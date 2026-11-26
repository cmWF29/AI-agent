"""L7 运维韧性层（ST）：落盘、服务中断恢复、数据迁移、上游挂起。

这四件事在进程内打桩全部演不出来，必须真起服务、真写目录、真换进程：
- 落盘：一次真实业务闭环之后，项目/工单/会话记录/日志索引/知识/定时审计必须在
  数据目录里真的存在，且内容对得上业务对象（不是内存里的假象）；
- 恢复：把服务停掉、不留进程，只用同一份数据目录重新装配，历史必须都在、还能接着写；
- 迁移：整棵目录换到另一个路径（等价换机器/换 VPS），内容一致且新根可写，
  同时旧根不被新根的写入污染；
- 挂起：上游接受连接但永不应答，服务必须在有限时间内回到 idle，不许挂死、不许伪造回复。
"""
from __future__ import annotations

import json
import os
import shutil
import socket
import socketserver
import sys
import tempfile
import threading
import time
from pathlib import Path

from report import LayerResult, Timer

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "assert"))
from recorder import Recorder  # noqa: E402

from layers import _bootstrap  # noqa: E402

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "scripts"))
from perf_http import Client  # noqa: E402

_IDLE_WAIT = 25.0


def _client(port):
    return Client("http://127.0.0.1:%d" % port, "t")


def _call(c, demand_id, payload=None):
    """真 RPC 调一手需求；业务失败直接抛，免得后面读到半成品状态。"""
    sample, data = c.rpc(demand_id, payload or {})
    outer = data.get("result") if isinstance(data, dict) else {}
    if not sample.ok or not isinstance(outer, dict) or outer.get("ok") is False:
        raise RuntimeError("%s 失败: %s / %s" % (demand_id, sample.code, outer))
    value = outer.get("result")
    return value if isinstance(value, dict) else {}


def _messages(c, ticket):
    out = _call(c, "ticket-thread", {"id": ticket})
    return list((out.get("thread") or {}).get("messages") or [])


def _wait_assistant(c, ticket, timeout=_IDLE_WAIT):
    """等这一轮真收口：thread 里出现 assistant 回复才算成，超时返回当时的条数。"""
    deadline = time.time() + timeout
    count = 0
    while time.time() < deadline:
        count = len(_messages(c, ticket))
        if count >= 2:
            return count
        time.sleep(0.4)
    return count


