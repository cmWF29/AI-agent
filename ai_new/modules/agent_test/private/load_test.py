"""并发压测：N 个项目 × M 个工单并发跑，LLM 全程走本地打桩网络服务，不接真实上游。

用法：
  python3 load_test.py                                   # 默认 100 项目 × 100 工单，16 并发
  python3 load_test.py --projects 2 --tickets 5 --workers 4   # 小规模冒烟
  python3 load_test.py --tool-rate 0.2 --delay 0.05      # 20% 回 tool_calls，桩加 50ms 延迟

打桩服务是标准库 ThreadingHTTPServer，按 OpenAI chat completion 的 SSE 格式随机回打桩
输出（纯文本收口，或按概率回一条 tool_calls）。被测系统在临时 data 目录里进程内装配，
llm.base_url 指到本地桩；全程不访问任何真实 LLM API。

脚本不被 unittest discover 收集（文件名不是 test_*.py），是手动跑的压测入口。
"""
import argparse
import gc
import os
import resource
import shutil
import sys
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))

from ai_new.modules.agent_common.boot.private._boot import _build as build  # noqa: E402
from ai_new.modules.agent_common.boot.private._context import Context  # noqa: E402
from ai_new.modules.agent_test.private import _fixtures  # noqa: E402
from ai_new.modules.agent_test.private import stub_llm  # noqa: E402


def start_stub(tool_rate, delay, delay_jitter=0.0, spawn_rate=0.0,
               pm_roles=None, role_rounds=1, filler_words=120):
    policy = stub_llm.StubPolicy(tool_rate=tool_rate, spawn_rate=spawn_rate,
                                 delay_base=delay, delay_jitter=delay_jitter,
                                 pm_roles=pm_roles, role_rounds=role_rounds,
                                 filler_words=filler_words)
    return stub_llm.start_stub(policy)


def clean_business(root, agent_subdir="agent"):
    """清空业务档案：项目/工单/会话/知识/产物；保留 library 种子与配置。返回删除条目数。

    兼容两种数据布局：源码树 <模块>/data/ 与 external 镜像 <模块>/（无 data 层），
    业务档案目录直接 rglob，避免持久根重复压测时上一轮残留撞号。
    agent_subdir 定位源码树 modules/agent 相对 root 的层级。
    """
    root = Path(root)
    business = ["projects", "tickets", "logs", "knowledge", "artifacts"]
    kept_templates = {"messages.yaml", "index.yaml"}
    removed = 0
    for mod in business:
        base = root / agent_subdir / mod
        if not base.is_dir():
            continue
        for rel in list(base.rglob("*")):
            if rel.is_dir():
                if rel.name.startswith("T-"):
                    shutil.rmtree(rel, ignore_errors=True)
                    removed += 1
                continue
            if rel.is_file() and rel.suffix in (".yaml", ".yml", ".json") \
                    and rel.name not in kept_templates:
                rel.unlink()
                removed += 1
    return removed


def assemble(stub_url, data_root=None, clean=False, source=False):
    """装配 ctx：llm 指桩，审计单检查关闭。

    source=True  落在源码树模块数据目录（与常驻进程同根）：不设外部镜像根、不重拷种子；
                 供线上压测让进程直接读到桩业务数据。
    data_root    持久化到该 external 镜像根；缺省用临时目录。
    """
    tmp = None
    if source:
        root = ROOT
        os.environ.pop("AI_NEW_DATA", None)
        if clean:
            n = clean_business(root, "ai_new/modules/agent")
            print("   清洗源码树业务档案: %d 项" % n)
    elif data_root:
        root = Path(data_root)
        root.mkdir(parents=True, exist_ok=True)
        if clean:
            n = clean_business(root)
            print("   清洗存量业务档案: %d 项" % n)
        _fixtures.stage(root)
    else:
        tmp = tempfile.mkdtemp(prefix="ai_new_load_")
        root = Path(tmp)
        _fixtures.stage(root)
    if not source:
        _fixtures.write_config(root, {
            "server": {"host": "127.0.0.1", "port": 0, "token": "t"},
            "llm": {"base_url": stub_url, "api_key": "stub", "model": "stub"},
            "tickets": {"stall_check": {"enabled": False}},
        })
        os.environ["AI_NEW_DATA"] = str(root)
    ctx = Context(root)
    build(ctx)
    # 桩地址注入内存配置；source 模式不落盘，避免覆盖源码树既有配置。
    ctx.cfg.setdefault("llm", {})["base_url"] = stub_url
    ctx.cfg["llm"]["api_key"] = "stub"
    ctx.cfg["llm"]["model"] = "stub"
    return ctx, root, tmp


