"""核心流程冒烟：真实装配（临时 data 目录）+ HTTP 端到端。

业务闭环一律走需求入口（demand_engine.run），模块能力只在纯形状/守卫层做单点断言。
"""
import yaml
import os
import sys
import tempfile
import unittest
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))

from ai_new.modules.agent_common.boot.private._boot import _build as build  # noqa: E402
from ai_new.modules.agent_common.boot.private._context import Context  # noqa: E402
from ai_new.modules.agent.auth.private import _pure as auth_pure  # noqa: E402
from ai_new.modules.agent.library.private import _pure as lib_pure  # noqa: E402
from ai_new.modules.agent.sessions.private import _run_pure as sess_run  # noqa: E402
from ai_new.modules.agent.tickets.private import _pure as ticket_pure  # noqa: E402
from ai_new.modules.agent_common.react.private import _pure as react_pure  # noqa: E402
from _fixtures import stage, write_config  # noqa: E402
import _fixtures  # noqa: E402


class FakeNet:
    """测试用传输：不联网，按 OpenAI 的形状回一段 JSON（编排和编解码都真跑）。"""

    def __init__(self):
        self.calls = 0

    def __call__(self, ctx, payload):
        self.calls += 1
        return {"ok": True, "status": 200, "headers": {},
                "text": '{"choices":[{"message":{"content":"（测试）已完成。"},'
                        '"finish_reason":"stop"}],"usage":null}'}


def _demand_bound_routes():
    """需求 do 树编排的路由 ∪ 已编排聚合能力的内部路由（B1 下沉，见 capability-routes.yaml）。"""
    from ai_new.modules.agent_common.demand_engine.private import _lang
    demand_bound = set()
    demands = _fixtures.module_data("agent_common", "demand_engine") / "demands"
    for path in sorted(demands.glob("*.yaml")):
        rec = yaml.safe_load(path.read_text(encoding="utf-8"))
        demand_bound.update(_lang.routes_of(rec.get("do")))
    cap_path = ROOT / "ai_new/modules/agent_common/api/data/capability-routes.yaml"
    internal = set()
    if cap_path.is_file():
        manifest = yaml.safe_load(cap_path.read_text(encoding="utf-8")) or {}
        for name, spec in (manifest.get("capabilities") or {}).items():
            if name in demand_bound:
                internal.update(spec.get("calls") or [])
    return demand_bound | internal


class CoreTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        root = Path(cls.tmp.name)
        stage(root)
        write_config(root, {
            "server": {"host": "127.0.0.1", "port": 0, "token": "t"},
            "llm": {"base_url": "http://stub.local/v1", "api_key": "k", "model": "stub"},
            "tickets": {"stall_check": {"enabled": False}},
        })
        os.environ["AI_NEW_DATA"] = str(root)
        cls.ctx = Context(root)
        cls.loaded = build(cls.ctx)
        cls.fake_net = FakeNet()
        cls.ctx.api.substitute("net.request", cls.fake_net)
        cls.server = cls.ctx.http
        cls.port = cls.server.server_address[1]

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        os.environ.pop("AI_NEW_DATA", None)
        cls.tmp.cleanup()

    # ---- 架构不变量 ----

    def test_all_modules_loaded(self):
        expect = {"config", "store", "hooks", "demand_engine", "api", "tools", "llm", "react",
                  "knowledge", "artifacts", "library", "sessions", "projects",
                  "tickets", "agents", "health", "ops", "skills", "web", "http",
                  "channel", "net", "host", "codec", "clock", "auth", "runtime", "exec",
                  "decompose"}
        self.assertEqual(set(self.loaded), expect)

    def test_modules_have_no_log_capability(self):
        """ctx 上没有日志：记日志是运维的业务，模块只能 emit hook。"""
        self.assertFalse(hasattr(self.ctx, "log"), "ctx 不该有 log 能力")
        self.assertFalse(hasattr(self.ctx, "bus"), "ctx 不该有总线能力")
        self.assertTrue(hasattr(self.ctx, "hooks"), "ctx 应该有 hooks 能力")

    def test_runtime_hook_points_match_static_scan(self):
        """运行期的点必须等于静态扫描出来的点：否则静态图就是在骗人。"""
        from ai_new.modules.agent_common.boot.private._boot import _plan
        static = set(_plan()["hooks"]["declared"])
        runtime = {p["name"] for p in self.ctx.api.call("hooks.points")}
        self.assertEqual(runtime, static)

    def test_demand_calls_bind_to_real_routes(self):
        """需求绑定的 func 必须真注册：改函数名/删函数，静态和运行期都躲不过。"""
        from ai_new.modules.agent_common.demand_engine.private import _lang
        meta = {r["name"] for r in self.ctx.api.routes()}
        problems = []
        for path in sorted(_fixtures.module_data("agent_common", "demand_engine")
                           .joinpath("demands").glob("*.yaml")):
            rec = yaml.safe_load(path.read_text(encoding="utf-8"))
            for route in _lang.routes_of(rec.get("do")):
                if route not in meta:
                    problems.append("%s 调了不存在的 func: %s" % (rec.get("id"), route))
        self.assertEqual(problems, [], "需求绑定了不存在的功能: %s" % problems)

    def test_registered_routes_are_demand_bound_or_platform(self):
        """注册表只收两类路由：被需求 do 树编排的业务能力，或清单登记的平台入口。

        只在模块内部进程内直调、不被任何需求/外部调用的纯函数，不许挂成 API。
        """
        from ai_new.modules.agent_common.demand_engine.private import _lang
        demand_bound = _demand_bound_routes()
        manifest = yaml.safe_load((ROOT / "ai_new/modules/agent_common/api/data"
                               / "platform-routes.yaml").read_text(encoding="utf-8"))
        platform = set(manifest.get("routes") or {})
        registered = {r["name"] for r in self.ctx.api.routes()}
        stray = sorted(registered - demand_bound - platform)
        self.assertEqual(stray, [],
                         "注册了既无需求编排、也未登记为平台入口的路由: %s" % stray)

    def test_write_routes_are_governed(self):
        """落盘是有副作用的业务动作：写能力要么被需求编排，要么是清单登记的平台件。

        不允许模块/注册表隐式写盘：存什么、存哪、怎么存，都要能追溯到需求或平台授权。
        """
        from ai_new.modules.agent_common.demand_engine.private import _lang
        demand_bound = _demand_bound_routes()
        manifest = yaml.safe_load((ROOT / "ai_new/modules/agent_common/api/data"
                               / "platform-routes.yaml").read_text(encoding="utf-8"))
        platform = set(manifest.get("routes") or {})
        write_routes = {
            "store.write", "store.write_text", "store.write_bytes", "store.append_text",
            "store.remove", "store.remove_dir", "store.archive", "config.set",
            "demand_engine.enable", "demand_engine.disable",
        }
        registered = {r["name"] for r in self.ctx.api.routes()}
        ungoverned = sorted((write_routes & registered) - demand_bound - platform)
        self.assertEqual(ungoverned, [], "存在未被需求或平台授权的写路由: %s" % ungoverned)


    def test_console_carries_no_business_demand_ids(self):
        """控制台外壳只认规格，不许自带第二份需求清单。

        HTML/JS 里出现需求 id 字面量，就等于页面又存了一份需求：改需求会漏改页面。
        允许的只有清单登记的平台入口（views-list / auth-logout）。
        """
        console = ROOT / "ai_new/modules/agent/web/data/console"
        html = "\n".join(f.read_text(encoding="utf-8") for f in sorted(
            list(console.glob("*.html")) + list(console.glob("*.js"))))
        entries = yaml.safe_load((ROOT / "ai_new/modules/agent_common/demand_engine/data"
                                 / "console-entries.yaml").read_text(encoding="utf-8"))
        allowed = set(entries.get("entries") or [])
        demands_dir = ROOT / "ai_new/modules/agent_common/demand_engine/data/demands"
        ids = {p.stem for p in demands_dir.glob("*.yaml")}
        hits = sorted(d for d in ids
                      if ('"%s"' % d) in html or ("'%s'" % d) in html)
        stray = [h for h in hits if h not in allowed]
        self.assertEqual(stray, [],
                         "控制台硬编码了业务需求 id，外壳又存了一份需求清单: %s" % stray)

    # ---- 需求编排闭环 ----

    def _run(self, demand, input=None):
        """按名跑一条 callable 需求，返回引擎结果 {ok, demand, result, calls}。"""
        return self.ctx.api.call("demand_engine.run",
                                 {"id": demand, "input": input or {}})

    def _glob(self, module, pattern):
        return self.ctx.api.call("store.glob",
                                 {"module": module, "pattern": pattern})["items"]

    def test_knowledge_roundtrip(self):
        self._run("knowledge-write", {"layer": "public", "name": "arch-note",
                                      "content": "架构约定：模块只能通过 api 调用。"})
        r = self._run("knowledge-read", {"layer": "public", "name": "arch-note"})
        self.assertIn("架构约定", r["result"]["content"])
        # public 层没有就是没有：读不到回 not_found，不抛异常
        miss = self._run("knowledge-read", {"layer": "public", "name": "secretary"})
        self.assertFalse(miss["result"].get("ok", True))
        # 结构化计划要素已下沉 public 知识库：可按名读到模板正文
        tmpl = self._run("knowledge-read", {"layer": "public", "name": "plan-structure"})["result"]
        self.assertIn("计划结构模板", tmpl["content"])
        self.assertIn("验收标准", tmpl["content"])
        # 检索与注入链路递归扫到 public 子目录种子，文本进匹配与注入结果
        found = self._run("knowledge-search", {"query": "验收标准"})["result"]
        self.assertTrue(any("plan-structure" in i["path"] for i in found["items"]))
        comp = self._run("knowledge-compose", {"prefixes": ["public/"]})["result"]
        self.assertIn("计划结构模板", comp["text"])
        self.assertIn("验收标准", comp["text"])

    def test_channel_post_tail_roundtrip(self):
        """频道：需求发两条、按序读回；watch 门面按游标回 {items, cursor}。"""
        self._run("channel-post", {"channel": "probe-ch", "role": "user", "content": "一"})
        self._run("channel-post", {"channel": "probe-ch", "role": "user", "content": "二"})
        t = self._run("channel-tail", {"channel": "probe-ch", "limit": 5})["result"]
        mine = [m["content"] for m in t["messages"] if m["role"] == "user"]
        self.assertEqual(mine, ["一", "二"])
        meta = {r["name"]: r for r in self.ctx.api.routes()}
        self.assertIn("channel.tail", meta)
        # watch 是流式门面：委托 channel-since，按游标取增量
        self.assertTrue(meta["channel.watch"]["stream"])
        w = self.ctx.api.call("channel.watch", {"channel": "probe-ch", "cursor": 0})
        self.assertGreaterEqual(w["cursor"], 2)
        self.assertTrue(any(i["content"] == "二" for i in w["items"]))
        # 游标之后不再重复推
        w2 = self.ctx.api.call("channel.watch", {"channel": "probe-ch", "cursor": w["cursor"]})
        self.assertEqual(w2["items"], [])
        self.ctx.hooks.drain()   # 收尾：延迟点在这里跑掉，不留给下一条用例

    def test_chat_demand_answers_and_does_not_self_trigger(self):
        """一条业务闭环：用户消息 → 模型 → 回复写回；assistant 不再触发模型。

        channel.posted 是延迟点：发消息的请求只入队，响应写完（drain）之后才跑模型。
        """
        key = "rt-chat"
        self.ctx.hooks.clear()
        before = self.fake_net.calls
        self._run("channel-post", {"channel": key, "role": "user", "content": "在吗"})
        self.assertEqual(self.fake_net.calls, before, "发消息的请求里不该等模型")
        self.assertEqual(self.ctx.hooks.pending(), 1, "应该有一个延迟派发在排队")
        self.ctx.hooks.drain()
        self.assertEqual(self.fake_net.calls, before + 1, "响应写完后的延迟派发要跑一次模型")
        rows = self._run("channel-tail", {"channel": key, "limit": 10})["result"]["messages"]
        self.assertEqual(rows[-1]["role"], "assistant")
        self.assertIn("测试", rows[-1]["content"])
        self.ctx.hooks.drain()   # assistant 落盘也会触发一次点，需求自己按 role 跳过
        self.assertEqual(self.fake_net.calls, before + 1, "assistant 消息不能再触发模型（会自激）")

    def test_internal_routes_are_not_reachable_over_http(self):
        """起进程这类能力只给进程内用：HTTP 通道一律 403，不给远程执行留口子。"""
        body = self.ctx.codec.yaml_encode({"argv": ["python3", "-c", "print(1)"]}).get("text") or ""
        req = urllib.request.Request(
            "http://127.0.0.1:%d/api/rpc/exec/run" % self.port,
            data=str(body).encode("utf-8"),
            headers={"X-Auth-Token": "t", "Content-Type": "application/yaml"})
        with self.assertRaises(urllib.error.HTTPError) as cm:
            urllib.request.urlopen(req, timeout=5)
        self.assertEqual(cm.exception.code, 403)
        self.assertNotIn("exec.run", [r["name"] for r in self.ctx.api.routes()],
                         "内部路由不该出现在对外路由清单里")

    def test_agent_stream_draft_grows_and_clears(self):
        """agent 边跑边吐：运行期草稿中途可见增长，一轮定稿后清空，不落盘。"""
        import threading, time as _time, tempfile, os, pathlib
        script = pathlib.Path(tempfile.mkdtemp()) / "stream_agent.py"
        script.write_text("import time\nprint('L1', flush=True); time.sleep(0.8); "
                          "print('L2', flush=True); time.sleep(0.8); print('L3')", encoding="utf-8")
        cfg = self.ctx.cfg.setdefault("llm", {})
        keep = dict(cfg)
        cfg["mode"] = "agent"
        cfg["agent"] = {"command": ["python3", str(script)], "timeout": 20}
        key = "draft-probe"
        seen, box = [], {}
        def worker():
            box["r"] = self._run("react-run", {
                "messages": [{"role": "user", "content": "x"}],
                "mode": "agent", "tools": [],
                "cancel": {"id": key, "since": 0}})["result"]
        th = threading.Thread(target=worker, daemon=True)
        th.start()
        for _ in range(40):
            _time.sleep(0.2)
            d = self.ctx.runtime.stream_get(key)
            if d["text"]:
                seen.append(d["text"])
            if not th.is_alive():
                break
        th.join()
        try:
            self.assertGreaterEqual(len(seen), 2, "草稿应在中途多次被读到")
            self.assertIn("L1", seen[0])
            msgs = box["r"].get("messages") or []
            self.assertIn("L3", msgs[-1].get("content") or "")
            final = self.ctx.runtime.stream_get(key)
            self.assertFalse(final["running"], "定稿后草稿必须清空")
        finally:
            cfg.clear(); cfg.update(keep)
            script.unlink(missing_ok=True)

    def test_agent_process_is_killed_on_cancel(self):
        """打断要真停：外部 agent 进程被 kill，能在秒级收尾，不拖到自然跑完。"""
        cfg = self.ctx.cfg.setdefault("llm", {})
        keep = dict(cfg)
        cfg["mode"] = "agent"
        cfg["agent"] = {"command": ["python3", "-c", "import time; time.sleep(30)"],
                        "timeout": 40}
        now = self.ctx.api.call("clock.now", {})["ts"]
        gate = {"id": "cancel-probe", "since": now}
        # 模拟"有人按了打断"：打断位比本轮开始时间更晚
        self.ctx.runtime._cancel["cancel-probe"] = now + 5
        try:
            started = __import__("time").time()
            r = self._run("llm-chat", {"messages": [{"role": "user", "content": "跑个长任务"}],
                                       "cancel": gate})["result"]
            spent = __import__("time").time() - started
            self.assertEqual(r.get("killed"), "cancelled", "被打断的进程要报 cancelled: %s" % r)
            self.assertLess(spent, 5, "打断应在秒级生效，实际 %.1fs" % spent)
        finally:
            self.ctx.runtime._cancel.pop("cancel-probe", None)
            cfg.clear()
            cfg.update(keep)

    def test_runtime_stop_cancels_and_joins_running_thread(self):
        """purge 硬删会话前：stop 置打断位、等线程收尾，再从运行表摘除，定稿不会写回。"""
        import threading, time as _time
        box = {"done": False}
        def work():
            _time.sleep(0.05)
            box["done"] = True
        th = threading.Thread(target=work, daemon=True)
        th.start()
        self.ctx.runtime._runs["stop-probe"] = th
        self.ctx.runtime.stop("stop-probe")
        self.assertNotIn("stop-probe", self.ctx.runtime._runs)
        self.assertNotIn("stop-probe", self.ctx.runtime._cancel)
        self.assertFalse(self.ctx.runtime.cancelled("stop-probe", 0))
        self.assertTrue(box["done"], "stop 应 join 等线程收尾后再返回")

    def test_agent_backend_runs_external_command(self):
        """agent 模式：对话拼成一段话交给外部进程，收回 stdout 当答复。

        外部 agent 自带工具闭环，所以返回里没有 tool_calls，ReAct 一轮即可收口。
        """
        cfg = self.ctx.cfg.setdefault("llm", {})
        keep = dict(cfg)
        cfg["mode"] = "agent"
        cfg["agent"] = {"command": ["python3", "-c",
                        "import sys; d=sys.stdin.read(); print('AGENT-ANSWER:' + str(len(d)))"],
                        "timeout": 20}
        try:
            r = self._run("llm-chat", {"messages": [
                {"role": "system", "content": "你是测试"}, {"role": "user", "content": "继续"}]})
            out = r["result"]
            self.assertTrue(out.get("ok", True), "agent 后端应成功返回: %s" % out)
            self.assertIn("AGENT-ANSWER:", out.get("content") or "")
            self.assertEqual(out.get("tool_calls") or [], [], "外部 agent 不该回工具调用")
            self.assertEqual(out.get("backend"), "agent")
        finally:
            cfg.clear()
            cfg.update(keep)

    def test_artifacts_roundtrip_and_escape(self):
        self._run("artifacts-write", {"layer": "ticket", "project": "p1", "ticket": "T-1",
                                      "path": "docs/handoff/dev.md", "content": "改动点：x"})
        r = self._run("artifacts-read", {"layer": "ticket", "project": "p1", "ticket": "T-1",
                                         "path": "docs/handoff/dev.md"})
        self.assertIn("改动点", r["result"]["text"])
        # 读回 size 必须是实际 UTF-8 字节数，不能恒为 0
        self.assertEqual(r["result"]["size"], len("改动点：x".encode("utf-8")))
        # 越界在纯函数里拦：rel 直接给失败形状，不落到盘上
        esc = self.ctx.api.call("artifacts.rel",
                                {"base": "projects/p1/tickets/T-1", "path": "../../escape.md"})
        self.assertFalse(esc.get("ok", True))

    def test_ticket_artifact_project_follows_ticket(self):
        """ticket 层写产物：归属项目以工单记录为准，模型传错/漏填都不能错位到 projects/item。"""
        proj = self._run("projects-create", {"name": "产物归属项目"})["result"]
        pid = proj["id"]
        t = self._run("ticket-create", {"title": "归属工单", "goal": "x",
                                        "project": pid})["result"]
        # 故意传错 project：落盘仍归工单记录的项目
        self._run("artifacts-write", {"layer": "ticket", "project": "WRONG-PID",
                                      "ticket": t["id"], "path": "docs/pm/plan.md",
                                      "content": "计划正文"})
        # 漏填 project：同样归工单项目，不兜底到 projects/item
        self._run("artifacts-write", {"layer": "ticket", "ticket": t["id"],
                                      "path": "docs/pm/note.md", "content": "备注正文"})
        nid = self.ctx.api.call("store.id", {"value": t["id"]})["id"]
        paths = self._glob("agent/artifacts", "projects/**")
        self.assertTrue(any("projects/%s/tickets/%s/" % (pid, nid) in p for p in paths),
                        "产物应落在工单归属项目下: %s" % paths)
        self.assertFalse(any("projects/wrong-pid" in p for p in paths),
                         "错误 project 不得被采信: %s" % paths)
        self.assertFalse(any("/projects/item/" in p for p in paths),
                         "漏填 project 不得兜底到 projects/item: %s" % paths)

    def test_project_lifecycle(self):
        """项目：建 → 列表露出字段 → 归档 → 彻底删除（纯形状解包不能漏层）。"""
        created = self._run("projects-create", {"name": "proj-test",
                                                "default_backend": "deepseek-chat"})["result"]
        self.assertTrue(created["id"])
        self.assertEqual(created["name"], "proj-test")
        self.assertFalse(created["archived"])
        self.assertTrue(created["created"])
        self.assertEqual(created["default_backend"], "deepseek-chat")

        listed = self._run("projects-list", {})["result"]["items"]
        mine = [p for p in listed if p["id"] == created["id"]]
        self.assertEqual(len(mine), 1)

        archived = self._run("projects-archive", {"id": created["id"]})["result"]
        self.assertTrue(archived["archived"])

        gone = self._run("projects-delete", {"id": created["id"], "purge": True})["result"]
        self.assertTrue(gone["deleted"])
        after = self._run("projects-list", {})["result"]["items"]
        self.assertFalse(any(p["id"] == created["id"] for p in after))

    def test_project_purge_cascades_children(self):
        """彻底删项目：工单、PM 会话、项目产物、项目知识一并清；public 知识保留。"""
        proj = self._run("projects-create", {"name": "级联删除项目"})["result"]
        pid = proj["id"]
        t = self._run("ticket-create", {"title": "级联工单", "goal": "x",
                                         "project": pid})["result"]
        pm = t["pm"]
        self._run("artifacts-write", {"layer": "ticket", "project": pid, "ticket": t["id"],
                                      "path": "docs/pm/plan.md", "content": "计划正文"})
        self._run("knowledge-write", {"layer": "project", "project": pid, "name": "decisions",
                                      "content": "项目取舍"})
        self._run("knowledge-write", {"layer": "ticket", "ticket": t["id"], "name": "note",
                                      "content": "工单层知识"})
        self._run("knowledge-write", {"layer": "public", "name": "keep-public",
                                       "content": "全局保留"})
        # 对照项目：purge 本项目时它的工单/会话/知识必须原样保留
        proj2 = self._run("projects-create", {"name": "留存对照项目"})["result"]
        t2 = self._run("ticket-create", {"title": "对照工单", "project": proj2["id"]})["result"]
        pm2 = t2["pm"]
        self._run("knowledge-write", {"layer": "project", "project": proj2["id"],
                                      "name": "keep-other", "content": "对照项目取舍"})
        # 删前确实落了盘
        self.assertTrue(any(pm in s for s in self._glob("agent/sessions", "sessions/*.yaml")))
        self.assertTrue(any(pid in a for a in self._glob("agent/artifacts", "projects/**")))
        self.assertTrue(any(pid in k for k in self._glob("agent/knowledge", "projects/**")))

        self._run("projects-delete", {"id": pid, "purge": True})

        # 项目档与工单目录
        self.assertFalse(any(p["id"] == pid for p in
                             self._run("projects-list", {})["result"]["items"]))
        self.assertFalse(any(x["id"] == t["id"] for x in
                             self._run("ticket-list", {})["result"]["items"]))
        # 会话按被删工单集合清掉
        self.assertFalse(any(pm in s for s in self._glob("agent/sessions", "sessions/*.yaml")))
        # 项目产物 / 项目知识前缀整棵清掉
        self.assertEqual(self._glob("agent/artifacts", "projects/%s/**" % pid), [])
        self.assertEqual(self._glob("agent/knowledge", "projects/%s/**" % pid), [])
        # 工单 ticket 层知识随工单清掉（前缀 tickets/<tid>，不在项目知识树下；tid 归一为小写）
        nid = self.ctx.api.call("store.id", {"value": t["id"]})["id"]
        self.assertEqual(self._glob("agent/knowledge", "tickets/%s/**" % nid), [])
        # public 层知识不被误删
        pub = self._run("knowledge-read", {"layer": "public", "name": "keep-public"})
        self.assertIn("全局保留", pub["result"]["content"])
        # 对照项目的工单、会话、项目知识原样保留
        self.assertTrue(any(x["id"] == t2["id"] for x in
                             self._run("ticket-list", {})["result"]["items"]))
        self.assertTrue(any(pm2 in s for s in self._glob("agent/sessions", "sessions/*.yaml")))
        other = self._run("knowledge-read", {"layer": "project", "project": proj2["id"],
                                              "name": "keep-other"})
        self.assertIn("对照项目取舍", other["result"]["content"])

    def test_ticket_lifecycle_and_role_tool(self):
        proj = self._run("projects-create", {"name": "工单归属项目"})["result"]
        c = self._run("ticket-create", {"title": "冒烟任务", "goal": "验证工单流程",
                                        "project": proj["id"]})
        t = c["result"]
        self.assertTrue(t["pm"], "PM 会话未创建")
        self.assertEqual(t["status"], "queued")
        # 建单即交首轮开工：dispatch 一把钥匙指向 PM 会话，由 apply 后台派发
        run_eff = next((e for e in t["effects"] if e["kind"] == "dispatch"), None)
        self.assertIsNotNone(run_eff, "建单后未派发首轮 session-run")
        self.assertEqual(run_eff["id"], "session-run")
        self.assertEqual(run_eff["key"], t["pm"])
        self.assertEqual(run_eff["input"], {"id": t["pm"]})
        # PM 会话挂在工单上；拉一个角色会话
        rs = self._run("ticket-role-spawn", {"id": t["id"], "role": "developer",
                                             "task": "写一份 docs/handoff/developer.md"})
        self.assertTrue(rs["result"]["roles"][0]["session"].startswith("role-"))
        # 列表与回读
        lst = self._run("ticket-list", {})
        self.assertTrue(any(x["id"] == t["id"] for x in lst["result"]["items"]))
        g = self._run("ticket-get", {"id": t["id"]})
        self.assertEqual(g["result"]["status"], "queued")
        # 无子单，可直接结单
        self._run("ticket-close", {"id": t["id"], "summary": "验证完成"})
        got = self._run("ticket-get", {"id": t["id"]})
        self.assertEqual(got["result"]["status"], "closed")

    def test_ticket_close_archives_transcript_and_recycles_sessions(self):
        """结单：往来对话固化进工单 transcript，随后 PM/角色会话文件被回收。"""
        proj = self._run("projects-create", {"name": "结单回收项目"})["result"]
        c = self._run("ticket-create", {"title": "回收工单", "goal": "结单后回收会话",
                                        "project": proj["id"]})
        t = c["result"]
        pm = t["pm"]
        rs = self._run("ticket-role-spawn", {"id": t["id"], "role": "developer",
                                             "task": "写交接文档"})
        role_sid = rs["result"]["roles"][0]["session"]
        self.assertTrue(any(pm in s for s in self._glob("agent/sessions", "sessions/*.yaml")))
        closed = self._run("ticket-close", {"id": t["id"], "summary": "验收通过"})
        removed = [e["path"] for e in closed["result"]["effects"] if e["kind"] == "remove"]
        self.assertIn("sessions/%s.yaml" % pm, removed)
        self.assertIn("sessions/%s.yaml" % role_sid, removed)
        left = self._glob("agent/sessions", "sessions/*.yaml")
        self.assertFalse(any(pm in s for s in left), "PM 会话未被回收")
        self.assertFalse(any(role_sid in s for s in left), "角色会话未被回收")
        # 对话已固化：会话文件删除后，线程仍从工单 transcript 回填出往来消息
        th = self._run("ticket-thread", {"id": t["id"]})["result"]
        self.assertTrue(th["thread"]["messages"], "结单后工单未回填留档对话")

    def test_project_tree_thread_and_positions(self):
        """项目→工单分级树；工单 1:1 主会话线程；岗位带流程规范。"""
        proj = self._run("projects-create", {"name": "分级树项目"})["result"]
        c = self._run("ticket-create", {"title": "分级工单", "project": proj["id"]})["result"]
        tree = self._run("project-tree", {})["result"]
        node = next((n for n in tree["items"] if n["project"]["id"] == proj["id"]), None)
        self.assertIsNotNone(node, "分级树里找不到项目节点")
        self.assertTrue(any(x["id"] == c["id"] for x in node["tickets"]))
        th = self._run("ticket-thread", {"id": c["id"]})["result"]
        self.assertEqual(th["ticket"]["id"], c["id"])
        self.assertEqual(th["thread"]["id"], c["pm"])
        self.assertIn("roles", th)
        plist = self._run("position-list", {})["result"]
        self.assertTrue(plist["items"])
        arch = next((x for x in plist["items"] if x["id"] == "architect"), None)
        self.assertIsNotNone(arch)
        self.assertIn("flow", arch)
        pget = self._run("position-get", {"id": "architect"})["result"]
        self.assertEqual(pget["id"], "architect")
        self.assertTrue(pget["prompt_file"])
        self.assertTrue(pget["prompt"].strip(), "岗位详情应透出提示词正文")
        arch_check = (pget["flow"]["checks"] or [])[0]
        self.assertTrue(arch_check["desc"], "检查规则应带可读说明")
        self.assertIn("任一", arch_check["desc"])
        # PM 作为主会话只读条目进库，不可派单；单条详情同样可取
        pm = next((x for x in plist["items"] if x["id"] == "pm"), None)
        self.assertIsNotNone(pm, "岗位库缺只读 PM 条目")
        self.assertTrue(pm["readonly"])
        self.assertTrue(pm["system"])
        pmget = self._run("position-get", {"id": "pm"})["result"]
        self.assertEqual(pmget["id"], "pm")
        self.assertTrue(pmget["readonly"])
        self.assertTrue(pmget["prompt"].strip(), "PM 详情应透出 sessions 侧提示词正文")

    def test_ticket_requires_existing_project(self):
        """工单必须绑定存在的项目：缺项目 / 项目不存在都被拦下。"""
        miss = self._run("ticket-create", {"title": "无项目工单"})["result"]
        self.assertEqual(miss["code"], "missing_project")
        ghost = self._run("ticket-create", {"title": "幽灵项目工单",
                                            "project": "no-such-proj"})["result"]
        self.assertEqual(ghost["code"], "not_found")

    def test_stall_audit_ticket_skips_pm_and_dispatch(self):
        """停滞审计单不拉 PM，也不派发首轮开工。"""
        proj = self._run("projects-create", {"name": "审计归属项目"})["result"]
        audit = self._run("ticket-create", {"title": "停滞审计", "project": proj["id"],
                                            "kind": "stall-audit"})["result"]
        self.assertEqual(audit["pm"], "")
        self.assertNotIn("dispatch", [e["kind"] for e in audit["effects"]])

    def test_session_spawn_send_run_wait(self):
        sp = self._run("session-spawn", {"kind": "role", "role": "developer",
                                          "name": "dev", "ticket": "T-1"})
        sid = sp["result"]["id"]
        self.assertEqual(sp["result"]["status"], "idle")
        # 角色人设必须进 system 消息（嵌套需求结果要解到 .result.prompt）
        sysmsg = next(m for m in sp["result"]["messages"] if m["role"] == "system")
        self.assertIn("开发角色", sysmsg["content"])
        # 岗位红线/必做进系统提示词；工具清单按岗位名单裁剪落会话 meta
        self.assertIn("必须做到", sysmsg["content"])
        self.assertIn("禁止事项", sysmsg["content"])
        names = {t["name"] for t in sp["result"].get("meta", {}).get("tools") or []}
        self.assertIn("artifact_read", names)
        self.assertNotIn("role_spawn", names)
        self._run("session-send", {"id": sid, "text": "开始"})
        self._run("session-run", {"id": sid})
        done = self._run("session-wait", {"id": sid})["result"]
        self.assertEqual(done["status"], "idle")
        self.assertIn("测试", done["content"])

    def test_ops_overview_logs_and_library(self):
        o = self._run("ops-overview")["result"]
        self.assertIn("sessions", o)
        logs = self._run("ops-logs")["result"]
        self.assertIn("events", logs)
        lib = self._run("library-summary")["result"]
        self.assertGreaterEqual(lib["counts"]["roles"], 8)

    # ---- 调用面与 HTTP 通道 ----

    def test_module_caller_is_forbidden(self):
        """能力只对需求开放：模块自己伸手会被注册表拦（旧跨模块矩阵已收敛成这道闸）。"""
        with self.assertRaises(Exception) as cm:
            self.ctx.api.call("tickets.view", {"rec": {}}, caller="sessions")
        self.assertIn("能力只能由需求调用", str(cm.exception))

    def test_demand_caller_allowed(self):
        r = self.ctx.api.call("tickets.view", {"rec": {}}, caller="demand_engine")
        self.assertIsInstance(r, dict)

    def test_sse_gate_rejects_non_stream_and_unknown(self):
        """SSE 入口：未知路由 404；已注册但非流式 400。流式路由仅 channel.watch。"""
        def _open(path):
            req = urllib.request.Request("http://127.0.0.1:%d%s" % (self.port, path),
                                         headers={"X-Auth-Token": "t"})
            return urllib.request.urlopen(req, timeout=5)

        with self.assertRaises(urllib.error.HTTPError) as cm:
            _open("/api/sse/nope/route").read()
        self.assertEqual(cm.exception.code, 404)

        with self.assertRaises(urllib.error.HTTPError) as cm:
            _open("/api/sse/clock/now").read()
        self.assertEqual(cm.exception.code, 400, "非流式路由必须被 SSE 入口拒绝")

    def test_health_and_http(self):
        h = self._run("health-self")["result"]
        self.assertTrue(h["ok"])
        self.assertGreaterEqual(len(h["modules"]), 19)
        req = urllib.request.Request(
            "http://127.0.0.1:%d/api/rpc/demand_engine/run" % self.port,
            data=yaml.safe_dump({"id": "health-self"}, allow_unicode=True, sort_keys=False, default_flow_style=True).strip().encode("utf-8"), method="POST",
            headers={"X-Auth-Token": "t", "Content-Type": "application/yaml"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            body = yaml.safe_load(resp.read().decode("utf-8"))
        self.assertTrue(body["ok"])
        self.assertGreaterEqual(len(body["result"]["result"]["modules"]), 19)
        # 无 token 必须 401
        bad = urllib.request.Request("http://127.0.0.1:%d/api/rpc/clock/now" % self.port)
        with self.assertRaises(urllib.error.HTTPError):
            urllib.request.urlopen(bad, timeout=5)

    def test_health_live_public_and_assemble_gated(self):
        """存活探头免鉴权且 uptime 非负；业务概览自检无令牌必须 401。"""
        live = urllib.request.Request(
            "http://127.0.0.1:%d/api/health/live" % self.port)
        with urllib.request.urlopen(live, timeout=5) as resp:
            body = yaml.safe_load(resp.read().decode("utf-8"))
        self.assertTrue(body["ok"])
        self.assertGreaterEqual(body["uptime"], 0)

        assemble = urllib.request.Request(
            "http://127.0.0.1:%d/api/health/assemble" % self.port)
        with self.assertRaises(urllib.error.HTTPError) as cm:
            urllib.request.urlopen(assemble, timeout=5)
        self.assertEqual(cm.exception.code, 401)

    def test_rpc_endpoint_returns_raw_result(self):
        """网络通道的服务端：/api/rpc/ 返回未包装的原始结果，供另一个进程直接消费。"""
        req = urllib.request.Request(
            "http://127.0.0.1:%d/api/rpc/clock/now" % self.port, method="POST",
            headers={"X-Auth-Token": "t", "Content-Type": "application/yaml"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            rec = yaml.safe_load(resp.read().decode("utf-8"))
        self.assertTrue(rec["ok"])
        self.assertIn("ts", rec["result"])

    # ---- 鉴权（登录 / 会话 / 旧令牌兼容） ----

    def test_auth_pure_functions(self):
        self.assertTrue(auth_pure.credentials_ok(
            {"username": "admin", "expect_username": "admin",
             "digest": "h", "expect_hash": "h"})["ok"])
        self.assertFalse(auth_pure.credentials_ok(
            {"username": "admin", "expect_username": "root",
             "digest": "h", "expect_hash": "h"})["ok"])
        self.assertFalse(auth_pure.credentials_ok(
            {"username": "admin", "expect_username": "admin",
             "digest": "x", "expect_hash": "h"})["ok"])
        rec = auth_pure.build_session({"token": "tok", "username": "admin",
                                       "issued": 1000.0, "ttl": 60})
        self.assertEqual(rec["expires"], 1060.0)
        self.assertTrue(auth_pure.session_valid({"record": rec, "now": 1030.0})["valid"])
        expired = auth_pure.session_valid({"record": rec, "now": 2000.0})
        self.assertFalse(expired["valid"])
        self.assertTrue(expired["expired"])
        self.assertEqual(auth_pure.session_view({"record": rec}),
                         {"token": "tok", "username": "admin", "expires": 1060.0})

    def test_position_pure_functions(self):
        # 评审三态：无缺口达标；有缺口未超限回催并计数；到上限不再催
        self.assertEqual(lib_pure.reviewp({"missing": [], "retries": 0})["verdict"], "pass")
        gap = [{"path": "docs/a.md"}]
        rep = lib_pure.reviewp({"missing": gap, "retries": 0})
        self.assertEqual(rep["verdict"], "repush")
        self.assertEqual(rep["retries"], 1)
        self.assertIn("docs/a.md", rep["missing_text"])
        exh = lib_pure.reviewp({"missing": gap, "retries": 2, "max_retries": 2})
        self.assertEqual(exh["verdict"], "exhausted")
        self.assertEqual(exh["retries"], 2)
        # 提示词拼装：正文 + 必做 + 红线分段
        block = lib_pure.prompt_blocks({"text": "正文", "must_dos": ["做 A"], "forbidden": ["禁 B"]})
        self.assertIn("正文", block["system"])
        self.assertIn("必须做到", block["system"])
        self.assertIn("做 A", block["system"])
        self.assertIn("禁止事项", block["system"])
        self.assertIn("禁 B", block["system"])
        # 交付件条目 → 路径清单
        self.assertEqual(ticket_pure.paths(
            {"items": [{"path": "x/a.py"}, {"nopath": 1}]})["paths"], ["x/a.py"])
        # 工单 touch：只刷新最后活动时间，不动状态与历史
        touched = ticket_pure.touch({"rec": {"id": "T-1", "status": "queued",
                                             "history": [{"at": 1, "event": "note"}]}, "now": 999})
        self.assertEqual(touched["updated"], 999)
        self.assertEqual(touched["status"], "queued")
        self.assertEqual(len(touched["history"]), 1)
        # 闭环注入消息：role 仍为 user（喂模型），打 note 标记供前端归系统条
        note_rec = sess_run.appendmsg({"rec": {"id": "s-1", "messages": [], "status": "idle"},
                                       "text": "回催", "kind": "note", "now": 5})
        note_msg = note_rec["messages"][0]
        self.assertEqual(note_msg["role"], "user")
        self.assertEqual(note_msg["kind"], "note")
        # 结单留档：system 人设不进 transcript，往来对话按会话固化
        arch = ticket_pure.archive_transcript({
            "rec": {"id": "T-1"},
            "pm": {"session": "pm-1", "messages": [
                {"role": "system", "content": "人设大段"},
                {"role": "user", "content": "开工"},
                {"role": "assistant", "content": "计划已出"}]},
            "roles": [{"session": "role-1", "role": "developer",
                       "messages": [{"role": "system", "content": "角色人设"},
                                    {"role": "assistant", "content": "交付完成"}]}]})
        pm_msgs = arch["transcript"]["pm"]["messages"]
        self.assertFalse(any(m["role"] == "system" for m in pm_msgs))
        self.assertEqual([m["content"] for m in pm_msgs], ["开工", "计划已出"])
        role_msgs = arch["transcript"]["roles"][0]["messages"]
        self.assertEqual([m["content"] for m in role_msgs], ["交付完成"])

    def test_flow_plan_effects(self):
        rec = {"id": "role-1", "kind": "role", "role": "developer",
               "ticket": "T-1", "meta": {}}
        gap = [{"path": "docs/a.md"}]
        repush = sess_run.flow_plan({
            "rec": rec, "review": {"verdict": "repush", "missing": gap, "retries": 1},
            "ticket": "T-1", "repush_text": "补缺口", "retrospect_text": "", "exhausted_text": ""})
        kinds = [e["kind"] for e in repush["effects"]]
        self.assertIn("write", kinds)
        self.assertIn("dispatch", kinds)
        self.assertEqual(repush["rec"]["meta"]["retries"], 1)
        passed = sess_run.flow_plan({
            "rec": rec, "review": {"verdict": "pass", "missing": [], "retries": 1},
            "ticket": "T-1", "repush_text": "", "retrospect_text": "复盘", "exhausted_text": "",
            "retrospect_enabled": True})
        self.assertIn("dispatch", [e["kind"] for e in passed["effects"]])
        self.assertTrue(passed["rec"]["meta"]["retrospected"])
        # 已复盘过一轮：不再重复触发复盘，避免闭环空转
        again = sess_run.flow_plan({
            "rec": passed["rec"], "review": {"verdict": "pass", "missing": [], "retries": 1},
            "ticket": "T-1", "repush_text": "", "retrospect_text": "复盘", "exhausted_text": "",
            "retrospect_enabled": True})
        self.assertNotIn("dispatch", [e["kind"] for e in again["effects"]])
        # 复盘开关关闭：达标也不注入复盘提示、不再驱动复盘轮，只落盘
        off = sess_run.flow_plan({
            "rec": rec, "review": {"verdict": "pass", "missing": [], "retries": 1},
            "ticket": "T-1", "repush_text": "", "retrospect_text": "复盘", "exhausted_text": "",
            "retrospect_enabled": False})
        self.assertNotIn("dispatch", [e["kind"] for e in off["effects"]])
        self.assertFalse(off["rec"]["meta"].get("retrospected"))
        # 工单未显式设置时回退全局默认；默认关闭同样不复盘
        default_off = sess_run.flow_plan({
            "rec": rec, "review": {"verdict": "pass", "missing": [], "retries": 1},
            "ticket": "T-1", "repush_text": "", "retrospect_text": "复盘", "exhausted_text": "",
            "retrospect_default": False})
        self.assertNotIn("dispatch", [e["kind"] for e in default_off["effects"]])
        exhausted = sess_run.flow_plan({
            "rec": rec, "review": {"verdict": "exhausted", "missing": gap, "retries": 2},
            "ticket": "T-1", "repush_text": "", "retrospect_text": "", "exhausted_text": "卡点"})
        kinds = [e["kind"] for e in exhausted["effects"]]
        self.assertIn("demand", kinds)
        self.assertNotIn("dispatch", kinds)
        # 会话标识缺失：不写盘、不再驱动，避免落出 sessions/None.yaml 孤儿
        orphan = sess_run.flow_plan({
            "rec": {"id": "", "meta": {}}, "review": {"verdict": "pass"},
            "ticket": "T-1", "repush_text": "", "retrospect_text": "复盘", "exhausted_text": ""})
        self.assertEqual(orphan["effects"], [])

    def test_flow_plan_awaiting_user_skips_review_loop(self):
        """仅读知识后向用户提问、无产物/编排动作：判等待用户，只落盘不回催不复盘。"""
        waiting_msgs = [
            {"role": "system", "content": "人设"},
            {"role": "user", "content": "开工"},
            {"role": "assistant", "tool_calls": [{"function": {"name": "knowledge_search"}}],
             "content": "先查知识"},
            {"role": "tool", "name": "knowledge_search", "content": '{"items": []}'},
            {"role": "assistant", "content": "需求信息不足，请补充被测对象与验收标准。"},
        ]
        rec = {"id": "pm-1", "kind": "pm", "role": "", "ticket": "T-1",
               "meta": {}, "messages": waiting_msgs}
        plan = sess_run.flow_plan({
            "rec": rec, "review": {"verdict": "pass", "missing": [], "retries": 0},
            "ticket": "T-1", "repush_text": "", "retrospect_text": "复盘", "exhausted_text": ""})
        self.assertEqual(plan["verdict"], "waiting")
        kinds = [e["kind"] for e in plan["effects"]]
        self.assertEqual(kinds, ["write"])
        self.assertNotIn("dispatch", kinds)
        self.assertFalse(plan["rec"]["meta"].get("retrospected"))

    def test_flow_plan_delivered_round_not_waiting(self):
        """本轮有写产物工具调用：不算等待，正常进入评审闭环。"""
        done_msgs = [
            {"role": "system", "content": "人设"},
            {"role": "user", "content": "开工"},
            {"role": "assistant", "tool_calls": [{"function": {"name": "artifact_write"}}],
             "content": "写计划"},
            {"role": "tool", "name": "artifact_write", "content": '{"written": true}'},
            {"role": "assistant", "content": "计划已落盘。"},
        ]
        rec = {"id": "pm-1", "kind": "pm", "role": "", "ticket": "T-1",
               "meta": {}, "messages": done_msgs}
        plan = sess_run.flow_plan({
            "rec": rec, "review": {"verdict": "pass", "missing": [], "retries": 0},
            "ticket": "T-1", "repush_text": "", "retrospect_text": "复盘", "exhausted_text": "",
            "retrospect_enabled": True})
        self.assertNotEqual(plan["verdict"], "waiting")
        self.assertIn("dispatch", [e["kind"] for e in plan["effects"]])

    def test_react_schema_normalizes_list_to_array(self):
        """内部 list 类型要归一为模型侧 JSON Schema 的 array，并带 items。"""
        sch = react_pure.schema({"name": "ticket_split", "desc": "拆单",
                                 "tool": [{"name": "children", "type": "list",
                                           "desc": "子任务清单", "required": True},
                                          {"name": "force", "type": "boolean",
                                           "desc": "强制", "required": False}]})
        props = sch["function"]["parameters"]["properties"]
        self.assertEqual(props["children"]["type"], "array")
        self.assertEqual(props["children"]["items"], {"type": "object"})
        self.assertEqual(props["force"]["type"], "boolean")
        self.assertEqual(sch["function"]["parameters"]["required"], ["children"])

    def test_react_result_carries_failure(self):
        """后端未答复的原因要随结果透出，不能在循环里丢掉。"""
        res = react_pure.result({"messages": [{"role": "user", "content": "x"}],
                                  "steps": 0, "cancelled": False,
                                  "failed": {"code": "net_error", "error": "连不上"}})
        self.assertEqual(res["failed"]["code"], "net_error")
        self.assertFalse(res["cancelled"])

    def test_finish_records_and_clears_last_error(self):
        """失败原因落进会话 meta；下一轮成功后清除上一次的错误痕迹。"""
        rec = {"id": "pm-1", "meta": {}}
        failed_out = {"messages": [], "steps": 0, "last": None, "cancelled": False,
                      "failed": {"code": "llm_error", "error": "余额不足"}}
        done = sess_run.finish({"rec": rec, "out": failed_out, "latest": {}, "now": 1})
        self.assertEqual(done["meta"]["last_error"]["error"], "余额不足")
        self.assertTrue(done["result"].get("failed"))
        ok_out = {"messages": [{"role": "assistant", "content": "好"}], "steps": 1,
                  "last": {"content": "好"}, "cancelled": False, "failed": None}
        cleared = sess_run.finish({"rec": done, "out": ok_out, "latest": {}, "now": 2})
        self.assertNotIn("last_error", cleared["meta"])

    def test_thread_exposes_session_backend_and_meta(self):
        """线程视图要露出主会话后端与 meta，界面才能判断 PM 走哪条链路、有无卡点。"""
        thread = {"id": "pm-2", "name": "pm", "status": "idle", "backend": "api",
                  "role": "", "updated": 1, "meta": {"tools": []}, "messages": []}
        out = ticket_pure.threadp({"ticket": {"id": "T-1", "roles": []}, "thread": thread})
        self.assertEqual(out["thread"]["backend"], "api")
        self.assertEqual(out["thread"]["meta"], {"tools": []})

    def test_auth_verify_legacy_token(self):
        """夹具配了旧令牌 t：命中放行，空/错令牌拒绝。"""
        self.assertTrue(self.ctx.api.call("auth.verify", {"token": "t"})["allow"])
        self.assertFalse(self.ctx.api.call("auth.verify", {"token": "nope"})["allow"])
        self.assertFalse(self.ctx.api.call("auth.verify", {"token": ""})["allow"])

    def test_auth_status_is_public(self):
        """状态路由不鉴权：登录页要先问当前是否需要登录。"""
        req = urllib.request.Request("http://127.0.0.1:%d/api/auth/status" % self.port)
        with urllib.request.urlopen(req, timeout=5) as resp:
            body = yaml.safe_load(resp.read().decode("utf-8"))
        self.assertTrue(body["ok"])
        self.assertTrue(body["legacy"])

    def test_auth_login_demand_is_public(self):
        """登录需求本身必须先可达：不带令牌也能过闸（凭据由需求内部判，失败返 401）。"""
        req = urllib.request.Request(
            "http://127.0.0.1:%d/api/rpc/demand_engine/run" % self.port,
            data=yaml.safe_dump({"id": "auth-login", "input": {"username": "a", "password": "b"}}, allow_unicode=True, sort_keys=False, default_flow_style=True).strip().encode("utf-8"),
            method="POST", headers={"Content-Type": "application/yaml"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            body = yaml.safe_load(resp.read().decode("utf-8"))
        self.assertEqual(resp.status, 200)
        self.assertTrue(body["ok"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
