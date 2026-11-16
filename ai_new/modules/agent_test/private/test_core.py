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
                  "channel", "net", "host", "codec", "clock", "auth", "runtime", "exec"}
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

    def test_knowledge_roundtrip(self):
        self._run("knowledge-write", {"layer": "public", "name": "arch-note",
                                      "content": "架构约定：模块只能通过 api 调用。"})
        r = self._run("knowledge-read", {"layer": "public", "name": "arch-note"})
        self.assertIn("架构约定", r["result"]["content"])
        # public 层没有就是没有：读不到回 not_found，不抛异常
        miss = self._run("knowledge-read", {"layer": "public", "name": "secretary"})
        self.assertFalse(miss["result"].get("ok", True))

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
        # 越界在纯函数里拦：rel 直接给失败形状，不落到盘上
        esc = self.ctx.api.call("artifacts.rel",
                                {"base": "projects/p1/tickets/T-1", "path": "../../escape.md"})
        self.assertFalse(esc.get("ok", True))

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

    def test_ticket_lifecycle_and_role_tool(self):
        proj = self._run("projects-create", {"name": "工单归属项目"})["result"]
        c = self._run("ticket-create", {"title": "冒烟任务", "goal": "验证工单流程",
                                        "project": proj["id"]})
        t = c["result"]
        self.assertTrue(t["pm"], "PM 会话未创建")
        self.assertEqual(t["status"], "queued")
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

    def test_ticket_requires_existing_project(self):
        """工单必须绑定存在的项目：缺项目 / 项目不存在都被拦下。"""
        miss = self._run("ticket-create", {"title": "无项目工单"})["result"]
        self.assertEqual(miss["code"], "missing_project")
        ghost = self._run("ticket-create", {"title": "幽灵项目工单",
                                            "project": "no-such-proj"})["result"]
        self.assertEqual(ghost["code"], "not_found")

    def test_session_spawn_send_run_wait(self):
        sp = self._run("session-spawn", {"kind": "role", "role": "developer",
                                          "name": "dev", "ticket": "T-1"})
        sid = sp["result"]["id"]
        self.assertEqual(sp["result"]["status"], "idle")
        # 角色人设必须进 system 消息（嵌套需求结果要解到 .result.prompt）
        sysmsg = next(m for m in sp["result"]["messages"] if m["role"] == "system")
        self.assertIn("开发角色", sysmsg["content"])
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