def run_demand(ctx, demand, inp):
    return ctx.api.call("demand_engine.run", {"id": demand, "input": inp or {}})


def make_project(ctx, index):
    res = run_demand(ctx, "projects-create", {"name": "load-proj-%04d" % index})
    rec = res.get("result") or {}
    if rec.get("id"):
        return {"ok": True, "id": rec["id"], "err": None}
    return {"ok": False, "id": None, "err": rec.get("code") or res}


def make_ticket(ctx, project, index, retries=3):
    last = None
    for attempt in range(retries):
        res = run_demand(ctx, "ticket-create", {
            "title": "load 工单 %04d" % index,
            "goal": "并发压测打桩任务",
            "project": project})
        rec = res.get("result") or {}
        if rec.get("id") and rec.get("status"):
            return {"ok": True, "id": rec["id"], "status": rec["status"],
                    "pm": rec.get("pm"), "err": None}
        last = rec
        if rec.get("code") == "ticket_id_conflict":
            time.sleep(0.02 * (attempt + 1))  # 并发撞号：让出后重排序号
            continue
        break
    return {"ok": False, "id": None, "err": (last or {}).get("code") or last}


def _ids_from_glob(items, kind):
    """从 glob 相对路径解析记录 id：工单 tickets/T-x/ticket.yaml → T-x；会话 sessions/pm-1.yaml → pm-1。"""
    out = set()
    for rel in items or []:
        name = str(rel).rsplit("/", 1)[-1].rsplit(".", 1)[0]
        if kind == "ticket":
            parts = str(rel).split("/")
            if len(parts) >= 2 and parts[1].startswith("T-"):
                out.add(parts[1])
        else:
            prefix, _, tail = name.rpartition("-")
            if prefix in ("pm", "role") and tail.isdigit():
                out.add(name)
    return out


def _current_rss_mb():
    try:
        for line in open("/proc/self/status", encoding="utf-8"):
            if line.startswith("VmRSS:"):
                return round(int(line.split()[1]) / 1024, 1)
    except OSError:
        pass
    return -1.0


def mem_snapshot(ctx):
    """采样内存与运行期回收面：当前/峰值 RSS、存活线程、死线程字典、草稿槽、订阅者。"""
    rt = ctx.runtime
    return {
        "rss": _current_rss_mb(),
        "peak": round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024, 1),
        "threads": threading.active_count(),
        "runs": len(rt._runs),
        "stream": len(rt._stream),
        "subs": sum(len(v) for v in rt._subs.values()),
    }


def join_background(ctx, timeout):
    """等后台 session-run 线程收敛；回催会再 dispatch 同 key，轮询到无存活线程。

    finished 是 defer 钩子：首轮收尾只入队，必须由主线程 drain 派发，闭环才会二次
    驱动；线程归零后再 drain 一轮，避免错过首轮结束后才入队、刚起的新线程。
    """
    deadline = time.perf_counter() + timeout
    while time.perf_counter() < deadline:
        ctx.hooks.drain()
        alive = [t for t in ctx.runtime._runs.values() if t.is_alive()]
        if not alive:
            ctx.hooks.drain()
            if not [t for t in ctx.runtime._runs.values() if t.is_alive()]:
                return [], time.perf_counter()
        time.sleep(0.2)
        for t in alive:
            t.join(timeout=1.0)
    return [t for t in ctx.runtime._runs.values() if t.is_alive()], time.perf_counter()