def _wait_idle(c, ticket, timeout=40.0):
    """等会话状态机回 idle：停机前必须确保没有在途轮次，否则快照条数会漂。"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if _thread_status(c, ticket) == "idle":
            return True
        time.sleep(0.3)
    return False


def _thread_status(c, ticket):
    """会话状态机里的 running/idle：判「真收口」只能读它，不能只看条数。"""
    out = _call(c, "ticket-thread", {"id": ticket})
    return str((out.get("thread") or {}).get("status") or "")


def _snapshot(root):
    return {os.path.relpath(os.path.join(dp, f), root)
            for dp, _dn, fn in os.walk(root) for f in fn}


def _log_sizes(root):
    """会话/日志文件的大小快照：写入可能是追加到既有文件，新增文件判不出变化。"""
    out = {}
    for sub in ("agent/logs",):
        for dp, _dn, fn in os.walk(Path(root) / sub):
            for f in fn:
                fp = Path(dp) / f
                if fp.suffix in (".yaml", ".jsonl", ".txt"):
                    out[str(fp)] = fp.stat().st_size
    return out


def _timer_row(c, timer_id):
    rows = _call(c, "timer-list", {"caller": {"scope": "global"}})
    return next((x for x in (rows.get("items") or []) if x.get("id") == timer_id), None)


class _Hang:
    """接受连接但永不应答的上游：专门演「连得上、读不回来」的超时路径。"""

    def __init__(self) -> None:
        self.hits = 0
        self._held = []
        outer = self
        srv = self

        class Handler(socketserver.BaseRequestHandler):
            def handle(self):
                srv.hits += 1
                outer._held.append(self.request)
                # 读掉请求头后既不回包也不关连接，让对端一直挂在读上。
                try:
                    self.request.settimeout(0.5)
                    self.request.recv(4096)
                except Exception:  # noqa: BLE001 —— 演练里断不断都无所谓
                    pass
                time.sleep(3600)

        class Server(socketserver.ThreadingTCPServer):
            daemon_threads = True
            allow_reuse_address = True

        self._sock = Server(("127.0.0.1", 0), Handler)
        self.port = self._sock.server_address[1]
        self._thread = threading.Thread(target=self._sock.serve_forever, daemon=True)
        self._thread.start()

    def close(self) -> None:
        for s in self._held:
            try:
                s.close()
            except Exception:  # noqa: BLE001
                pass
        try:
            self._sock.shutdown()
            self._sock.server_close()
        except Exception:  # noqa: BLE001
            pass


def _disk_checks(rec, boot, project, ticket, marker):
    """落盘断言：业务对象在盘上各自有位置，内容也要对得上。"""
    root = boot.root
    files = _snapshot(root)
    proj_file = "agent/projects/%s.yaml" % project
    rec.check("落盘·项目文件", proj_file in files, proj_file)
    tpath = "agent/tickets/projects/%s/tickets/%s/ticket.yaml" % (project, ticket)
    rec.check("落盘·工单文件", tpath in files, tpath)
    if tpath in files:
        text = (root / tpath).read_text(encoding="utf-8")
        rec.check("落盘·工单正文含标题", "落盘巡检工单" in text, text[:200])
    sessions = [f for f in files if f.startswith("agent/logs/sessions/") and f.endswith(".yaml")]
    rec.check("落盘·会话记录", bool(sessions), "会话记录 %d 份" % len(sessions))
    hit = [f for f in sessions if "落盘巡检工单" in (root / f).read_text(encoding="utf-8")]
    rec.check("落盘·会话记录含本单上下文", bool(hit), "命中记录: %s" % hit[:3])
    index = root / "agent/logs/index.yaml"
    rec.check("落盘·日志索引存在", index.is_file() and index.stat().st_size > 0)
    if index.is_file():
        seen = ticket in index.read_text(encoding="utf-8")
        rec.check("落盘·日志索引登记本单", seen,
                  "索引%s %s" % ("含" if seen else "缺", ticket))
    kn = root / ("agent/knowledge/public/%s.md" % marker)
    rec.check("落盘·知识正文", kn.is_file(), str(kn))
    if kn.is_file():
        rec.check("落盘·知识内容一致", "# 落盘巡检" in kn.read_text(encoding="utf-8"))
    audit = root / "agent/timer/audit.jsonl"
    rec.check("落盘·定时器审计", audit.is_file() and "create" in audit.read_text(encoding="utf-8"),
              str(audit))


def _persist_and_restart(rec):
    """一次真业务闭环 → 关服务 → 同一目录重装 → 历史还在且能接着写。"""
    stamp = int(time.time())
    project = "落盘巡检%d" % stamp
    marker = "disk-%d" % stamp
    boot = _bootstrap.boot(overrides={"timer": {"tick_interval_s": 3600, "min_interval_s": 0}})
    ticket = ""
    try:
        c = _client(boot.port)
        project_id = _call(c, "projects-create", {"name": project})["id"]
        ticket = _call(c, "ticket-create", {"project": project_id,
                                            "title": "落盘巡检工单",
                                            "goal": "验证落盘、重启恢复与迁移"})["id"]
        _call(c, "ticket-message", {"id": ticket, "text": "落盘标记 %s" % marker})
        got = _wait_assistant(c, ticket)
        rec.check("闭环·本轮真收口", got >= 2, "thread 消息 %d 条" % got)
        _wait_idle(c, ticket)
        _call(c, "knowledge-write", {"layer": "public", "name": marker, "content": "# 落盘巡检\n正文"})
        timer = _call(c, "timer-create", {
            "project": project_id, "kind": "once", "expr": "2030-01-01T00:00:00+00:00",
            "tz": "UTC", "title": "落盘巡检定时器", "action": "notify",
            "caller": {"scope": "global"}})
        rec.check("落盘·定时器已建", bool(timer.get("id")), str(timer)[:200])
        _disk_checks(rec, boot, project, ticket, marker)
        before_msgs = _messages(c, ticket)
        before = len(before_msgs)
        before_sig = [(m.get("role"), m.get("session"), m.get("content")) for m in before_msgs]
        before_files = _snapshot(boot.root)
        before_sizes = _log_sizes(boot.root)
        c.close()

        boot.stop()
        rec.check("恢复·服务已停机", True, "端口 %d 已释放" % boot.port)
        dead = True
        try:
            sock = socket.create_connection(("127.0.0.1", boot.port), timeout=1.0)
            sock.close()
            dead = False
        except OSError:
            dead = True
        rec.check("恢复·旧端口确实关掉", dead,
                  "端口 %d %s" % (boot.port, "已拒绝连接" if dead else "仍能连上"))

        # 换一份进程内装配，只认同一份数据目录——历史只能来自盘，不可能来自内存。
        reboot = _bootstrap.boot(root=boot.root)
        try:
            c2 = _client(reboot.port)
            tree = _call(c2, "project-tree", {})
            names = [((it.get("project") or {}).get("name")) for it in (tree.get("items") or [])]
            rec.check("恢复·项目还在", project in names, "项目树 %s" % names[:6])
            got = _call(c2, "ticket-get", {"id": ticket})
            rec.check("恢复·工单还在", (got.get("ticket") or got).get("id") == ticket, str(got)[:200])
            after_msgs = _messages(c2, ticket)
            after = len(after_msgs)
            after_sig = [(m.get("role"), m.get("session"), m.get("content")) for m in after_msgs]
            # 重启期间会话续跑可能补一条系统消息，因此判「原有消息逐条还在且不减」，
            # 而不是拿总条数卡死相等。
            kept = after_sig[:len(before_sig)] == before_sig and after >= before
            rec.check("恢复·历史 thread 不丢", kept,
                      "原 %d 条%s，总 %d 条" % (before, "都在" if kept else "有缺失", after))
            row = _timer_row(c2, timer.get("id"))
            rec.check("恢复·定时器还在", row is not None and row.get("status") == "active", str(row)[:200])
            kn = _call(c2, "knowledge-read", {"layer": "public", "name": marker})
            rec.check("恢复·知识还在", "落盘巡检" in str(kn), str(kn)[:200])

            _call(c2, "ticket-message", {"id": ticket, "text": "重启后第二轮 %s" % marker})
            grew = _wait_assistant(c2, ticket)
            rec.check("恢复·能接着写", grew > after, "%d → %d" % (after, grew))
            after_files = _snapshot(boot.root)
            after_sizes = _log_sizes(boot.root)
            grew_files = len(after_files) - len(before_files)
            grew_logs = sum(1 for k, v in after_sizes.items() if before_sizes.get(k, 0) != v)
            rec.check("恢复·第二轮写入真落盘", grew_files > 0 or grew_logs > 0,
                      "新增文件 %d 份，日志变动 %d 份" % (grew_files, grew_logs))

            c2.close()
        finally:
            reboot.cleanup()
    finally:
        boot.cleanup()


def _migrate_checks(rec):
    """整树复制到新根：等价换机器，内容一致、新根可写、旧根不被污染。"""
    stamp = int(time.time())
    project = "迁移巡检%d" % stamp
    boot = _bootstrap.boot()
    dest = Path(tempfile.mkdtemp(prefix="ai_new_migrate_"))
    try:
        c = _client(boot.port)
        project_id = _call(c, "projects-create", {"name": project})["id"]
        ticket = _call(c, "ticket-create", {"project": project_id,
                                            "title": "迁移巡检工单",
                                            "goal": "验证换根后内容一致且可写"})["id"]
        _call(c, "ticket-message", {"id": ticket, "text": "迁移标记 %s" % stamp})
        _wait_assistant(c, ticket)
        c.close()
        boot.stop()

        shutil.copytree(boot.root, dest, dirs_exist_ok=True)
        old_files = _snapshot(boot.root)
        moved = _bootstrap.boot(root=dest)
        try:
            c2 = _client(moved.port)
            tree = _call(c2, "project-tree", {})
            names = [((it.get("project") or {}).get("name")) for it in (tree.get("items") or [])]
            rec.check("迁移·项目随盘搬过去", project in names, "项目树 %s" % names[:6])
            got = _call(c2, "ticket-get", {"id": ticket})
            rec.check("迁移·工单随盘搬过去", (got.get("ticket") or got).get("id") == ticket, str(got)[:160])
            msgs = _messages(c2, ticket)
            rec.check("迁移·history 不丢", len(msgs) >= 2, "消息 %d 条" % len(msgs))
            _call(c2, "knowledge-write", {"layer": "public", "name": "migrate-%d" % stamp,
                                          "content": "# 迁移后写入"})
            wrote = (dest / ("agent/knowledge/public/migrate-%d.md" % stamp)).is_file()
            rec.check("迁移·新根可写", wrote, "新根知识文件 %s" % ("已写出" if wrote else "缺"))
            c2.close()
        finally:
            moved.cleanup()
        same = _snapshot(boot.root) == old_files
        rec.check("迁移·旧根不被新根写脏", same,
                  "旧根文件 %d 份，%s" % (len(old_files), "未变" if same else "被写脏"))
    finally:
        boot.cleanup()
        shutil.rmtree(dest, ignore_errors=True)


def _hang_checks(rec):
    """上游接受连接但永不应答：不许挂死、不许伪造回复，超时后必须回 idle。"""
    hang = _Hang()
    boot = None
    try:
        boot = _bootstrap.boot(
            overrides={"llm": {"base_url": "http://127.0.0.1:%d/v1" % hang.port,
                               "api_key": "k", "model": "stub", "timeout": 2}},
            stub_net=False)
        c = _client(boot.port)
        project_id = _call(c, "projects-create", {"name": "挂起巡检%d" % int(time.time())})["id"]
        ticket = _call(c, "ticket-create", {"project": project_id, "title": "上游挂起工单",
                                            "goal": "读超时后必须回 idle"})["id"]
        started = time.time()
        _call(c, "ticket-message", {"id": ticket, "text": "上游永不应答"})
        deadline = started + 70.0
        idle_at = 0.0
        while time.time() < deadline:
            time.sleep(0.4)
            # status 是会话自己的状态机：running → idle 才算真收口，条数不变不算。
            if _thread_status(c, ticket) == "idle" and time.time() - started > 1.0:
                idle_at = time.time() - started
                break
        rec.check("挂起·回到 idle", idle_at > 0.0,
                  "%.1fs %s" % (idle_at or time.time() - started,
                                "回 idle" if idle_at else "内未回 idle"))
        rec.check("挂起·有限时间内降级", 0.0 < idle_at < 65.0, "耗时 %.1fs" % idle_at)
        faked = [m for m in _messages(c, ticket) if m.get("role") == "assistant"]
        rec.check("挂起·未伪造回复", not faked, "assistant 回复 %d 条" % len(faked))
        rec.check("挂起·真打到上游", hang.hits > 0, "上游命中 %d 次" % hang.hits)
        # 降级之后服务必须还能接下一单：挂死的服务这一条必炸。
        _call(c, "projects-create", {"name": "挂起后仍可用%d" % int(time.time())})
        rec.check("挂起·降级后服务可用", True)
        c.close()
    finally:
        hang.close()
        if boot is not None:
            boot.cleanup()


def _cron_checks(rec):
    """cron 到点真触发（不是 once）：后台扫描线程必须自己不靠接口把手就建出单来。"""
    stamp = int(time.time())
    project = "cron巡检%d" % stamp
    boot = _bootstrap.boot(overrides={"timer": {"tick_interval_s": 1, "min_interval_s": 0}})
    try:
        c = _client(boot.port)
        project_id = _call(c, "projects-create", {"name": project})["id"]
        timer = _call(c, "timer-create", {
            "project": project_id, "kind": "cron", "expr": "* * * * *", "tz": "UTC",
            "title": "每分钟建单", "action": "spawn_ticket",
            "caller": {"scope": "global"}})
        rec.check("cron·定时器已建", bool(timer.get("id")), str(timer)[:200])
        deadline = time.time() + 90.0
        row = None
        while time.time() < deadline:
            time.sleep(1.0)
            row = _timer_row(c, timer.get("id")) or {}
            if (row.get("last_run") or {}).get("ok"):
                break
        run = (row or {}).get("last_run") or {}
        rec.check("cron·到点真触发", bool(run.get("ok")), str(row)[:300])
        tickets = _call(c, "ticket-list", {"project": project_id})
        count = len(tickets.get("items") or [])
        rec.check("cron·真建出工单", count >= 1, "工单 %d 条" % count)
        timers = boot.root / ("agent/timer/projects/%s/timers.yaml" % project)
        text = timers.read_text(encoding="utf-8") if timers.is_file() else ""
        fired = [ln for ln in text.splitlines() if ln.strip().startswith("- ") and ":" in ln and "T" in ln]
        rec.check("cron·槽位落盘", bool(fired), "timers.yaml 槽位行 %s" % fired[:4])
        c.close()
    finally:
        boot.cleanup()


def run(timeout: float = 300.0) -> LayerResult:
    rec = Recorder()
    output = []
    with Timer() as t:
        for name, fn in (("落盘与重启恢复", _persist_and_restart),
                         ("数据迁移", _migrate_checks),
                         ("上游挂起", _hang_checks),
                         ("cron 到点触发", _cron_checks)):
            try:
                output.append("== %s" % name)
                fn(rec)
            except Exception as exc:  # noqa: BLE001 —— 整段崩了也要留证据
                rec.check(name, False, repr(exc))
    return LayerResult(
        layer="L7", title="运维韧性 E2E（落盘 / 重启恢复 / 迁移 / 上游挂起 / cron）",
        ok=rec.ok, duration=t.elapsed, checks=rec.checks, output="\n".join(output),
        note="真目录、真停服、真换根、真挂起：落盘内容对得上业务对象，重启后同一份数据可继续写，"
             "整树搬到新根内容一致且旧根不被污染，上游只接不回时有限时间内降级不伪造，"
             "cron 由后台扫描线程自己到点建单。",
    )