def main(argv=None):
    ap = argparse.ArgumentParser(description="Hive AI 并发压测（本地打桩，不接真实 API）")
    ap.add_argument("--projects", type=int, default=10, help="项目数")
    ap.add_argument("--tickets", type=int, default=10, help="每项目工单数")
    ap.add_argument("--workers", type=int, default=16, help="并发线程数")
    ap.add_argument("--tool-rate", type=float, default=1.0,
                    help="角色上下文回写文件工具的概率 0~1，默认 1.0")
    ap.add_argument("--spawn-rate", type=float, default=1.0,
                    help="PM 上下文拉角色会话的概率 0~1，默认 1.0")
    ap.add_argument("--delay", type=float, default=0.02, help="桩每轮基础延迟秒")
    ap.add_argument("--delay-jitter", type=float, default=0.0,
                    help="桩附加随机抖动上限秒（网络波动）")
    ap.add_argument("--join-timeout", type=float, default=300, help="等待后台线程收敛上限秒")
    ap.add_argument("--data-root", default="", help="持久 data 镜像根；缺省用临时目录")
    ap.add_argument("--source-data", action="store_true",
                    help="直接落在源码树模块数据目录（与常驻进程同根），不落外部镜像根")
    ap.add_argument("--clean", action="store_true", help="建单前清空存量业务档案")
    ap.add_argument("--pm-roles", default="developer,tester,reviewer",
                    help="PM 依次分派的角色，逗号分隔")
    ap.add_argument("--role-rounds", type=int, default=1, help="角色读→写→备注重复遍数")
    ap.add_argument("--filler-words", type=int, default=120, help="桩每段正文字数")
    ap.add_argument("--keep-data", action="store_true", help="保留临时 data 目录供排查")
    args = ap.parse_args(argv)

    pm_roles = [r.strip() for r in args.pm_roles.split(",") if r.strip()]
    print("== 启动本地打桩服务（不接真实 API）")
    stub, stub_thread, stub_url = start_stub(args.tool_rate, args.delay,
                                            args.delay_jitter, args.spawn_rate,
                                            pm_roles, args.role_rounds, args.filler_words)
    print("   桩地址: %s | roles=%s rounds=%d words=%d delay=%.2fs"
          % (stub_url, pm_roles, args.role_rounds, args.filler_words, args.delay))

    ctx = root = tmp = None
    failures = []
    try:
        ctx, root, tmp = assemble(stub_url, args.data_root or None, args.clean,
                                  source=args.source_data)
        print("== 装配完成: %s" % root)
        m0 = mem_snapshot(ctx)

        # 阶段 A：并发建项目
        t0 = time.perf_counter()
        projects = []
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            futs = {pool.submit(make_project, ctx, i): i for i in range(args.projects)}
            for fut in as_completed(futs):
                r = fut.result()
                if r["ok"]:
                    projects.append(r["id"])
                else:
                    failures.append(("project", futs[fut], r["err"]))
        t_proj = time.perf_counter() - t0
        print("== 项目: 成功 %d / 失败 %d，耗时 %.2fs"
              % (len(projects), args.projects - len(projects), t_proj))

        if not projects:
            print("!! 没有项目建成，终止压测")
            return 1

        # 阶段 B：并发建工单（每项目 args.tickets 个）
        t1 = time.perf_counter()
        ticket_ok = ticket_fail = conflict = 0
        ticket_errs = []
        submitted_tickets = set()
        submitted_pms = set()
        pm_submitted = 0
        tasks = [(p, pidx, k) for pidx, p in enumerate(projects)
                 for k in range(args.tickets)]

        def _task(p, pidx, k):
            return make_ticket(ctx, p, pidx * args.tickets + k)

        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            futs = {pool.submit(_task, p, pidx, k): (pidx, k)
                    for p, pidx, k in tasks}
            for fut in as_completed(futs):
                r = fut.result()
                if r["ok"]:
                    ticket_ok += 1
                    submitted_tickets.add(r["id"])
                    if r["pm"]:
                        submitted_pms.add(r["pm"])
                        pm_submitted += 1
                else:
                    ticket_fail += 1
                    if r["err"] == "ticket_id_conflict":
                        conflict += 1
                    if len(ticket_errs) < 10:
                        ticket_errs.append((futs[fut], r["err"]))
        t_ticket = time.perf_counter() - t1
        m1 = mem_snapshot(ctx)
        total = args.projects * args.tickets
        print("== 工单: 成功 %d / 失败 %d（撞号 %d），共 %d，耗时 %.2fs"
              % (ticket_ok, ticket_fail, conflict, total, t_ticket))
        if ticket_errs:
            print("   错误抽样: %s" % ticket_errs)

        # 阶段 C：等后台会话线程收敛
        print("== 等待后台 session-run 线程收敛（上限 %.0fs）" % args.join_timeout)
        t2 = time.perf_counter()
        leftover, t_join = join_background(ctx, args.join_timeout)
        t_wait = t_join - t2
        print("== 后台线程: 残留 %d，等待 %.2fs" % (len(leftover), t_wait))
        m2 = mem_snapshot(ctx)
        gc.collect()
        m3 = mem_snapshot(ctx)
        print("== 内存/回收: 装配前 %s | 建单后 %s | 收敛后 %s | GC 后 %s" % (m0, m1, m2, m3))

        # 落盘计数与桩统计
        proj_items = (ctx.api.call("store.glob", {"module": "agent/projects",
                       "pattern": "*.yaml"}).get("items") or [])
        proj_items = [p for p in proj_items if not p.rsplit("/", 1)[-1] == "messages.yaml"]
        ticket_items = (ctx.api.call("store.glob", {"module": "agent/tickets",
                        "pattern": "tickets/T-*/ticket.yaml"}).get("items") or [])
        sess_items = (ctx.api.call("store.glob", {"module": "agent/logs",
                      "pattern": "sessions/*.yaml"}).get("items") or [])
        disk_tickets = _ids_from_glob(ticket_items, "ticket")
        lost_tickets = submitted_tickets - disk_tickets

        # 会话分组：PM 会话 vs 角色会话；角色按角色计数、判定工具步与收口。
        bound_role_sids = set()
        for rel in ticket_items:
            trow = ctx.api.call("store.read", {"module": "agent/tickets",
                                "path": rel})["value"]
            for r in trow.get("roles") or []:
                if r.get("session"):
                    bound_role_sids.add(r["session"])
        pm_sessions, role_sessions = [], []
        role_kinds, role_closed, role_with_tool = {}, 0, 0
        pm_msgs = role_msgs = 0
        for rel in sess_items:
            row = ctx.api.call("store.read", {"module": "agent/logs",
                              "path": rel})["value"]
            msgs = row.get("messages") or []
            if row.get("kind") == "pm":
                pm_sessions.append(row)
                pm_msgs += len(msgs)
            else:
                role_sessions.append(row)
                role_msgs += len(msgs)
                rk = row.get("role") or "?"
                role_kinds[rk] = role_kinds.get(rk, 0) + 1
                last_a = next((m for m in reversed(msgs) if m.get("role") == "assistant"), None)
                if last_a and not last_a.get("tool_calls"):
                    role_closed += 1
                if any(m.get("tool_calls") for m in msgs):
                    role_with_tool += 1
        total_msgs = pm_msgs + role_msgs
        pm_ids = {r.get("id") for r in pm_sessions}
        role_ids = {r.get("id") for r in role_sessions}
        orphan_sessions = (pm_ids - submitted_pms) | (role_ids - bound_role_sids)
        n_proj = len(proj_items)
        n_ticket = len(ticket_items)
        n_sess = len(sess_items)
        st = stub.stats
        total_sec = time.perf_counter() - t0
        print("\n== 压测结果")
        print("   落盘: 项目 %d | 工单 %d | 会话 %d（PM %d | 角色 %d）"
              % (n_proj, n_ticket, n_sess, len(pm_sessions), len(role_sessions)))
        per_ticket = (total_msgs / n_ticket) if n_ticket else 0.0
        print("   消息: 合计 %d（PM %d | 角色 %d）| 单工单均值 %.1f 条"
              % (total_msgs, pm_msgs, role_msgs, per_ticket))
        print("   工单: 提交 %d 次 | 塌缩/覆盖 %d | 唯一编号 %d | 落盘 %d | 丢失 %d"
              % (ticket_ok, ticket_ok - len(submitted_tickets),
                 len(submitted_tickets), n_ticket, len(lost_tickets)))
        print("   会话: 提交 PM %d | PM 落盘 %d | 角色落盘 %d | 孤儿 %d"
              % (pm_submitted, len(pm_sessions), len(role_sessions), len(orphan_sessions)))
        if role_kinds:
            print("   角色分布: %s" % role_kinds)
        print("   角色流程: 含工具步 %d | 已收口 %d" % (role_with_tool, role_closed))
        if lost_tickets:
            print("   丢失工单抽样: %s" % sorted(lost_tickets)[:10])
        if orphan_sessions:
            print("   孤儿会话抽样: %s" % sorted(orphan_sessions)[:10])
        print("   桩调用: 总 %d | 纯文本 %d | tool_calls %d | 错误 %d"
              % (st.calls, st.text, st.tool_calls, st.errors))
        print("   耗时: 建项目 %.2fs | 建工单 %.2fs | 等后台 %.2fs | 总计 %.2fs"
              % (t_proj, t_ticket, t_wait, total_sec))
        if t_ticket > 0:
            print("   吞吐: 工单 %.1f/s（建单阶段）" % (ticket_ok / t_ticket))
        if st.calls:
            print("   桩 RPS: %.1f/s（全流程）" % (st.calls / total_sec))
        if failures:
            print("   项目失败: %s" % failures[:10])
        ticket_collapse = ticket_ok - len(submitted_tickets)
        sess_collapse = pm_submitted - len(submitted_pms)
        clean = (ticket_fail == 0 and not lost_tickets and not orphan_sessions
                 and ticket_collapse == 0 and sess_collapse == 0 and not leftover)
        return 0 if clean else 2
    finally:
        stub.shutdown()
        stub_thread.join(timeout=2)
        http = getattr(ctx, "http", None)
        if http is not None:
            try:
                http.shutdown()
                http.server_close()
            except Exception:  # noqa: BLE001
                pass
        os.environ.pop("AI_NEW_DATA", None)
        if tmp and not args.keep_data:
            shutil.rmtree(tmp, ignore_errors=True)
        elif tmp:
            print("   保留临时数据目录: %s" % tmp)
        elif root:
            print("   持久数据保留在: %s" % root)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
