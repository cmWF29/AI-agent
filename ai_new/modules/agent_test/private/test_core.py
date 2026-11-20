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
from ai_new.modules.agent.decompose.private import _pure as decompose_pure  # noqa: E402
from ai_new.modules.agent.sessions.private import _run_pure as sess_run  # noqa: E402
from ai_new.modules.agent.sessions.private import _pure as sess_pure  # noqa: E402
from ai_new.modules.agent.tickets.private import _pure as ticket_pure  # noqa: E402
from ai_new.modules.agent.projects.private import _pure as projects_pure  # noqa: E402
from ai_new.modules.agent_common.react.private import _pure as react_pure  # noqa: E402
from ai_new.modules.agent_common.tools.private import _pure as tools_pure  # noqa: E402
from ai_new.modules.agent_common.host.private import _probe as host_probe  # noqa: E402
from _fixtures import stage, write_config  # noqa: E402
import _fixtures  # noqa: E402


class FakeNet:
    """测试用传输：不联网，按 OpenAI SSE 的形状回一段事件列表（编排和编解码都真跑）。"""

    def __init__(self):
        self.calls = 0

    def __call__(self, ctx, payload):
        self.calls += 1
        return {"ok": True, "status": 200, "headers": {},
                "items": [{"choices": [{"delta": {"content": "（测试）已完成。"},
                                        "finish_reason": "stop"}]}]}


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
        cls.ctx.api.substitute("net.request_stream", cls.fake_net)
        cls.server = cls.ctx.http
        cls.port = cls.server.server_address[1]

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        os.environ.pop("AI_NEW_DATA", None)
        cls.tmp.cleanup()

    # ---- 架构不变量 ----

    def test_every_registered_route_declares_contract(self):
        """消息结构是数据：注册的每条路由都要在模块 data/api.yaml 里声明收发字段。"""
        contracts = self.ctx.api._load_contracts()
        missing = sorted(name for name in self.ctx.api._routes if name not in contracts)
        self.assertEqual(missing, [], "这些路由没有消息契约（去补模块 data/api.yaml）: %s" % missing)
        dead = sorted(r for r in contracts if r not in self.ctx.api._routes)
        self.assertEqual(dead, [], "契约里写了没注册的路由（发出去了就是死名）: %s" % dead)

    def test_call_identity_is_judged_by_ledger(self):
        """调用方身份不是自报的：handler 执行期按所属模块判定；跨模块直调必须登记。"""
        from ai_new.modules.agent_common.api.private import _registry as reg
        ctx = self.ctx
        token = reg._SCOPE.set("probe")
        try:
            # 未登记：业务模块越界直调，enforce 下拒绝
            with self.assertRaises(Exception) as caught:
                ctx.api.call("health.live", {}, caller=None, direct=True)
            self.assertEqual(getattr(caught.exception, "code", ""),
                             "internal_call_unregistered")
            # 登记后放行：台账是显式的，不是后门
            ctx.api._calls = {"probe": ("health",)}
            ctx.api._calls_seen = len(ctx.loaded)
            self.assertTrue(ctx.api.call("health.live", {}, caller=None, direct=True)["ok"])
        finally:
            reg._SCOPE.reset(token)
            ctx.api._calls = None
            ctx.api._calls_seen = -1
        # 平台身份（远端服务端/HTTP 闸）不受台账限制
        self.assertTrue(ctx.api.call("health.live", {}, caller="platform:test",
                                     direct=True)["ok"])

    def test_contract_enforces_required_fields(self):
        """enforce 模式下缺必填字段直接拒；warn 模式只留证据，不改变行为。"""
        route = self.ctx.api._routes["store.read"]
        handler = route["fn"]
        ctx = self.ctx
        # warn（默认）：缺字段照跑，但留证据
        ctx.api._warned.clear()
        payload = {"module": "agent", "path": "not-exist.yaml"}
        ctx.api.call("store.read", payload, caller=None, direct=True)
        self.assertEqual(ctx.api._warned, [], "这条路由不该有必填字段告警")
        # enforce：造一个缺失必填的调用，确认门禁会拒
        ctx.cfg.setdefault("api", {})["contract_mode"] = "enforce"
        try:
            with self.assertRaises(ctx.ApiError) as caught:
                ctx.api._check("store.read", {})
            self.assertEqual(getattr(caught.exception, "code", ""), "bad_payload")
        finally:
            ctx.cfg["api"]["contract_mode"] = "warn"

    def test_all_modules_loaded(self):
        expect = {"config", "store", "hooks", "demand_engine", "api", "tools", "llm", "react",
                  "knowledge", "artifacts", "library", "sessions", "projects",
                  "tickets", "health", "ops", "web", "http",
                  "channel", "net", "host", "codec", "clock", "auth", "runtime", "exec",
                  "decompose", "asr", "logs", "todos"}
        self.assertEqual(set(self.loaded), expect)

    def test_modules_have_no_log_capability(self):
        """ctx 上没有日志：记日志是运维的业务，模块只能 emit hook。"""
        self.assertFalse(hasattr(self.ctx, "log"), "ctx 不该有 log 能力")
        self.assertFalse(hasattr(self.ctx, "bus"), "ctx 不该有总线能力")
        self.assertTrue(hasattr(self.ctx, "hooks"), "ctx 应该有 hooks 能力")

    def test_api_executor_pool_capacity_is_configured(self):
        """api-loop 桥接执行器是有界池，容量由 config.runtime.api_workers 显性声明。

        并发建单在执行器线程内回投 loop 跑嵌套需求；池容量必须留足并发+嵌套余量，
        否则执行器线程被占满、嵌套协程拿不到线程形成循环等待。
        """
        import concurrent.futures
        loop = self.ctx.api._ensure_loop()
        executor = loop._default_executor
        self.assertIsInstance(executor, concurrent.futures.ThreadPoolExecutor)
        expect = self.ctx.api._cfg_int("api_workers", 32)
        self.assertEqual(executor._max_workers, expect)
        self.assertGreaterEqual(expect, 16)

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

    def _clean_hooks(self):
        """用例隔离：先 drain 消化前序残留 defer，再清空队列，避免跨用例串扰污染计数。"""
        self.ctx.hooks.drain()
        self.ctx.hooks.clear()

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
        # 出厂规范模板归文档（非交付件/系统内置），按需读，不进知识检索与注入上下文
        tmpl = self._run("artifacts-read", {"layer": "public",
                                            "path": "plan-structure.md"})["result"]
        self.assertIn("计划结构模板", tmpl["text"])
        self.assertIn("验收标准", tmpl["text"])
        # 知识检索只命中 LLM 沉淀，不卷入文档模板
        found = self._run("knowledge-search", {"query": "架构约定"})["result"]
        self.assertTrue(any("arch-note" in i["path"] for i in found["items"]))
        comp = self._run("knowledge-compose", {"prefixes": ["public/"]})["result"]
        self.assertIn("架构约定", comp["text"])
        # 清单落盘：知识条目恒 category=knowledge、source=llm、doc_kind 为空
        kidx = self.ctx.api.call("store.read", {
            "module": "agent/knowledge", "path": "index.yaml",
            "fallback": {"entries": []}})["value"]
        kentry = next(e for e in kidx["entries"] if e["path"] == "public/arch-note.md")
        self.assertEqual(kentry["category"], "knowledge")
        self.assertEqual(kentry["source"], "llm")
        self.assertEqual(kentry["layer"], "public")
        self.assertIsNone(kentry["doc_kind"])

    def test_knowledge_index_tree_groups_tickets_under_project(self):
        """知识目录树：公共平铺，项目文档与其工单文档按归属归到项目节点下。"""
        rows = [
            {"path": "public/plan-structure.md"},
            {"path": "projects/重构/pm-decisions.md"},
            {"path": "tickets/t-20261117-0004/ticket-brief.md"},
            {"path": "tickets/t-20261118-0003/pm-decisions.md"},
        ]
        tickets = [
            {"id": "T-20261117-0004", "project": "重构", "title": "登录闭环"},
            {"id": "T-20261118-0003", "project": "重构", "title": "群聊流式"},
        ]
        out = self.ctx.api.call("knowledge.index", {"rows": rows, "tickets": tickets})
        self.assertEqual(out["counts"], {"public": 1, "project": 1, "ticket": 2})
        top = {n["type"] + ":" + n.get("label", ""): n for n in out["tree"]}
        self.assertIn("public:公共", top)
        proj = top["project:重构"]
        kinds = [c["type"] for c in proj["children"]]
        self.assertEqual(kinds.count("doc"), 1)
        ticket_nodes = [c for c in proj["children"] if c["type"] == "ticket"]
        self.assertEqual(len(ticket_nodes), 2)
        for node in ticket_nodes:
            self.assertEqual(len(node["children"]), 1)
            self.assertEqual(node["children"][0]["project"], "重构")
            self.assertTrue(node["label"].startswith("T-"))
        # 工单档案缺失项目归属时，工单文档落到顶层孤儿节点，不丢条目
        orphan = self.ctx.api.call("knowledge.index", {
            "rows": [{"path": "tickets/t-orphan/note.md"}], "tickets": []})
        self.assertEqual(orphan["tree"][0]["type"], "ticket")

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
        self._clean_hooks()
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

    def test_chat_drain_async_dispatches_reply(self):
        """异步轨收尾：drain_async 经 adispatch/arun/acall 直连事件循环，回复照常落盘。"""
        import asyncio
        self._clean_hooks()
        key = "rt-chat-async"
        self._run("channel-post", {"channel": key, "role": "user", "content": "异步在吗"})
        self.assertEqual(self.ctx.hooks.pending(), 1, "应该有一个延迟派发在排队")
        loop = self.ctx.api._ensure_loop()
        asyncio.run_coroutine_threadsafe(self.ctx.hooks.drain_async(), loop).result(timeout=10)
        rows = self._run("channel-tail", {"channel": key, "limit": 10})["result"]["messages"]
        self.assertEqual(rows[-1]["role"], "assistant")
        self.assertIn("测试", rows[-1]["content"])
        self.ctx.hooks.drain()

    def test_defer_queue_persists_and_replays_after_restart(self):
        """延迟事件落盘：入队即持久化；新 Runtime 从盘回填；认领/清空后盘上摘除。"""
        from ai_new.modules.agent_common.runtime.private import _core
        rt = self.ctx.runtime
        rt.clear_hooks()
        rt.enqueue_hook("channel.posted",
            {"level": "info", "data": {"channel": "persist-ch", "role": "user"}})
        rt.enqueue_hook("sessions.finished",
            {"level": "info", "data": {"session": "persist-sess"}})
        self.assertEqual(rt.pending_hooks(), 2)
        row = self.ctx.api.call("store.read",
            {"module": "agent/logs", "path": "hook-queue.yaml", "fallback": {}})
        self.assertTrue(row.get("exists"), "队列文件应已落盘")
        items = (row.get("value") or {}).get("items") or []
        self.assertEqual([i["hook"] for i in items], ["channel.posted", "sessions.finished"])

        # 模拟进程重启：新 Runtime 从盘上残留回填待派发事件
        rebooted = _core.Runtime(self.ctx)
        self.assertEqual(rebooted.pending_hooks(), 2, "重启后应回填两条待派发事件")

        # 逐条认领：摘除并同步落盘剩余
        batch = rt.claim_hooks(1)
        self.assertEqual(len(batch), 1)
        self.assertEqual(rt.pending_hooks(), 1)
        rt.clear_hooks()
        self.assertEqual(rt.pending_hooks(), 0)
        row2 = self.ctx.api.call("store.read",
            {"module": "agent/logs", "path": "hook-queue.yaml", "fallback": {}})
        items2 = (row2.get("value") or {}).get("items") or []
        self.assertEqual(items2, [], "清空后盘上不应残留事件")


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

    def test_runtime_stream_events_pushes_on_change_and_clears(self):
        """草稿事件流：订阅后 put/clear 唤醒推快照；游标对齐后不重复推。"""
        import threading, time as _time
        key = "events-probe"
        self.ctx.runtime.stream_clear(key)
        r1 = self.ctx.runtime.stream_events(key, cursor=None, timeout=0.2)
        self.assertEqual(r1["items"][0]["text"], "")
        self.assertFalse(r1["items"][0]["running"])
        cursor = r1["cursor"]

        def writer():
            _time.sleep(0.2)
            self.ctx.runtime.stream_put(key, "你好")
        threading.Thread(target=writer, daemon=True).start()
        r2 = self.ctx.runtime.stream_events(key, cursor=cursor, timeout=3)
        self.assertTrue(r2["items"])
        self.assertEqual(r2["items"][0]["text"], "你好")
        self.assertTrue(r2["items"][0]["running"])

        r3 = self.ctx.runtime.stream_events(key, cursor=r2["cursor"], timeout=0.2)
        self.assertEqual(r3["items"], [], "游标对齐后无变化不应重复推")

        self.ctx.runtime.stream_clear(key)
        r4 = self.ctx.runtime.stream_events(key, cursor=r2["cursor"], timeout=3)
        self.assertFalse(r4["items"][0]["running"], "定稿清空后推空快照")
        meta = {r["name"]: r for r in self.ctx.api.routes()}
        self.assertTrue(meta["runtime.stream_events"]["stream"])

    def test_net_stream_pushes_draft_and_collects_frames(self):
        """SSE 流式出站：逐帧正文增量进草稿槽，事件对象汇总交 decode_sse 归一。"""
        import json
        import http.server
        import threading
        from ai_new.modules.agent_common.net.private import _client as net_client

        frames = [
            {"choices": [{"delta": {"content": "你好"}}]},
            {"choices": [{"delta": {"content": "世界"}, "finish_reason": "stop"}]},
        ]
        body = "".join("data: %s\n\n" % json.dumps(f, ensure_ascii=False) for f in frames)
        body += "data: [DONE]\n\n"

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_POST(self):
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.end_headers()
                self.wfile.write(body.encode("utf-8"))

            def log_message(self, *args):
                pass

        server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        key = "sse-probe"
        try:
            url = "http://127.0.0.1:%d/v1/chat/completions" % server.server_address[1]
            resp = net_client.request_stream(self.ctx, url=url, method="POST",
                                              headers={}, body="{}", timeout=10,
                                              stream_key=key)
            self.assertTrue(resp.get("ok"), "流式请求应成功: %s" % resp)
            self.assertEqual(len(resp.get("items") or []), 2)
            draft = self.ctx.runtime.stream_get(key)
            self.assertEqual(draft["text"], "你好世界", "逐帧正文要累积进草稿槽")
            merged = self.ctx.api.call("llm.decode_sse", {"items": resp["items"]})
            self.assertEqual(merged["content"], "你好世界")
        finally:
            server.shutdown()
            server.server_close()
            self.ctx.runtime.stream_clear(key)

    def test_net_request_decodes_chunked_body(self):
        """非流响应 chunked 编码：按块解码还原完整 JSON，不被 keep-alive 挂住。"""
        import http.server
        import threading
        from ai_new.modules.agent_common.net.private import _client as net_client

        body = '{"answer":"chunked-ok"}'.encode("utf-8")
        b1, b2 = body[:7], body[7:]

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Transfer-Encoding", "chunked")
                self.end_headers()
                self.wfile.write(("%x\r\n" % len(b1)).encode() + b1 + b"\r\n")
                self.wfile.write(("%x\r\n" % len(b2)).encode() + b2 + b"\r\n")
                self.wfile.write(b"0\r\n\r\n")

            def log_message(self, *args):
                pass

        server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            url = "http://127.0.0.1:%d/v1/chat/completions" % server.server_address[1]
            resp = net_client.request(self.ctx, url=url, method="GET", timeout=10)
            self.assertTrue(resp.get("ok"), resp)
            dec = self.ctx.api.call("codec.json_decode", {"text": resp["text"]})
            self.assertEqual(dec["value"]["answer"], "chunked-ok")
        finally:
            server.shutdown()
            server.server_close()

    def test_net_unreachable_returns_error_code(self):
        """连接不可达：非流与流都归 unreachable 失败结果，不外抛；retries=0 不拖退避。"""
        from ai_new.modules.agent_common.net.private import _client as net_client
        req = net_client.request(self.ctx, url="http://127.0.0.1:1/nope",
                                 timeout=2, retries=0)
        self.assertFalse(req["ok"])
        self.assertEqual(req["code"], "unreachable")
        stream = net_client.request_stream(self.ctx, url="http://127.0.0.1:1/nope",
                                           method="POST", body="{}", timeout=2, retries=0)
        self.assertFalse(stream["ok"])
        self.assertEqual(stream["code"], "unreachable")

    def test_net_passes_through_4xx_status(self):
        """4xx 是请求本身问题：传输成功即透传状态码，不当瞬时故障重试。"""
        import http.server
        import threading
        from ai_new.modules.agent_common.net.private import _client as net_client

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(404)
                self.send_header("Content-Length", len(b"not found"))
                self.end_headers()
                self.wfile.write(b"not found")

            def log_message(self, *args):
                pass

        server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            url = "http://127.0.0.1:%d/missing" % server.server_address[1]
            resp = net_client.request(self.ctx, url=url, method="GET", timeout=10, retries=0)
            self.assertTrue(resp["ok"])
            self.assertEqual(resp["status"], 404)
        finally:
            server.shutdown()
            server.server_close()

    def test_net_passes_through_5xx_status(self):
        """5xx 响应体正常读出：状态码透传，业务层据状态判定；读阶段异常才走重试。"""
        import http.server
        import threading
        from ai_new.modules.agent_common.net.private import _client as net_client

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(500)
                self.send_header("Content-Length", len(b"boom"))
                self.end_headers()
                self.wfile.write(b"boom")

            def log_message(self, *args):
                pass

        server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            url = "http://127.0.0.1:%d/err" % server.server_address[1]
            resp = net_client.request(self.ctx, url=url, method="GET", timeout=10, retries=0)
            self.assertTrue(resp["ok"])
            self.assertEqual(resp["status"], 500)
        finally:
            server.shutdown()
            server.server_close()

    def test_net_stream_skips_bad_frames_and_stops_on_done(self):
        """坏 JSON / 非对象帧被跳过，合法帧保留；[DONE] 提前结束读取。"""
        import json
        import http.server
        import threading
        from ai_new.modules.agent_common.net.private import _client as net_client

        body = "data: {not-json\n\n"
        body += "data: %s\n\n" % json.dumps({"choices": [{"delta": {"content": "保留"}}]},
                                              ensure_ascii=False)
        body += "data: [DONE]\n\n"

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_POST(self):
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.end_headers()
                self.wfile.write(body.encode("utf-8"))

            def log_message(self, *args):
                pass

        server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        key = "sse-bad"
        try:
            url = "http://127.0.0.1:%d/v1/chat/completions" % server.server_address[1]
            resp = net_client.request_stream(self.ctx, url=url, method="POST",
                                              headers={}, body="{}", timeout=10,
                                              stream_key=key, retries=0)
            self.assertTrue(resp["ok"], resp)
            self.assertEqual(len(resp["items"]), 1)
            self.assertEqual(self.ctx.runtime.stream_get(key)["text"], "保留")
        finally:
            server.shutdown()
            server.server_close()
            self.ctx.runtime.stream_clear(key)

    def test_net_stream_eof_keeps_received_frames(self):
        """流中途断线：已收到的帧保留返回，不当失败（草稿槽不回滚）。"""
        import json
        import http.server
        import threading
        from ai_new.modules.agent_common.net.private import _client as net_client

        body = "data: %s\n\n" % json.dumps({"choices": [{"delta": {"content": "半条"}}]},
                                            ensure_ascii=False)

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_POST(self):
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.end_headers()
                self.wfile.write(body.encode("utf-8"))
                # 不发 [DONE]，返回即关连接，模拟上游断线

            def log_message(self, *args):
                pass

        server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        key = "sse-eof"
        try:
            url = "http://127.0.0.1:%d/v1/chat/completions" % server.server_address[1]
            resp = net_client.request_stream(self.ctx, url=url, method="POST",
                                              headers={}, body="{}", timeout=10,
                                              stream_key=key, retries=0)
            self.assertTrue(resp["ok"], resp)
            self.assertEqual(len(resp["items"]), 1)
            self.assertEqual(self.ctx.runtime.stream_get(key)["text"], "半条")
        finally:
            server.shutdown()
            server.server_close()
            self.ctx.runtime.stream_clear(key)

    def test_net_stream_read_timeout_returns_error(self):
        """连接建立后上游不吐帧：读帧超时归 unreachable，流已连上不重试。"""
        import time
        import http.server
        import threading
        from ai_new.modules.agent_common.net.private import _client as net_client

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_POST(self):
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.end_headers()
                time.sleep(3)  # 保持连接但不发任何帧

            def log_message(self, *args):
                pass

        server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            url = "http://127.0.0.1:%d/v1/chat/completions" % server.server_address[1]
            resp = net_client.request_stream(self.ctx, url=url, method="POST",
                                              headers={}, body="{}", timeout=1,
                                              retries=0)
            self.assertFalse(resp["ok"])
            self.assertEqual(resp["code"], "unreachable")
        finally:
            server.shutdown()
            server.server_close()


        """purge 硬删会话前：stop 置打断位、等后台任务收尾，再从运行表摘除，定稿不会写回。"""
        import concurrent.futures, time as _time
        box = {"done": False}
        def work():
            _time.sleep(0.05)
            box["done"] = True
        fut = concurrent.futures.ThreadPoolExecutor(max_workers=1).submit(work)
        self.ctx.runtime._runs["stop-probe"] = fut
        self.ctx.runtime.stop("stop-probe")
        self.assertNotIn("stop-probe", self.ctx.runtime._runs)
        self.assertNotIn("stop-probe", self.ctx.runtime._cancel)
        self.assertFalse(self.ctx.runtime.cancelled("stop-probe", 0))
        self.assertTrue(box["done"], "stop 应等任务收尾后再返回")

    def test_runtime_dispatch_clears_run_slot_after_finish(self):
        """后台任务跑完（正常/报错/被接管作废）即自清运行表，死任务条目不随工单数堆积。"""
        import time as _time
        key = "rt-cleanup-probe"
        self.ctx.runtime.dispatch({"demand": "projects-list", "key": key, "input": {}})
        deadline = _time.perf_counter() + 5
        while _time.perf_counter() < deadline:
            th = self.ctx.runtime._runs.get(key)
            if th is None or th.done():
                break
            _time.sleep(0.02)
        self.assertNotIn(key, self.ctx.runtime._runs, "跑完后运行表应自清，死任务条目不残留")
        self.assertNotIn(key, self.ctx.runtime._cancel)

    def test_artifacts_roundtrip_and_escape(self):
        self._run("artifacts-write", {"layer": "ticket", "project": "p1", "ticket": "T-1",
                                      "path": "docs/handoff/dev.md", "content": "改动点：x"})
        r = self._run("artifacts-read", {"layer": "ticket", "project": "p1", "ticket": "T-1",
                                         "path": "docs/handoff/dev.md"})
        self.assertIn("改动点", r["result"]["text"])
        # 读回 size 必须是实际 UTF-8 字节数，不能恒为 0
        self.assertEqual(r["result"]["size"], len("改动点：x".encode("utf-8")))
        # 清单落盘：文档条目恒 category=document，缺省 doc_kind=artifact、source=llm
        aidx = self.ctx.api.call("store.read", {
            "module": "agent/artifacts", "path": "index.yaml",
            "fallback": {"entries": []}})["value"]
        aentry = next(e for e in aidx["entries"] if e["path"].endswith("dev.md"))
        self.assertEqual(aentry["category"], "document")
        self.assertEqual(aentry["doc_kind"], "artifact")
        self.assertEqual(aentry["source"], "llm")
        # 越界在纯函数里拦：rel 直接给失败形状，不落到盘上
        esc = self.ctx.api.call("artifacts.rel",
                                {"base": "projects/p1/tickets/T-1", "path": "../../escape.md"})
        self.assertFalse(esc.get("ok", True))

    def test_artifacts_index_tree_groups_tickets_under_project(self):
        """文档目录树：公共平铺，项目文档与其工单文档按归属归到项目节点下。"""
        rows = [
            {"path": "public/plan-structure.md", "layer": "public",
             "doc_kind": "non_artifact", "source": "system", "name": "plan-structure.md"},
            {"path": "projects/重构/docs/notes.md", "layer": "project", "project": "重构",
             "doc_kind": "artifact", "source": "system", "name": "notes.md"},
            {"path": "projects/重构/tickets/t-20261117-0003/docs/pm/plan.md", "layer": "ticket",
             "project": "重构", "ticket": "t-20261117-0003",
             "doc_kind": "artifact", "source": "system", "name": "plan.md"},
        ]
        tickets = [{"id": "T-20261117-0003", "project": "重构", "title": "流式去重"}]
        out = self.ctx.api.call("artifacts.group", {"entries": rows, "tickets": tickets})
        self.assertEqual(out["counts"], {"public": 1, "project": 1, "ticket": 1})
        top = {n["type"] + ":" + n.get("label", ""): n for n in out["tree"]}
        self.assertIn("public:公共文档", top)
        proj = top["project:重构"]
        kinds = [c["type"] for c in proj["children"]]
        self.assertEqual(kinds.count("doc"), 1)
        ticket_nodes = [c for c in proj["children"] if c["type"] == "ticket"]
        self.assertEqual(len(ticket_nodes), 1)
        self.assertEqual(ticket_nodes[0]["children"][0]["project"], "重构")
        self.assertTrue(ticket_nodes[0]["label"].startswith("T-"))

    def test_codec_decode_hex_utf8_and_binary(self):
        """hex 解码成形：utf8 直出；非 utf8 退 base64；超阈值标 truncated。"""
        text = "计划正文"
        raw = text.encode("utf-8")
        ok = self.ctx.api.call("codec.decode_hex", {"hex": raw.hex(),
                                                    "size": len(raw), "max_bytes": 4096})
        self.assertEqual(ok["encoding"], "utf8")
        self.assertEqual(ok["text"], text)
        self.assertFalse(ok["truncated"])
        bin_raw = b"\xff\xfe\x00\x01"
        bad = self.ctx.api.call("codec.decode_hex", {"hex": bin_raw.hex(),
                                                      "size": len(bin_raw), "max_bytes": 4096})
        self.assertEqual(bad["encoding"], "binary")
        self.assertTrue(bad["needs_encode"])
        self.assertTrue(bad["text"])
        trunc = self.ctx.api.call("codec.decode_hex", {"hex": raw.hex(),
                                                       "size": len(raw), "max_bytes": 2})
        self.assertTrue(trunc["truncated"])

    def test_logs_index_tree_leaf_carries_name_and_type(self):
        """日志目录叶子：带 type=log 与 name/path，前端按叶子渲染不空卡。"""
        rows = [
            {"path": "channels/web.jsonl", "layer": "public", "kind": "channel",
             "name": "web.jsonl", "source": "system"},
            {"path": "projects/重构/tickets/t-1/tool/a.txt", "layer": "ticket",
             "project": "重构", "ticket": "t-1", "kind": "tool", "name": "a.txt"},
        ]
        tickets = [{"id": "T-1", "project": "重构", "title": "工具输出"}]
        out = self.ctx.api.call("logs.group", {"entries": rows, "tickets": tickets})
        self.assertEqual(out["counts"], {"public": 1, "project": 0, "ticket": 1})
        leaf = out["tree"][0]["children"][0]
        self.assertEqual(leaf["type"], "log")
        self.assertEqual(leaf["name"], "web.jsonl")
        self.assertEqual(leaf["path"], "channels/web.jsonl")
        proj = next(n for n in out["tree"] if n["type"] == "project")
        tnode = proj["children"][0]
        self.assertEqual(tnode["children"][0]["type"], "log")

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
        created = self._run("projects-create", {"name": "proj-test"})["result"]
        self.assertTrue(created["id"])
        self.assertEqual(created["name"], "proj-test")
        self.assertFalse(created["archived"])
        self.assertTrue(created["created"])

        pid = created["id"]
        rec = self.ctx.api.call("store.read", {"module": "agent/projects",
                                "path": pid + ".yaml"}).get("value") or {}
        ov = rec.get("overrides") or {}
        for kind in ("roles", "flows", "skills", "tools"):
            self.assertEqual(ov.get(kind) or [], [], "新项目覆盖层应默认为全启用: %s" % kind)
        for fname in ("roles.yaml", "flows.yaml", "skills.yaml", "tools.yaml"):
            snap = self.ctx.api.call("store.read", {"module": "agent/projects",
                                     "path": "projects/%s/%s" % (pid, fname)})
            self.assertIsNone(snap.get("value"), "新项目不应再物理拷贝库副本: %s" % fname)
        pos = self._run("project-positions", {"id": pid})["result"]
        self.assertGreaterEqual(len(pos["items"]), 1)

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
        self.assertTrue(any(pm in s for s in self._glob("agent/logs", "sessions/*.yaml")))
        self.assertTrue(any(pid in a for a in self._glob("agent/artifacts", "projects/**")))
        self.assertTrue(any(pid in k for k in self._glob("agent/knowledge", "projects/**")))

        self._run("projects-delete", {"id": pid, "purge": True})

        # 项目档与工单目录
        self.assertFalse(any(p["id"] == pid for p in
                             self._run("projects-list", {})["result"]["items"]))
        self.assertFalse(any(x["id"] == t["id"] for x in
                             self._run("ticket-list", {})["result"]["items"]))
        # 会话按被删工单集合清掉
        self.assertFalse(any(pm in s for s in self._glob("agent/logs", "sessions/*.yaml")))
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
        self.assertTrue(any(pm2 in s for s in self._glob("agent/logs", "sessions/*.yaml")))
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
        self.assertTrue(any(pm in s for s in self._glob("agent/logs", "sessions/*.yaml")))
        pre = self.ctx.api.call("store.read", {
            "module": "agent/logs", "path": "index.yaml",
            "fallback": {"entries": []}})["value"]["entries"]
        pre_names = {e["name"] for e in pre}
        self.assertIn(pm, pre_names, "PM 会话未登记日志清单")
        self.assertIn(role_sid, pre_names, "角色会话未登记日志清单")
        pm_entry = next(e for e in pre if e["name"] == pm)
        self.assertEqual(pm_entry["category"], "log")
        self.assertEqual(pm_entry["source"], "system")
        self.assertEqual(pm_entry["kind"], "session")
        closed = self._run("ticket-close", {"id": t["id"], "summary": "验收通过"})
        removed = [e["path"] for e in closed["result"]["effects"] if e["kind"] == "remove"]
        self.assertIn("sessions/%s.yaml" % pm, removed)
        self.assertIn("sessions/%s.yaml" % role_sid, removed)
        left = self._glob("agent/logs", "sessions/*.yaml")
        self.assertFalse(any(pm in s for s in left), "PM 会话未被回收")
        self.assertFalse(any(role_sid in s for s in left), "角色会话未被回收")
        post = self.ctx.api.call("store.read", {
            "module": "agent/logs", "path": "index.yaml",
            "fallback": {"entries": []}})["value"]["entries"]
        post_names = {e["name"] for e in post}
        self.assertNotIn(pm, post_names, "PM 会话清单条目未随回收清除")
        self.assertNotIn(role_sid, post_names, "角色会话清单条目未随回收清除")
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
        # PM 作为内置只读岗位进库，不可派单；单条详情同样可取 sessions 侧提示词正文
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
        # 流程约束独立成结构化消息：流程标识/当前态/状态全集/验收标准随消息落盘
        ctx_msg = next((m for m in sp["result"]["messages"]
                        if m.get("kind") == "flow-context"), None)
        self.assertIsNotNone(ctx_msg, "应落独立流程约束消息")
        c = ctx_msg["constraint"]
        self.assertEqual(c["flow"]["id"], "developer")
        self.assertIn("understand", c["active"])
        self.assertEqual([s["id"] for s in c["states"]],
                         ["understand", "implement", "verify"])
        self.assertTrue(c["checks"])
        self.assertEqual(sp["result"]["meta"]["flow"]["id"], "developer")
        self._run("session-send", {"id": sid, "text": "开始"})
        # 收口步桩返回严格 JSON：reply 进气泡，summary 拆出存滚动摘要
        import json as _json
        def stub_json(ctx, payload):
            return {"ok": True, "status": 200, "headers": {},
                    "items": [{"choices": [{"delta": {"content": _json.dumps(
                        {"reply": "（测试）已完成。", "summary": "本轮结论：验证通过"},
                         ensure_ascii=False)}, "finish_reason": "stop"}]}]}
        self.ctx.api.substitute("net.request_stream", stub_json)
        try:
            self._run("session-run", {"id": sid})
            done = self._run("session-wait", {"id": sid})["result"]
            self.assertEqual(done["status"], "idle")
            self.assertIn("测试", done["content"])
            # 一轮收口后滚动摘要已回填；原始往返仍全量存档
            rec = self.ctx.api.call("store.read", {"module": "agent/logs",
                                    "path": "sessions/%s.yaml" % sid}).get("value") or {}
            self.assertEqual(rec.get("summary"), "本轮结论：验证通过")
            self.assertTrue(any(m["role"] == "assistant" for m in rec.get("messages") or []))
            # 存档气泡只存 reply，不夹带摘要 JSON
            self.assertNotIn("summary", done["content"])
        finally:
            self.ctx.api.substitute("net.request_stream", self.fake_net)

    def test_spawn_reuses_active_same_role_no_duplicate(self):
        """重复触发同岗：已有在途会话时复用，不并出第二条同岗线。"""
        sp1 = self._run("session-spawn", {"kind": "role", "role": "developer",
                                          "name": "dev", "ticket": "T-IDEM"})["result"]
        sid1 = sp1["id"]
        # 模拟后台已接手：置在途并回写落盘
        path = "sessions/%s.yaml" % sid1
        rec = self.ctx.api.call("store.read", {"module": "agent/logs",
                                               "path": path}).get("value") or {}
        rec = self.ctx.api.call("sessions.mark", {"rec": rec, "status": "running"})
        self.ctx.api.call("store.write", {"module": "agent/logs", "path": path, "value": rec})
        # 第二次同工单同岗触发：复用已有在途会话，不新建
        sp2 = self._run("session-spawn", {"kind": "role", "role": "developer",
                                          "name": "dev", "ticket": "T-IDEM"})["result"]
        self.assertEqual(sp2["id"], sid1, "在途同岗会话应被复用，不新建")
        self.assertTrue(sp2.get("reused"), "复用分支应带 reused 标记")
        # 落盘上该工单的 developer 会话仍只有一条
        rows = [self.ctx.api.call("store.read", {"module": "agent/logs", "path": p}).get("value") or {}
                for p in self._glob("agent/logs", "sessions/*.yaml")]
        dev = [r for r in rows if r.get("ticket") == "T-IDEM" and r.get("role") == "developer"]
        self.assertEqual(len(dev), 1)
        self.ctx.api.call("store.remove", {"module": "agent/logs",
                                           "path": "sessions/%s.yaml" % sid1})

    def test_react_stash_tool_output_branches(self):
        """T1 大输出分级：阈值内全文；落盘成功回日志路径；apply 失败兜底全文回填。"""
        from ai_new.modules.agent_common import react as react_mod
        stash = react_mod._stash_tool_output
        session = {"id": "s1", "ticket": "T-1", "project": "p"}
        big = "x" * 1001
        orig_record = self.ctx.api.route("logs.record")["fn"]
        orig_apply = self.ctx.runtime.apply
        try:
            # 阈值内：不碰盘，全文回填
            short = stash(self.ctx, session, "c1", "短", 1000)
            self.assertFalse(short["stashed"])
            self.assertEqual(short["content"], "短")
            # 超限 + 落盘成功：回 ticket 层日志路径与读取提示
            self.ctx.api.substitute("logs.record",
                                    lambda ctx, p: {"entry": {}, "effects": []})
            self.ctx.runtime.apply = lambda req: {"applied": [{"ok": True}]}
            ok = stash(self.ctx, session, "c1", big, 1000)
            self.assertTrue(ok["stashed"])
            self.assertIn("projects/p/tickets/T-1/tool/c1.txt", ok["content"])
            # 超限 + 有回执但 apply 任一失败：回退全文并标 write_failed
            self.ctx.api.substitute("logs.record",
                                    lambda ctx, p: {"entry": {},
                                                     "effects": [{"kind": "write"}]})
            self.ctx.runtime.apply = lambda req: {"applied": [{"ok": False, "code": "apply_error"}]}
            failed = stash(self.ctx, session, "c1", big, 1000)
            self.assertFalse(failed["stashed"])
            self.assertEqual(failed["content"], big)
            self.assertEqual(failed.get("fallback"), "write_failed")
        finally:
            self.ctx.api.substitute("logs.record", orig_record)
            self.ctx.runtime.apply = orig_apply

    def test_react_checkpoint_writes_session_record(self):
        """轮内检查点：带 path 时收口步经 runtime.apply 把会话记录写回，崩溃后存档不丢本轮增量。"""
        import json as _json
        def stub_json(ctx, payload):
            return {"ok": True, "status": 200, "headers": {},
                    "items": [{"choices": [{"delta": {"content": _json.dumps(
                        {"reply": "（测试）完成", "summary": "摘要"},
                         ensure_ascii=False)}, "finish_reason": "stop"}]}]}
        self.ctx.api.substitute("net.request_stream", stub_json)
        captured = []
        orig_apply = self.ctx.runtime.apply
        def spy(req):
            eff = (req or {}).get("effect")
            if isinstance(eff, list):
                captured.extend(eff)
            elif eff:
                captured.append(eff)
            return orig_apply(req)
        self.ctx.runtime.apply = spy
        try:
            self._run("react-run", {
                "session": {"id": "cp-1", "summary": "旧摘要"},
                "messages": [{"role": "system", "content": "人设"},
                             {"role": "user", "content": "指令"}],
                "tools": [], "path": "sessions/cp-1.yaml",
                "cancel": {"id": "cp-1", "since": 0}})
            writes = [e for e in captured if e.get("kind") == "write"
                      and e.get("module") == "agent/logs"]
            self.assertTrue(writes, "收口步应落一条会话检查点")
            ck = writes[-1]["value"]
            self.assertEqual(ck["id"], "cp-1")
            self.assertTrue(any(m["role"] == "assistant" for m in ck["messages"]))
            self.assertEqual(ck["summary"], "摘要")
        finally:
            self.ctx.runtime.apply = orig_apply
            self.ctx.api.substitute("net.request_stream", self.fake_net)

    def test_react_tool_calls_run_concurrently(self):
        """同一轮多个 tool_call 并发提交工具池：总耗时≈max(单工具) 而非 sum；回填按原序。"""
        import time as _time
        starts = []

        def slow_tool(ctx, payload):
            starts.append(_time.perf_counter())
            _time.sleep(0.15)
            return {"ok": True, "content": "done:" + str(payload.get("name"))}

        self.ctx.api.substitute("tools.execute", slow_tool)
        state = {"n": 0}

        def stub_net(ctx, payload):
            state["n"] += 1
            if state["n"] == 1:
                return {"ok": True, "status": 200, "headers": {}, "items": [{
                    "choices": [{"delta": {"tool_calls": [
                        {"index": 0, "id": "c1", "function": {"name": "t1", "arguments": "{}"}},
                        {"index": 1, "id": "c2", "function": {"name": "t2", "arguments": "{}"}}]},
                        "finish_reason": "tool_calls"}]}]}
            return {"ok": True, "status": 200, "headers": {}, "items": [{
                "choices": [{"delta": {"content": '{"reply":"完成","summary":""}',
                                      "finish_reason": "stop"}}]}]}

        self.ctx.api.substitute("net.request_stream", stub_net)
        try:
            t0 = _time.perf_counter()
            res = self._run("react-run", {
                "session": {"id": "cc-1", "summary": ""},
                "messages": [{"role": "user", "content": "并行跑两个"}],
                "tools": [], "path": "", "cancel": {"id": "cc-1", "since": 0}})
            elapsed = _time.perf_counter() - t0
            self.assertEqual(len(starts), 2, "两条工具都应被执行")
            msgs = res["result"]["messages"]
            tool_msgs = [m for m in msgs if m.get("role") == "tool"]
            self.assertEqual([m.get("tool_call_id") for m in tool_msgs],
                             ["c1", "c2"], "工具回填应保持模型给出的原顺序")
            # 串行两条 0.15 应为 ≈0.30；并发应明显低于串行阈值。
            self.assertLess(elapsed, 0.28, "两条工具应并发执行，总耗时≈max 而非 sum")
        finally:
            self.ctx.api.substitute("net.request_stream", self.fake_net)

    def test_session_resume_demand_forms_effects(self):
        """启动续跑需求：读配置/文案 → 能力分类残留 running → 成形 write+dispatch 效果清单。

        中断文案来自 sessions/messages.yaml 模板，纯函数只做分类与字段定型。
        """
        for sid in ("rs-1", "rs-2"):
            self.ctx.api.call("store.write", {"module": "agent/logs",
                "path": "sessions/%s.yaml" % sid,
                "value": {"id": sid, "kind": "role", "role": "developer",
                          "ticket": "T-1", "status": "running", "messages": [],
                          "meta": {}, "updated": 0}})
        r = self._run("session-resume", {})
        self.assertTrue(r["ok"])
        effects = r["result"]["effects"]
        writes = [e for e in effects if e.get("kind") == "write"]
        dispatches = [e for e in effects if e.get("kind") == "dispatch"]
        self.assertEqual(len(writes), 2)
        self.assertEqual(len(dispatches), 2)
        for w in writes:
            self.assertEqual(w["value"]["status"], "idle")
            self.assertEqual(w["value"]["meta"]["last_error"]["code"],
                             "interrupted_on_boot")
        self.assertEqual(writes[0]["value"]["meta"]["last_error"]["error"],
                         "进程重启前卡在运行中，已自动重新驱动")
        self.assertEqual({d["input"]["id"] for d in dispatches}, {"rs-1", "rs-2"})
        # 清理本用例写入的残留会话，避免盘上 running 状态污染后续 spawn 查重
        for sid in ("rs-1", "rs-2"):
            self.ctx.api.call("store.remove", {"module": "agent/logs",
                                               "path": "sessions/%s.yaml" % sid})

    def test_runtime_call_nested_demand_skips_loop_bridge(self):
        """能力内同步壳嵌套需求直接走同步引擎，不经 demand_engine.run async 路由回投 loop。

        经 async 路由会在执行器线程占线等嵌套协程收口，并发占满池后循环等待；
        同步轨递归在当前线程跑完即返回，断掉池线程 ↔ loop 等待环。
        """
        routed = []
        orig_call = self.ctx.api.call

        def spy(name, payload=None, caller=None):
            if name == "demand_engine.run":
                routed.append(name)
            return orig_call(name, payload, caller=caller)

        self.ctx.api.call = spy
        try:
            res = self.ctx.runtime.call("session-resume", {})
        finally:
            self.ctx.api.call = orig_call
        self.assertEqual(routed, [], "同步壳嵌套需求不应回投 loop 跑 async 需求")
        self.assertIsInstance(res, dict)

    def test_session_stuck_scan_demand_forms_effects(self):
        """自愈扫描需求：无在途任务的 running 会话被复位 idle，成形 write 效果交 apply。"""
        self.ctx.api.call("store.write", {"module": "agent/logs",
            "path": "sessions/ss-1.yaml",
            "value": {"id": "ss-1", "kind": "role", "role": "developer",
                      "ticket": "T-1", "status": "running", "messages": [],
                      "meta": {}, "updated": 0}})
        r = self._run("session-stuck-scan", {})
        self.assertTrue(r["ok"])
        writes = [e for e in r["result"]["effects"] if e.get("kind") == "write"]
        self.assertEqual(len(writes), 1)
        self.assertEqual(writes[0]["value"]["status"], "idle")
        self.assertEqual(writes[0]["value"]["meta"]["last_error"]["code"],
                         "stuck_missing_task")
        self.assertEqual(writes[0]["value"]["meta"]["last_error"]["error"],
                         "运行期扫描发现会话卡死或停滞超时，已复位等待重新驱动")
        self.ctx.api.call("store.remove", {"module": "agent/logs",
                                           "path": "sessions/ss-1.yaml"})

    def test_react_non_structured_keeps_old_summary(self):
        """T2 非结构化收口不清空滚动摘要；旧摘要跨轮保留。"""
        import json as _json
        sp = self._run("session-spawn", {"kind": "role", "role": "developer",
                                        "name": "dev2", "ticket": "T-1"})
        sid = sp["result"]["id"]
        self._run("session-send", {"id": sid, "text": "开始"})

        def stub_json(ctx, payload):
            return {"ok": True, "status": 200, "headers": {},
                    "items": [{"choices": [{"delta": {"content": _json.dumps(
                        {"reply": "第一轮", "summary": "旧摘要"},
                         ensure_ascii=False)}, "finish_reason": "stop"}]}]}

        self.ctx.api.substitute("net.request_stream", stub_json)
        self._run("session-run", {"id": sid})
        self._run("session-wait", {"id": sid})

        def stub_plain(ctx, payload):
            return {"ok": True, "status": 200, "headers": {},
                    "items": [{"choices": [{"delta": {"content": "一段普通答复，没有 JSON 壳"},
                                          "finish_reason": "stop"}]}]}

        self.ctx.api.substitute("net.request_stream", stub_plain)
        self._run("session-send", {"id": sid, "text": "再来"})
        self._run("session-run", {"id": sid})
        self._run("session-wait", {"id": sid})
        rec = self.ctx.api.call("store.read", {"module": "agent/logs",
                                "path": "sessions/%s.yaml" % sid}).get("value") or {}
        self.assertEqual(rec.get("summary"), "旧摘要")
        self.ctx.api.substitute("net.request_stream", self.fake_net)

    def test_ops_overview_logs_and_library(self):
        o = self._run("ops-overview")["result"]
        self.assertIn("sessions", o)
        logs = self._run("ops-logs")["result"]
        self.assertIn("events", logs)
        lib = self._run("library-summary")["result"]
        self.assertGreaterEqual(lib["counts"]["roles"], 8)

    # ---- 内置工具 / 外部工具边界与依赖就绪 ----

    def test_tool_library_splits_builtin_and_external(self):
        """内置清单只列代码内置；内置行字段齐全、来源标记正确。外部边界由注册表占位用例覆盖。"""
        builtin_list = self._run("tools-list")["result"]
        for row in builtin_list["items"]:
            self.assertTrue(row["builtin"], "工具库混入外部能力: %s" % row["name"])
            self.assertEqual(row["source"], "内置")
        required = {"name", "desc", "module", "params", "kinds", "deps",
                    "status", "status_text", "missing", "builtin", "source"}
        for row in builtin_list["items"]:
            self.assertTrue(required <= set(row), "工具行缺字段: %s" % (required - set(row)))
        self.assertGreaterEqual(len(builtin_list["items"]), 1)

    def test_external_tool_registers_and_runs_pending(self):
        """外部登记工具装配进注册表但不进内置清单；占位执行回 external_pending，业务参数透传、tool 键剥离。"""
        reg = self.ctx.tools
        reg.register_demand("probe_ext_img", "探测用外部生图",
                            [{"name": "prompt", "type": "string", "required": True}],
                            demand="tool-external-run", module="external", builtin=False)
        self.assertTrue(reg.has("probe_ext_img"))
        self.assertNotIn("probe_ext_img", {t["name"] for t in reg.list_tools()})
        out = self.ctx.api.call("tools.execute",
                                {"name": "probe_ext_img", "args": {"prompt": "一只猫"}})
        self.assertFalse(out.get("ok", True))
        self.assertEqual(out.get("code"), "external_pending")
        self.assertEqual(out.get("tool"), "probe_ext_img")
        self.assertEqual(out.get("args"), {"prompt": "一只猫"})

    def test_project_tool_override_toggle_pick_and_execute(self):
        """项目覆盖层禁用工具：pick 名单剔除、execute 拦截；启用后恢复占位执行。公共库定义不被改写。"""
        created = self._run("projects-create", {"name": "工具覆盖项目"})["result"]
        pid = created["id"]
        row = self.ctx.api.call("store.read", {"module": "agent_common/tools",
                                              "path": "tools.yaml"})
        tools = dict(row.get("value") or {})
        tools["ext_demo_tool"] = {"desc": "公共登记探测工具",
                                  "params": [{"name": "prompt", "type": "string"}],
                                  "module": "external", "kinds": ["role"], "deps": {}}
        self.ctx.api.call("store.write", {"module": "agent_common/tools",
                                          "path": "tools.yaml", "value": tools})

        picked = self.ctx.api.call("tools.pick", {"project": pid, "tools": [], "kind": "role"})
        self.assertIn("ext_demo_tool", {t["name"] for t in picked["items"]})

        self._run("project-override-toggle", {"project": pid, "kind": "tools",
                                              "id": "ext_demo_tool", "enabled": False})
        picked = self.ctx.api.call("tools.pick", {"project": pid, "tools": [], "kind": "role"})
        self.assertNotIn("ext_demo_tool", {t["name"] for t in picked["items"]})

        with self.assertRaises(Exception) as cm:
            self.ctx.api.call("tools.execute", {"name": "ext_demo_tool",
                                                "args": {"prompt": "x"},
                                                "session": {"project": pid}})
        self.assertEqual(cm.exception.code, "no_tool")

        self._run("project-override-toggle", {"project": pid, "kind": "tools",
                                              "id": "ext_demo_tool", "enabled": True})
        out = self.ctx.api.call("tools.execute", {"name": "ext_demo_tool",
                                                  "args": {"prompt": "x"},
                                                  "session": {"project": pid}})
        self.assertEqual(out.get("code"), "external_pending")
        self.assertEqual(out.get("tool"), "ext_demo_tool")

    def test_shell_only_on_execution_roles(self):
        """shell 按岗位名单裁剪：developer/tester 可取，只读文档岗取不到。"""
        row = self.ctx.api.call("store.read", {"module": "agent/library",
                                               "path": "roles.yaml"})
        roles = row.get("value") or {}

        def picked(role):
            rec = roles.get(role) or {}
            res = self.ctx.api.call("tools.pick",
                                    {"tools": rec.get("tools") or [], "kind": "role"})
            return {t["name"] for t in res["items"]}

        self.assertIn("shell", picked("developer"))
        self.assertIn("shell", picked("tester"))
        self.assertNotIn("shell", picked("reviewer"))
        self.assertNotIn("shell", picked("researcher"))

    def test_exec_runs_real_subprocess_and_captures_output(self):
        """异步子进程核心：起真实解释器，收 stdout/stderr 与退出码。"""
        code = "import sys; sys.stdout.write('out-ok'); sys.stderr.write('err-ok')"
        res = self.ctx.api.call("exec.run", {"argv": [sys.executable, "-c", code]})
        self.assertTrue(res["ok"], res)
        self.assertEqual(res["code"], 0)
        self.assertIn("out-ok", res["out"])
        self.assertIn("err-ok", res["err"])

    def test_exec_kills_on_timeout(self):
        """超时打断：长睡眠进程被 kill，killed=timeout。"""
        res = self.ctx.api.call(
            "exec.run",
            {"argv": [sys.executable, "-c", "import time; time.sleep(5)"], "timeout": 0.3})
        self.assertFalse(res["ok"])
        self.assertEqual(res["killed"], "timeout")
        self.assertNotEqual(res["code"], 0)

    def test_project_skills_and_tools_list(self):
        """项目技能/工具清单取数：直读公共库并按覆盖层打标记，成行字段齐全。"""
        created = self._run("projects-create", {"name": "清单项目"})["result"]
        pid = created["id"]
        skills = self._run("project-skills", {"id": pid})["result"]
        self.assertIsInstance(skills["items"], list)
        tools = self._run("project-tools", {"id": pid})["result"]
        self.assertIsInstance(tools["items"], list)
        required = {"name", "desc", "module", "params", "kinds", "deps",
                    "status", "status_text", "missing", "builtin", "source"}
        for row in tools["items"]:
            self.assertTrue(required <= set(row), "项目工具行缺字段: %s" % (required - set(row)))

    def test_install_plan_empty_deps_is_ready(self):
        """空依赖清单的安装计划直接就绪；有未在位 pip 包才进待装清单。"""
        plan = tools_pure.install_plan({"tools": [], "snapshot": {}})
        self.assertTrue(plan["ready"])
        self.assertEqual(plan["pip"], [])
        tool = {"name": "x", "deps": {"pip": ["numpy"]}}
        plan2 = tools_pure.install_plan({"tools": [tool], "snapshot": {"pip": {}}})
        self.assertFalse(plan2["ready"])
        self.assertIn("numpy", plan2["pip"])

    def test_deps_report_groups_present_and_missing(self):
        """盘点按类别聚合在位/缺失：在位项进 present，缺失项带归属工具；统计与可装标志成形。"""
        tools = [
            {"name": "a", "deps": {"pip": ["numpy"], "cli": ["ffmpeg"], "env": ["HOME"]}},
            {"name": "b", "deps": {"pip": ["nonexistent_pkg_zzz"], "config": ["db.url"]}},
        ]
        snapshot = {"pip": {"numpy": True}, "cli": {"ffmpeg": True},
                    "env": {"HOME": "/home"}, "config": {"db.url": ""}}
        rep = tools_pure.deps_report({"tools": tools, "snapshot": snapshot})
        self.assertEqual(rep["total"], 2)
        self.assertEqual(rep["ready"], 1)
        self.assertEqual(rep["missing_tools"], 1)
        self.assertIn("numpy", rep["groups"]["pip"]["present"])
        self.assertIn("ffmpeg", rep["groups"]["cli"]["present"])
        self.assertIn("HOME", rep["groups"]["env"]["present"])
        pip_missing = [m["name"] for m in rep["groups"]["pip"]["missing"]]
        cfg_missing = [m["name"] for m in rep["groups"]["config"]["missing"]]
        self.assertIn("nonexistent_pkg_zzz", pip_missing)
        self.assertIn("db.url", cfg_missing)
        self.assertTrue(rep["can_install"])
        self.assertFalse(rep["install_blocked"])
        self.assertIn("nonexistent_pkg_zzz", rep["plan"]["pip"])
        self.assertEqual(rep["pip_missing"], 1)
        self.assertEqual(rep["manual_missing"], 1)

    def test_deps_report_all_ready_blocks_install(self):
        """全部在位时盘点就绪、无可自动装项，安装按钮应被禁用。"""
        tools = [{"name": "a", "deps": {"pip": ["numpy"]}}]
        rep = tools_pure.deps_report({"tools": tools,
                                      "snapshot": {"pip": {"numpy": True}}})
        self.assertEqual(rep["total"], 1)
        self.assertEqual(rep["ready"], 1)
        self.assertEqual(rep["missing_tools"], 0)
        self.assertTrue(rep["plan"]["ready"])
        self.assertFalse(rep["can_install"])
        self.assertTrue(rep["install_blocked"])
        self.assertEqual(rep["pip_missing"], 0)
        self.assertEqual(rep["manual_missing"], 0)

    def test_tools_deps_demand_runs_report(self):
        """盘点需求闭环：取外部登记与禁用过滤 → tools.deps 成形分类盘点，只读不装包。"""
        rep = self._run("tools-deps")["result"]
        for key in ("total", "ready", "missing_tools", "can_install",
                    "install_blocked", "pip_missing", "manual_missing",
                    "plan", "groups"):
            self.assertIn(key, rep, "盘点结果缺字段: %s" % key)
        self.assertGreaterEqual(rep["total"], 1)
        for kind in ("pip", "cli", "env", "config", "resources"):
            self.assertIn(kind, rep["groups"])

    def test_pip_name_maps_to_import_name(self):
        """pip 规范名与导入名不一致时，探测按映射后的导入名走；未收录的兜底连字符转下划线。"""
        self.assertEqual(host_probe._import_name("PyMuPDF"), "fitz")
        self.assertEqual(host_probe._import_name("python-docx"), "docx")
        self.assertEqual(host_probe._import_name("beautifulsoup4"), "bs4")
        self.assertEqual(host_probe._import_name("opencv-python"), "cv2")
        self.assertEqual(host_probe._import_name("numpy"), "numpy")

    def test_assembled_demands_include_new_entries(self):
        """装配后需求清单含本轮入口（冒烟断言固化进门禁，避免下线后静默丢失）。"""
        listed = self.ctx.api.call("demand_engine.list", {})
        ids = {d.get("id") for d in listed}
        for need in ("tools-list", "tools-deps", "tools-install", "decompose-install",
                     "skills-list", "skill-disable", "skill-enable", "skill-uninstall",
                     "view-tools", "view-skills"):
            self.assertIn(need, ids, "装配后需求清单缺少: %s" % need)

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
        # library 快照是 demand_engine.run 包裹层，计数在内层 result.counts
        lib_counts = h["library"]["counts"]
        self.assertIsNotNone(lib_counts)
        self.assertIn("roles", lib_counts)
        self.assertIn("flows", lib_counts)
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
        self.assertEqual(lib_pure.reviewp({"missing": [], "retries": 0, "max_retries": 2})["verdict"], "pass")
        gap = [{"path": "docs/a.md"}]
        rep = lib_pure.reviewp({"missing": gap, "retries": 0, "max_retries": 2})
        self.assertEqual(rep["verdict"], "repush")
        self.assertEqual(rep["retries"], 1)
        self.assertIn("docs/a.md", rep["missing_text"])
        exh = lib_pure.reviewp({"missing": gap, "retries": 2, "max_retries": 2})
        self.assertEqual(exh["verdict"], "exhausted")
        self.assertEqual(exh["retries"], 2)
        # 提示词拼装：正文 + 必做 + 红线分段；段标题来自 messages.yaml
        lib_tpl = self.ctx.api.call("store.read", {
            "module": "agent/library", "path": "messages.yaml"}, caller=None).get("value") or {}
        block = lib_pure.prompt_blocks({"text": "正文", "must_dos": ["做 A"],
                                         "forbidden": ["禁 B"], "tpl": lib_tpl})
        self.assertIn("正文", block["system"])
        self.assertIn("必须做到", block["system"])
        self.assertIn("做 A", block["system"])
        self.assertIn("禁止事项", block["system"])
        self.assertIn("禁 B", block["system"])
        # 阶段段刷新：替换旧阶段段，人设正文与 user 消息保留
        seed_msgs = [{"role": "system",
                      "content": "## 通用规则\n规则\n\n## 流程阶段\n当前阶段：理解（understand）"},
                     {"role": "user", "content": "x"}]
        ref = sess_pure.refresh_stage_message(
            {"messages": seed_msgs, "stage": "## 流程阶段\n当前阶段：实现（implement）"})
        ref_sys = ref["messages"][0]["content"]
        self.assertIn("规则", ref_sys)
        self.assertIn("implement", ref_sys)
        self.assertNotIn("understand", ref_sys)
        self.assertEqual(ref["messages"][1]["content"], "x")
        # 已派角色注入：清单并入 system，重复角色去重；空清单原样返回
        inj = sess_pure.inject_assigned_message(
            {"messages": seed_msgs, "roles": [{"role": "developer"}, {"role": "developer"}],
             "heading": "## 已分派角色"})
        inj_sys = inj["messages"][0]["content"]
        self.assertIn("developer", inj_sys)
        self.assertEqual(inj_sys.count("developer"), 1)
        inj_empty = sess_pure.inject_assigned_message(
            {"messages": seed_msgs, "roles": [], "heading": "## 已分派角色"})
        self.assertEqual(inj_empty["messages"][0]["content"], seed_msgs[0]["content"])
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

    def test_stage_state_machine(self):
        stages = [
            {"id": "a", "cn": "甲", "desc": "d-a", "tools": ["t1"], "next": ["b"]},
            {"id": "b", "cn": "乙", "desc": "d-b", "tools": ["t1", "t2"], "next": ["a", "c"]},
            {"id": "c", "cn": "丙", "tools": ["t3"], "next": [], "terminal": True},
        ]
        contract = lib_pure.stage_contractp({"stages": stages})
        self.assertEqual(contract["initial"], "a")
        self.assertEqual(contract["terminals"], ["c"])
        self.assertEqual(set(contract["by_id"]), {"a", "b", "c"})
        # 契约定形：空 stages 直通空
        empty = lib_pure.stage_contractp({"stages": []})
        self.assertEqual(empty["initial"], "")
        self.assertEqual(empty["terminals"], [])
        # 跳转校验：开局进初始、合法边、原地停留、未上报直通
        self.assertTrue(lib_pure.stage_transitionp(
            {"contract": contract, "prev": "", "nxt": "a"})["ok"])
        ok = lib_pure.stage_transitionp({"contract": contract, "prev": "a", "nxt": "b"})
        self.assertTrue(ok["ok"])
        self.assertEqual(ok["stage"], "b")
        stay = lib_pure.stage_transitionp({"contract": contract, "prev": "b", "nxt": "b"})
        self.assertTrue(stay["ok"])
        unset = lib_pure.stage_transitionp({"contract": contract, "prev": "b", "nxt": ""})
        self.assertTrue(unset["ok"])
        self.assertEqual(unset["stage"], "b")
        # 非法边、未知阶段、开局未进初始都拦下并保留 prev
        bad = lib_pure.stage_transitionp({"contract": contract, "prev": "a", "nxt": "c"})
        self.assertFalse(bad["ok"])
        self.assertEqual(bad["code"], "illegal_edge")
        self.assertEqual(bad["stage"], "a")
        unknown = lib_pure.stage_transitionp({"contract": contract, "prev": "b", "nxt": "zz"})
        self.assertFalse(unknown["ok"])
        self.assertEqual(unknown["code"], "unknown_stage")
        start = lib_pure.stage_transitionp({"contract": contract, "prev": "", "nxt": "b"})
        self.assertFalse(start["ok"])
        self.assertEqual(start["code"], "illegal_start")
        # 工具裁剪：阶段 tools 与全集取交集；dict 取 name，字符串直接比
        items = [{"name": "t1"}, {"name": "t2"}, {"name": "t3"}, "t4"]
        cut = lib_pure.stage_toolsp({"contract": contract, "stage": "b", "items": items})
        self.assertEqual([t["name"] for t in cut["items"]], ["t1", "t2"])
        # 阶段未列 tools 回退全集；无契约直通全集
        full = lib_pure.stage_toolsp({"contract": contract, "stage": "c", "items": items})
        self.assertEqual([t["name"] for t in full["items"] if isinstance(t, dict)], ["t3"])
        passthrough = lib_pure.stage_toolsp({"contract": empty, "stage": "", "items": items})
        self.assertEqual(passthrough["items"], items)
        # 阶段段文本：标题/当前阶段/可跳转来自模板与数据；无契约返空
        lib_tpl = self.ctx.api.call("store.read", {
            "module": "agent/library", "path": "messages.yaml"}, caller=None).get("value") or {}
        blk = lib_pure.stage_blockp({"contract": contract, "stage": "b", "tpl": lib_tpl})["system"]
        self.assertIn("乙", blk)
        self.assertIn("b", blk)
        self.assertFalse(lib_pure.stage_blockp({"contract": empty, "stage": "", "tpl": lib_tpl})["system"])
        # 阶段缺口：非终态追加一条；终态不追加；非法跳转告警追加；无契约直通 base
        base = [{"path": "docs/a.md"}]
        g_open = lib_pure.stage_gapsp({"contract": contract, "stage": "b", "base": base, "tpl": lib_tpl})
        self.assertEqual(len(g_open["missing"]), 2)
        g_term = lib_pure.stage_gapsp({"contract": contract, "stage": "c", "base": base, "tpl": lib_tpl})
        self.assertEqual(len(g_term["missing"]), 1)
        g_alert = lib_pure.stage_gapsp({"contract": contract, "stage": "c",
                                        "stage_alert": {"code": "illegal_edge", "nxt": "zz"},
                                        "base": base, "tpl": lib_tpl})
        self.assertEqual(len(g_alert["missing"]), 2)
        g_plain = lib_pure.stage_gapsp({"contract": empty, "stage": "", "base": base, "tpl": lib_tpl})
        self.assertEqual(g_plain["missing"], base)
        # 收口解析：stage 随结构化对象拆出；非结构化回退空串
        f = react_pure.parse_final({"obj": {"reply": "答", "summary": "摘", "stage": "b"},
                                    "content": "x"})
        self.assertTrue(f["structured"])
        self.assertEqual(f["stage"], "b")
        f_plain = react_pure.parse_final({"obj": None, "content": "普通正文"})
        self.assertEqual(f_plain["stage"], "")
        # result 透出 stage
        res = react_pure.result({"messages": [], "stage": "b"})
        self.assertEqual(res["stage"], "b")
        # 嵌套子状态机：点分路径、父子/深度索引归一
        tree = [{"id": "x", "cn": "X", "next": ["x.y"], "children": [
            {"id": "y", "cn": "Y", "terminal": True}]}]
        c2 = lib_pure.stage_contractp({"states": tree})
        self.assertEqual(c2["by_id"]["x.y"]["cn"], "Y")
        self.assertEqual(c2["parents"]["x.y"], "x")
        self.assertEqual(c2["children"]["x"], ["x.y"])
        self.assertEqual(c2["depth"]["x.y"], 1)
        self.assertEqual(c2["initial"], "x")
        self.assertEqual(c2["terminals"], ["x.y"])
        # 并发活跃集合：多源可达即合法，非终态源保留并并入目标
        ok = lib_pure.stage_transitionp({"contract": contract,
                                         "active": ["a", "b"], "nxt": "c"})
        self.assertTrue(ok["ok"])
        self.assertEqual(ok["stage"], "c")
        self.assertIn("b", ok["active"])
        self.assertIn("c", ok["active"])
        # 交付件条件未达标拦截：源状态 checks 无落盘文件 → condition_unmet 保留活跃态
        cc = lib_pure.stage_contractp({"states": [
            {"id": "s1", "next": ["s2"], "checks": [
                {"kind": "glob", "paths": ["**/*.py"], "match": "any"}]},
            {"id": "s2", "terminal": True}]})
        un = lib_pure.stage_transitionp({"contract": cc, "prev": "s1",
                                         "nxt": "s2", "files": [], "contents": {}})
        self.assertFalse(un["ok"])
        self.assertEqual(un["code"], "condition_unmet")
        self.assertEqual(un["active"], ["s1"])
        # 交付件达标放行
        reached = lib_pure.stage_transitionp({"contract": cc, "prev": "s1",
                                              "nxt": "s2", "files": ["a.py"], "contents": {}})
        self.assertTrue(reached["ok"])
        # 角色顶层交付约束并入条件缺口
        cc2 = lib_pure.stage_contractp({"checks": [
            {"kind": "glob", "paths": ["**/*.md"], "match": "any"}], "states": [
            {"id": "s1", "next": ["s2"]}, {"id": "s2", "terminal": True}]})
        miss = lib_pure.stage_conditionsp({"contract": cc2, "active": ["s1"],
                                           "files": [], "contents": {}, "tpl": lib_tpl})
        self.assertEqual(len(miss["missing"]), 1)
        # 结论型检查：note 备注达标放行；无备注/仅系统事件记缺口
        cc_note = lib_pure.stage_contractp({"states": [
            {"id": "n1", "next": ["n2"], "checks": [{"kind": "note"}]},
            {"id": "n2", "terminal": True}]})
        nmiss = lib_pure.stage_transitionp({"contract": cc_note, "prev": "n1", "nxt": "n2",
                                            "files": [], "contents": {}, "notes": []})
        self.assertFalse(nmiss["ok"])
        self.assertEqual(nmiss["code"], "condition_unmet")
        hist_sys = [{"event": "pm_start", "text": "PM 会话已拉起"},
                    {"event": "role_spawn", "text": "x"}]
        nmiss2 = lib_pure.stage_transitionp({"contract": cc_note, "prev": "n1", "nxt": "n2",
                                             "files": [], "contents": {}, "notes": hist_sys})
        self.assertFalse(nmiss2["ok"])
        hist_note = hist_sys + [{"event": "note", "text": "评审通过，缺口已补齐"}]
        nok = lib_pure.stage_transitionp({"contract": cc_note, "prev": "n1", "nxt": "n2",
                                          "files": [], "contents": {}, "notes": hist_note})
        self.assertTrue(nok["ok"])
        cmiss = lib_pure.stage_conditionsp({"contract": cc_note, "active": ["n1"],
                                            "files": [], "contents": {}, "notes": [],
                                            "tpl": lib_tpl})
        self.assertEqual(len(cmiss["missing"]), 1)
        cp = lib_pure.checkp({"rec": {"checks": [{"kind": "note"}]},
                              "notes": [{"event": "note", "text": "结论"}]})
        self.assertEqual(cp["missing"], [])
        cp2 = lib_pure.checkp({"rec": {"checks": [{"kind": "note"}]}, "notes": []})
        self.assertEqual(len(cp2["missing"]), 1)
        # 旧流程 nodes/edges 归一为状态机 states：边转 next 邻接，末态标 terminal
        fs = lib_pure.flow_to_statesp({"nodes": ["n1", "n2"], "edges": [["n1", "n2"]]})
        self.assertEqual(fs["states"][0]["next"], ["n2"])
        self.assertTrue(fs["states"][1]["terminal"])
        # 多活跃状态工具取并集
        items = [{"name": "t1"}, {"name": "t2"}, {"name": "t3"}]
        cut = lib_pure.stage_toolsp({"contract": contract, "active": ["a", "b"], "items": items})
        self.assertEqual([t["name"] for t in cut["items"]], ["t1", "t2"])
        # 动态增删改：增节点、删节点及其出边、追加邻接
        ov = lib_pure.stage_apply_overridesp({"states": [
            {"id": "a", "next": ["b"]}, {"id": "b", "next": []}],
            "add": [{"id": "c", "next": []}],
            "remove": ["b"], "edges": [["a", "c"]]})
        ov_by = {s["id"]: s for s in ov["states"]}
        self.assertIn("c", ov_by)
        self.assertNotIn("b", ov_by)
        self.assertEqual(ov_by["a"]["next"], ["c"])
        # 契约写回快照：回收不在新契约的活跃态，全部失效则回退初始
        contract2 = lib_pure.stage_contractp({"states": [
            {"id": "a", "next": ["b"]}, {"id": "b", "terminal": True}]})
        applied = sess_pure.machine_applyp({"rec": {"meta": {"active": ["a", "ghost"]}},
                                            "contract": contract2})
        self.assertEqual(applied["meta"]["active"], ["a"])
        self.assertEqual(applied["meta"]["machine"]["initial"], "a")
        app2 = sess_pure.machine_applyp({"rec": {"meta": {"active": ["ghost"]}},
                                         "contract": contract2})
        self.assertEqual(app2["meta"]["active"], ["a"])

    def test_seed_flow_refs_wired(self):
        """种子岗位流程经 ref 复用公共子流程：契约展开子链全路径与终态。"""
        seed = yaml.safe_load((ROOT /
            "ai_new/modules/agent/library/data/seed.yaml").read_text(encoding="utf-8"))
        refs = lib_pure.stage_refsp({"seed": seed, "flows": {}})["refs"]
        flows = lib_pure._records({"seed": seed, "user": {}, "kind": "flows"})
        pm = lib_pure.stage_contractp({"states": flows["pm"]["states"], "refs": refs,
                                       "checks": flows["pm"].get("checks")})
        self.assertEqual(pm["initial"], "owner")
        self.assertEqual(pm["terminals"], ["owner.req.close"])
        self.assertIn("owner.req.intake", [s["path"] for s in pm["states"]])
        ops = lib_pure.stage_contractp({"states": flows["ops"]["states"], "refs": refs,
                                        "checks": flows["ops"].get("checks")})
        self.assertEqual(ops["initial"], "health")
        self.assertEqual(ops["terminals"], ["health.audit.close"])
        self.assertIn("health.ops.diagnose", [s["path"] for s in ops["states"]])
        self.assertIn("requirement-owner", refs)
        self.assertIn("ticket-health", refs)

    def test_react_context_pure_functions(self):
        # 发往视图：system 保留，历史往返剔除，摘要占位 + 本轮指令保留
        msgs = [
            {"role": "system", "content": "人设"},
            {"role": "user", "content": "历史指令一"},
            {"role": "assistant", "content": "历史答复"},
            {"role": "tool", "tool_call_id": "c1", "name": "x", "content": "历史工具结果"},
            {"role": "user", "content": "本轮指令"},
        ]
        view = react_pure.context_view({"messages": msgs, "summary": "旧摘要"})
        self.assertEqual([m["role"] for m in view["messages"]],
                         ["system", "assistant", "user"])
        self.assertEqual(view["messages"][1]["kind"], "summary")
        self.assertEqual(view["messages"][1]["content"], "旧摘要")
        self.assertEqual(view["messages"][2]["content"], "本轮指令")
        # 无摘要时不插摘要消息
        view2 = react_pure.context_view({"messages": msgs, "summary": ""})
        self.assertEqual([m["role"] for m in view2["messages"]], ["system", "user"])
        # 工具输出分级：阈值内全文，超限标记落盘
        self.assertFalse(react_pure.classify_tool(
            {"content": "短", "threshold": 1000})["large"])
        big = "x" * 1001
        cls = react_pure.classify_tool({"content": big, "threshold": 1000})
        self.assertTrue(cls["large"])
        self.assertEqual(cls["size"], 1001)
        # 收口结构化拆分：剥围栏 → 解码 → reply 进气泡，summary 存滚动摘要
        import json as _json2
        fenced = '```json\n{"reply": "已完成", "summary": "结论 A，路径 x"}\n```'
        stripped = react_pure.strip_fence({"text": fenced})
        obj = _json2.loads(stripped["text"])
        fin = react_pure.parse_final({"obj": obj, "content": fenced})
        self.assertTrue(fin["structured"])
        self.assertEqual(fin["reply"], "已完成")
        self.assertEqual(fin["summary"], "结论 A，路径 x")
        # 非结构化文本：整段作答复，摘要留空回退
        plain = react_pure.parse_final({"obj": None, "content": "就是一段普通答复"})
        self.assertFalse(plain["structured"])
        self.assertEqual(plain["reply"], "就是一段普通答复")
        self.assertEqual(plain["summary"], "")
        # 协议约定追加到首条 system，其余消息不动
        proto = react_pure.attach_protocol({
            "messages": [{"role": "system", "content": "人设"},
                         {"role": "user", "content": "开工"}],
            "protocol": "收口返回 JSON"})
        self.assertIn("收口返回 JSON", proto["messages"][0]["content"])
        self.assertEqual(proto["messages"][1]["content"], "开工")

        # T3 第二轮视图带上一轮摘要；换一轮摘要即被新值覆盖
        view3 = react_pure.context_view({"messages": [
            {"role": "system", "content": "人设"}, {"role": "user", "content": "本轮"}],
            "summary": "上一轮结论"})
        self.assertEqual([m["role"] for m in view3["messages"]], ["system", "assistant", "user"])
        self.assertEqual(view3["messages"][1]["kind"], "summary")
        self.assertEqual(view3["messages"][1]["content"], "上一轮结论")
        view3b = react_pure.context_view({"messages": [
            {"role": "system", "content": "人设"}, {"role": "user", "content": "本轮"}],
            "summary": "更新后的结论"})
        self.assertEqual(view3b["messages"][1]["content"], "更新后的结论")

        # T4 parse_final 字段定型：reply=None 置空、非字符串转文本、obj 为 list 回退、单键可解析
        f4 = react_pure.parse_final({"obj": {"reply": None, "summary": 123}, "content": "x"})
        self.assertTrue(f4["structured"])
        self.assertEqual(f4["reply"], "")
        self.assertEqual(f4["summary"], "123")
        f4list = react_pure.parse_final({"obj": ["a"], "content": "普通正文"})
        self.assertFalse(f4list["structured"])
        self.assertEqual(f4list["reply"], "普通正文")
        self.assertEqual(f4list["summary"], "")
        f4one = react_pure.parse_final({"obj": {"reply": "只答复"}, "content": "x"})
        self.assertTrue(f4one["structured"])
        self.assertEqual(f4one["reply"], "只答复")
        self.assertEqual(f4one["summary"], "")

        # T5 strip_fence：无围栏原样、单行围栏、缺尾围栏；纯文本不动
        self.assertEqual(react_pure.strip_fence({"text": "裸文本"})["text"], "裸文本")
        self.assertEqual(react_pure.strip_fence(
            {"text": '```json\n{"a": 1}\n```'})["text"], '{"a": 1}')
        self.assertEqual(react_pure.strip_fence(
            {"text": '```json\n{"a": 1}'})["text"], '{"a": 1}')
        self.assertEqual(react_pure.strip_fence(
            {"text": '```json {"a": 1} ```'})["text"], '{"a": 1}')

        # T6 attach_protocol：无 system 不改消息、空协议原样、多 system 只改首条
        no_sys = react_pure.attach_protocol(
            {"messages": [{"role": "user", "content": "开工"}], "protocol": "收口 JSON"})
        self.assertEqual(no_sys["messages"][0]["content"], "开工")
        empty_proto = react_pure.attach_protocol(
            {"messages": [{"role": "system", "content": "人设"}], "protocol": "  "})
        self.assertEqual(empty_proto["messages"][0]["content"], "人设")
        multi = react_pure.attach_protocol({
            "messages": [{"role": "system", "content": "首条"},
                         {"role": "system", "content": "次条"}],
            "protocol": "收口 JSON"})
        self.assertIn("收口 JSON", multi["messages"][0]["content"])
        self.assertEqual(multi["messages"][1]["content"], "次条")

        # T7 classify_tool：size 恰等于阈值不判 large，超 1 字符才落盘
        self.assertFalse(react_pure.classify_tool(
            {"content": "x" * 1000, "threshold": 1000})["large"])
        self.assertTrue(react_pure.classify_tool(
            {"content": "x" * 1001, "threshold": 1000})["large"])
        self.assertEqual(react_pure.classify_tool(
            {"content": "x" * 1001, "threshold": 1000})["size"], 1001)

        # 检查点成形：快照拷贝，覆盖 messages/summary/steps/updated，其余字段原样保留
        rec = {"id": "s1", "kind": "role", "status": "running", "summary": "旧",
               "messages": [{"role": "system", "content": "人设"}], "steps": 2}
        ck = react_pure.checkpoint({"rec": rec,
            "messages": [{"role": "system"}, {"role": "user", "content": "指令"},
                         {"role": "assistant", "content": "回"}],
            "summary": "新摘要", "steps": 4, "now": "t2"})
        self.assertEqual(ck["id"], "s1")
        self.assertEqual(ck["status"], "running")
        self.assertEqual(len(ck["messages"]), 3)
        self.assertEqual(ck["summary"], "新摘要")
        self.assertEqual(ck["steps"], 4)
        self.assertEqual(ck["updated"], "t2")
        # 不改动原快照
        self.assertEqual(rec["summary"], "旧")
        self.assertEqual(rec["steps"], 2)

        now = 1000000

        # 启动续跑计划：开开关且未超上限 → resume 标记中断痕迹并复位 idle；超出上限 → stale 复位
        rows2 = [
            {"path": "a.yaml", "rec": {"id": "a", "status": "running"}},
            {"path": "b.yaml", "rec": {"id": "b", "status": "running"}},
            {"path": "c.yaml", "rec": {"id": "c", "status": "running"}},
            {"path": "d.yaml", "rec": {"id": "d", "status": "idle"}},
        ]
        plan = sess_run.resume_plan({"rows": rows2, "now": now, "enabled": True, "max": 2,
                                     "resume_text": "续跑提示", "stale_text": "复位提示"})
        self.assertEqual([i["id"] for i in plan["resume"]], ["a", "b"])
        self.assertEqual([i["id"] for i in plan["stale"]], ["c"])
        ra = plan["resume"][0]["rec"]
        self.assertEqual(ra["status"], "idle")
        self.assertEqual(ra["meta"]["resumed"], 1)
        self.assertEqual(ra["meta"]["last_error"]["code"], "interrupted_on_boot")
        self.assertEqual(ra["meta"]["last_error"]["error"], "续跑提示")
        self.assertEqual(ra["updated"], now)
        sc = plan["stale"][0]["rec"]
        self.assertEqual(sc["meta"]["last_error"]["error"], "复位提示")
        # 关开关：running 全部归 stale，不续跑
        off = sess_run.resume_plan({"rows": rows2, "now": now, "enabled": False, "max": 2,
                                    "resume_text": "续跑提示", "stale_text": "复位提示"})
        self.assertEqual(off["resume"], [])
        self.assertEqual([i["id"] for i in off["stale"]], ["a", "b", "c"])
        # max=0 不限制条数
        allr = sess_run.resume_plan({"rows": rows2, "now": now, "enabled": True, "max": 0,
                                    "resume_text": "续跑提示", "stale_text": "复位提示"})
        self.assertEqual(len(allr["resume"]), 3)

    def test_session_stuck_plan_classifies_missing_and_stalled(self):
        """自愈扫描：任务丢失 / 停滞超阈值复位 idle；在途新鲜会话保留；非 running 不碰。"""
        now = 1000000
        rows = [
            {"path": "dead.yaml", "rec": {"id": "dead", "status": "running"}, "idle_seconds": 3},
            {"path": "stalled.yaml", "rec": {"id": "stalled", "status": "running"}, "idle_seconds": 99999},
            {"path": "live.yaml", "rec": {"id": "live", "status": "running"}, "idle_seconds": 5},
            {"path": "idle.yaml", "rec": {"id": "idle", "status": "idle"}, "idle_seconds": 1},
        ]
        plan = sess_run.stuck_plan({"rows": rows, "active": ["stalled", "live"], "now": now,
                                    "enabled": True, "idle_seconds": 30 * 60,
                                    "stale_text": "卡死复位提示"})
        self.assertEqual([i["id"] for i in plan["stuck"]], ["dead", "stalled"])
        self.assertEqual(plan["keep"], ["live"])
        dead = plan["stuck"][0]["rec"]
        self.assertEqual(dead["status"], "idle")
        self.assertEqual(dead["meta"]["last_error"]["code"], "stuck_missing_task")
        self.assertEqual(dead["updated"], now)
        stalled = plan["stuck"][1]["rec"]
        self.assertEqual(stalled["meta"]["last_error"]["code"], "stuck_stalled")
        self.assertEqual(stalled["meta"]["last_error"]["error"], "卡死复位提示")
        # 关开关：一律保留不复位
        off = sess_run.stuck_plan({"rows": rows, "active": [], "now": now,
                                   "enabled": False, "idle_seconds": 30 * 60,
                                   "stale_text": "x"})
        self.assertEqual(off["stuck"], [])
        self.assertEqual(len(off["keep"]), 3)
        # 不设停滞阈值：在途会话不按 stalled 复位，仅任务丢失的复位
        nolimit = sess_run.stuck_plan({"rows": rows, "active": ["stalled", "live"], "now": now,
                                        "enabled": True, "idle_seconds": 0,
                                        "stale_text": "x"})
        self.assertEqual([i["id"] for i in nolimit["stuck"]], ["dead"])
        self.assertEqual(nolimit["keep"], ["stalled", "live"])

    def test_active_same_role_idempotent_dedupe(self):
        """同工单同岗在途查重：只并在途（queued/running/stalled），排除空闲/终态/异岗异单。"""
        records = [
            {"id": "role-1", "ticket": "T-1", "role": "developer", "status": "running"},
            {"id": "role-2", "ticket": "T-1", "role": "developer", "status": "idle"},
            {"id": "role-3", "ticket": "T-1", "role": "designer", "status": "running"},
            {"id": "role-4", "ticket": "T-2", "role": "developer", "status": "queued"},
            {"id": "role-5", "ticket": "T-1", "role": "developer", "status": "stalled"},
        ]
        dup = sess_run.active_same_role({"ticket": "T-1", "role": "developer", "records": records})
        self.assertEqual([r["id"] for r in dup["items"]], ["role-1", "role-5"])
        # 异岗：designer 的在途会话不进 developer 结果；独立查 designer 命中自身
        idle = sess_run.active_same_role({"ticket": "T-1", "role": "designer", "records": records})
        self.assertEqual([r["id"] for r in idle["items"]], ["role-3"])
        # ticket / role 任一为空不并线，避免误合
        self.assertEqual(
            sess_run.active_same_role({"ticket": "", "role": "developer", "records": records})["items"], [])
        self.assertEqual(
            sess_run.active_same_role({"ticket": "T-1", "role": "", "records": records})["items"], [])

    def test_skill_unit_pure_functions(self):
        # install_parts：流程拆不出 → flow=null、skill.flow 留空；岗位/工具带同一 skill 归属
        draft_empty = {"id": "ppt_design_skill",
                       "role": {"cn": "演示文稿设计师", "must_dos": ["出稿"],
                                "forbidden": ["不改码"], "tools": ["artifact_read"]},
                       "flow": {"checks": [], "nodes": [], "edges": []},
                       "tools": [{"name": "ppt_render", "desc": "渲染", "params": [],
                                  "deps": {"pip": ["python-pptx"]}}]}
        out = decompose_pure.install_parts(
            {"draft": draft_empty, "meta": {"id": "ppt_design_skill", "doc": "做PPT", "version": "v1"},
             "source": "github:x", "now": "t1"})
        self.assertIsNone(out["flow"])
        self.assertEqual(out["skill"]["flow"], "")
        self.assertEqual(out["skill"]["status"], "enabled")
        self.assertEqual(out["role"]["skill"], "ppt_design_skill")
        self.assertEqual(out["tools"][0]["skill"], "ppt_design_skill")
        self.assertIn("artifact_read", out["role"]["tools"])
        self.assertIn("ppt_render", out["role"]["tools"])
        # 带检查项 → 流程成形，skill.flow 指向流程标识
        draft_flow = dict(draft_empty)
        draft_flow["flow"] = {"checks": [{"kind": "file", "paths": ["docs/a.md"]}],
                              "nodes": [], "edges": []}
        out2 = decompose_pure.install_parts(
            {"draft": draft_flow, "meta": {"id": "ppt_design_skill"}, "now": "t2"})
        self.assertIsNotNone(out2["flow"])
        self.assertEqual(out2["skill"]["flow"], "ppt_design_skill")
        # 缺标识 → 成形报错，不落有效记录
        bad = decompose_pure.install_parts({"draft": {"role": {}}})
        self.assertFalse(bad["ok"])

    def test_decompose_safe_pkg_validates_name(self):
        # 合法名 / 带版本约束 / 环境标记 → 剥成纯包名；注入字符与路径 → 拒
        self.assertEqual(decompose_pure.safe_pkg("python-pptx")["pkg"], "python-pptx")
        self.assertEqual(decompose_pure.safe_pkg("python-pptx==1.0.0b8")["pkg"],
                         "python-pptx")
        self.assertFalse(decompose_pure.safe_pkg('requests; python_version>"3.8"')["ok"])
        self.assertFalse(decompose_pure.safe_pkg("pptx; rm -rf /")["ok"])
        self.assertFalse(decompose_pure.safe_pkg("foo/bar")["ok"])
        self.assertFalse(decompose_pure.safe_pkg("")["ok"])
        # 工具定义：拉文档、装 pip、跑命令三个拆解期动作
        names = [t["name"] for t in decompose_pure.tool_defs()]
        self.assertEqual(names, ["fetch_url", "pip_install", "shell"])

    def test_decompose_run_reacts_with_restricted_tools(self):
        import json
        draft = {"role": {"cn": "演示师", "must_dos": ["出稿"], "forbidden": [],
                          "tools": []},
                 "flow": {"checks": [], "nodes": [], "edges": []},
                 "new_tools": [{"name": "ppt_render", "desc": "渲染", "params": [],
                                "deps": {"pip": ["python-pptx"]}}]}
        captured = {}

        def fake_react(ctx, payload):
            captured["tools"] = [t["name"] for t in payload.get("tools") or []]
            text = json.dumps(draft, ensure_ascii=False)
            return {"steps": 1, "messages": [{"role": "assistant", "content": text}],
                    "last": {"role": "assistant", "content": text},
                    "cancelled": False, "failed": None}

        original = self.ctx.api.route("react.run")["fn"]
        self.ctx.api.substitute("react.run", fake_react)
        try:
            r = self.ctx.api.call("decompose.run", {
                "skill_md": "---\nname: ppt_x\ndescription: 演示\n---\n正文", "system": ""})
        finally:
            self.ctx.api.substitute("react.run", original)
        self.assertEqual(captured["tools"], ["fetch_url", "pip_install", "shell"])
        self.assertEqual(r["draft"]["id"], "ppt_x")
        self.assertEqual([t["name"] for t in r["draft"]["tools"]], ["ppt_render"])
        # 工具已注册；fetch_url/pip_install 是拆解专用不进普通名单，shell 已提升为内置
        for tn in ("fetch_url", "pip_install", "shell"):
            self.assertTrue(self.ctx.tools.has(tn))
        listed = {t["name"] for t in self.ctx.tools.list_tools()}
        self.assertNotIn("fetch_url", listed)
        self.assertNotIn("pip_install", listed)
        self.assertIn("shell", listed)

    def test_decompose_install_effects_only_on_valid_parts(self):
        draft = {"id": "ppt_x",
                 "role": {"cn": "演示师", "must_dos": ["出稿"], "forbidden": [],
                          "tools": []},
                 "flow": {"checks": [], "nodes": [], "edges": []},
                 "tools": [{"name": "ppt_render", "desc": "渲染", "params": [],
                            "deps": {"pip": ["python-pptx"]}}]}
        parts = decompose_pure.install_parts(
            {"draft": draft, "meta": {"id": "ppt_x", "doc": "演示"}, "now": "t1"})
        eff = decompose_pure.install_effects(
            {"parts": parts, "roles": {}, "flows": {}, "tools": {}, "skills": {}})
        self.assertTrue(eff["ok"])
        paths = [e["path"] for e in eff["effects"]]
        self.assertIn("roles.yaml", paths)
        self.assertIn("tools.yaml", paths)
        self.assertIn("skills.yaml", paths)
        self.assertNotIn("flows.yaml", paths, "流程拆不出不写 flows.yaml")
        # 无效产物（缺 skill）→ 空 effects，不落盘
        bad = decompose_pure.install_effects({"parts": {"role": {}}})
        self.assertFalse(bad["ok"])
        self.assertEqual(bad["effects"], [])

    def test_decompose_install_route_skips_write_on_invalid(self):
        r = self.ctx.api.call("decompose.install",
                              {"draft": None, "meta": {}, "source": "", "now": "t"})
        self.assertFalse(r["ok"])
        self.assertEqual(r["effects"], [])

        # skills_listp：关联岗位中文名、流程在库与否、工具名、启停文本
        skills = {"s1": {"id": "s1", "cn": "PPT师", "status": "enabled", "role": "r1",
                         "flow": "f1", "tools": ["t1"], "builtin": False},
                  "s2": {"id": "s2", "cn": "生图师", "status": "disabled", "role": "r2",
                         "flow": "", "tools": ["t2"], "builtin": False}}
        roles = {"r1": {"id": "r1", "cn": "PPT师", "skill": "s1"},
                 "r2": {"id": "r2", "cn": "生图师", "skill": "s2"}}
        flows = {"f1": {"id": "f1", "role": "r1", "checks": []}}
        tools = {"t1": {"name": "t1", "skill": "s1"}, "t2": {"name": "t2", "skill": "s2"}}
        listed = lib_pure.skills_listp({"skills": skills, "roles": roles,
                                        "flows": flows, "tools": tools})["items"]
        row1 = next(x for x in listed if x["id"] == "s1")
        row2 = next(x for x in listed if x["id"] == "s2")
        self.assertEqual(row1["role_cn"], "PPT师")
        self.assertTrue(row1["has_flow"])
        self.assertEqual(row1["status"], "enabled")
        self.assertEqual(row1["tools"], "t1")
        self.assertFalse(row2["has_flow"])
        self.assertEqual(row2["status"], "disabled")

        # disabled_p：只成形已禁用标识清单
        self.assertEqual(lib_pure.disabled_p({"skills": skills})["ids"], ["s2"])

        # 岗位清单摘除禁用 Skill 的岗位；seed 为空时不含内置条目
        pos = lib_pure.positionsp({"seed": {}, "user": roles, "flows": flows,
                                   "skills": skills})["items"]
        self.assertIn("r1", [p["id"] for p in pos])
        self.assertNotIn("r2", [p["id"] for p in pos])

        # skill_statusp：翻转状态；内置受保护
        on = lib_pure.skill_statusp({"id": "s1", "record": skills["s1"],
                                     "status": "disabled", "now": "t3"})
        self.assertEqual(on["status"], "disabled")
        self.assertEqual(on["updated"], "t3")
        prot = lib_pure.skill_statusp({"id": "b", "record": {"builtin": True},
                                       "status": "disabled", "now": "t"})
        self.assertFalse(prot["ok"])
        self.assertEqual(prot["status"], 403)

        # skill_uninstallp：级联删岗位/流程/工具/Skill；内置受保护
        removed = lib_pure.skill_uninstallp(
            {"id": "s1", "skills": dict(skills), "roles": dict(roles),
             "flows": dict(flows), "tools": dict(tools)})
        self.assertNotIn("s1", removed["skills"])
        self.assertNotIn("r1", removed["roles"])
        self.assertNotIn("f1", removed["flows"])
        self.assertNotIn("t1", removed["tools"])
        self.assertIn("s2", removed["skills"])
        prot_un = lib_pure.skill_uninstallp(
            {"id": "b", "skills": {"b": {"builtin": True}}, "roles": {}, "flows": {}, "tools": {}})
        self.assertFalse(prot_un["ok"])
        self.assertEqual(prot_un["status"], 403)

        # 工具合并：归属禁用 Skill 的外部工具不进清单；清单行带 skill 归属
        merged = tools_pure.merge({"builtin": [], "external": tools, "disabled": ["s2"]})
        self.assertEqual([t["name"] for t in merged["items"]], ["t1"])
        listing = tools_pure.listing({"tools": merged["items"], "snapshot": {}})["items"]
        self.assertEqual(listing[0]["skill"], "s1")

    def test_project_override_pure_parts_and_toggle(self):
        """覆盖层纯函数：缺省五类空清单；禁用加入、启用移出、去重保序；非法类型/标识返错误形状。"""
        empty = projects_pure.override_parts({"rec": {}})
        self.assertEqual(empty, {"roles": [], "flows": [], "skills": [], "tools": [], "states": []})
        rec = {"id": "p1", "overrides": {"roles": [" dev ", "dev"], "tools": ["t1"]}}
        parts = projects_pure.override_parts({"rec": rec})
        self.assertEqual(parts["roles"], ["dev"])
        self.assertEqual(parts["tools"], ["t1"])

        off = projects_pure.toggle_override({"rec": rec, "kind": "roles",
                                            "id": "qa", "enabled": False, "now": "t1"})
        self.assertEqual(off["overrides"]["roles"], ["dev", "qa"])
        on = projects_pure.toggle_override({"rec": off, "kind": "roles",
                                           "id": "dev", "enabled": True, "now": "t2"})
        self.assertEqual(on["overrides"]["roles"], ["qa"])
        # 状态节点覆盖：禁用状态入清单、启用移出，与岗位/工具同构
        st_off = projects_pure.toggle_override({"rec": rec, "kind": "states",
                                               "id": "verify", "enabled": False, "now": "t1"})
        self.assertEqual(st_off["overrides"]["states"], ["verify"])
        st_on = projects_pure.toggle_override({"rec": st_off, "kind": "states",
                                              "id": "verify", "enabled": True, "now": "t2"})
        self.assertEqual(st_on["overrides"]["states"], [])

        bad_kind = projects_pure.toggle_override({"rec": {}, "kind": "billing",
                                                  "id": "x", "enabled": False})
        self.assertFalse(bad_kind["ok"])
        missing_id = projects_pure.toggle_override({"rec": {}, "kind": "roles",
                                                    "id": "  ", "enabled": False})
        self.assertFalse(missing_id["ok"])

    def test_project_screen_filters_non_record_files(self):
        """列表/分级树：messages.yaml 这类无档案 id 的文案模板 dict 不渲染成空壳项目。"""
        rows = [{"id": "p1", "name": "项目一", "created": "t1"},
                {"missing": "项目不存在: {id}", "conflict": "项目已存在: {id}"},
                None]
        items = projects_pure.screen({"rows": rows})["items"]
        self.assertEqual([x["id"] for x in items], ["p1"])

        tree = projects_pure.tree({"projects": rows, "tickets": []})["items"]
        self.assertEqual([x["project"]["id"] for x in tree], ["p1"])

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
        """对话型会话仅读知识后向用户提问、无产物/编排动作：判等待用户，只落盘不回催不复盘。"""
        waiting_msgs = [
            {"role": "system", "content": "人设"},
            {"role": "user", "content": "开工"},
            {"role": "assistant", "tool_calls": [{"function": {"name": "knowledge_search"}}],
             "content": "先查知识"},
            {"role": "tool", "name": "knowledge_search", "content": '{"items": []}'},
            {"role": "assistant", "content": "需求信息不足，请补充被测对象与验收标准。"},
        ]
        rec = {"id": "ch-1", "kind": "channel", "role": "", "ticket": "T-1",
               "meta": {}, "messages": waiting_msgs}
        plan = sess_run.flow_plan({
            "rec": rec, "review": {"verdict": "pass", "missing": [], "retries": 0},
            "ticket": "T-1", "repush_text": "", "retrospect_text": "复盘", "exhausted_text": ""})
        self.assertEqual(plan["verdict"], "waiting")
        kinds = [e["kind"] for e in plan["effects"]]
        self.assertEqual(kinds, ["write"])
        self.assertNotIn("dispatch", kinds)
        self.assertFalse(plan["rec"]["meta"].get("retrospected"))

    def test_flow_plan_auto_session_not_waiting(self):
        """后台自动会话（pm/role）不设等待闸门：读类工具后陈述也按终态判定进入闭环。"""
        auto_msgs = [
            {"role": "system", "content": "人设"},
            {"role": "user", "content": "工单任务"},
            {"role": "assistant", "tool_calls": [{"function": {"name": "ticket_read_doc"}}],
             "content": "先读工单"},
            {"role": "tool", "name": "ticket_read_doc", "content": '{"ok": true}'},
            {"role": "assistant", "content": "需求要点已梳理，进入编排与分派。"},
        ]
        rec = {"id": "pm-1", "kind": "pm", "role": "pm", "ticket": "T-1",
               "meta": {}, "messages": auto_msgs}
        plan = sess_run.flow_plan({
            "rec": rec, "review": {"verdict": "repush", "missing": [{"kind": "stage"}],
                                   "retries": 1},
            "ticket": "T-1", "repush_text": "回催", "retrospect_text": "复盘",
            "exhausted_text": "卡点"})
        self.assertNotEqual(plan["verdict"], "waiting")
        self.assertIn("dispatch", [e["kind"] for e in plan["effects"]])

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
        done = sess_run.finish({"rec": rec, "out": failed_out, "latest": {}, "now": 1,
                                "result_chars": 500})
        self.assertEqual(done["meta"]["last_error"]["error"], "余额不足")
        self.assertTrue(done["result"].get("failed"))
        ok_out = {"messages": [{"role": "assistant", "content": "好"}], "steps": 1,
                  "last": {"content": "好"}, "cancelled": False, "failed": None}
        cleared = sess_run.finish({"rec": done, "out": ok_out, "latest": {}, "now": 2,
                                   "result_chars": 500})
        self.assertNotIn("last_error", cleared["meta"])

    def test_finish_records_stage_and_alert(self):
        """合法跳转落新阶段；非法跳转保留旧阶段并留告警；无校验时按 out.stage 落库。"""
        base_out = {"messages": [], "steps": 1, "last": {"content": "好"},
                    "cancelled": False, "failed": None}
        ok = sess_run.finish({"rec": {"id": "s-1", "meta": {"stage": "a"}},
                              "out": dict(base_out, stage="b"),
                              "stage_check": {"ok": True, "code": "ok", "stage": "b"},
                              "latest": {}, "now": 1, "result_chars": 500})
        self.assertEqual(ok["meta"]["stage"], "b")
        self.assertNotIn("stage_alert", ok["meta"])
        bad = sess_run.finish({"rec": {"id": "s-1", "meta": {"stage": "a"}},
                               "out": dict(base_out, stage="c"),
                               "stage_check": {"ok": False, "code": "illegal_edge", "stage": "a"},
                               "latest": {}, "now": 2, "result_chars": 500})
        self.assertEqual(bad["meta"]["stage"], "a")
        self.assertEqual(bad["meta"]["stage_alert"]["code"], "illegal_edge")
        self.assertEqual(bad["meta"]["stage_alert"]["nxt"], "c")
        plain = sess_run.finish({"rec": {"id": "s-1", "meta": {}},
                                 "out": dict(base_out, stage="a"),
                                 "latest": {}, "now": 3, "result_chars": 500})
        self.assertEqual(plain["meta"]["stage"], "a")

    def test_thread_exposes_session_meta(self):
        """线程视图要露出主会话 meta，界面才能判断 PM 有无卡点。"""
        thread = {"id": "pm-2", "name": "pm", "status": "idle",
                  "role": "", "updated": 1, "meta": {"tools": []}, "messages": []}
        out = ticket_pure.threadp({"ticket": {"id": "T-1", "roles": []}, "thread": thread})
        self.assertEqual(out["thread"]["meta"], {"tools": []})

    def test_thread_messages_carry_at(self):
        """群聊按时间穿插表征：历史消息缺时间戳时用会话起始时刻补，且同会话单调递增。"""
        ticket = {"id": "T-1", "roles": [{"session": "role-1", "role": "developer"}],
                  "transcript": {}}
        thread = {"id": "pm-1", "name": "pm", "status": "idle", "role": "", "created": 100,
                  "updated": 200, "meta": {}, "messages": [{"role": "user", "content": "a"},
                                                            {"role": "assistant", "content": "b"}]}
        live = [{"id": "role-1", "role": "developer", "status": "busy", "created": 150,
                 "messages": [{"role": "assistant", "content": "c"},
                              {"role": "assistant", "content": "d", "at": 190}]}]
        out = ticket_pure.threadp({"ticket": ticket, "thread": thread, "role_threads": live})
        ats = [m.get("at") for m in out["thread"]["messages"]]
        self.assertTrue(all(isinstance(a, (int, float)) for a in ats), ats)
        pm_ats = [m["at"] for m in out["thread"]["messages"] if m["session"] == "pm-1"]
        self.assertEqual(pm_ats, sorted(pm_ats))
        role_ats = [m["at"] for m in out["thread"]["messages"] if m["session"] == "role-1"]
        self.assertEqual(role_ats, sorted(role_ats))
        self.assertEqual(role_ats[-1], 190)

    def test_thread_members_carry_task(self):
        """成员卡要展示职责，members 必须自带 task，前端不得回查 roles 补字段。"""
        ticket = {"id": "T-1", "goal": "把需求做完",
                  "roles": [{"session": "role-1", "role": "developer",
                             "display": "探针", "task": "任务 x"}],
                  "transcript": {}}
        thread = {"id": "pm-1", "name": "pm-t-1", "status": "idle",
                  "role": "", "updated": 1, "meta": {"tools": []}, "messages": []}
        out = ticket_pure.threadp({"ticket": ticket, "thread": thread})
        by_sid = {m["session"]: m for m in out["members"]}
        self.assertEqual(by_sid["pm-1"]["task"], "把需求做完")
        self.assertEqual(by_sid["role-1"]["task"], "任务 x")

    def test_spawn_refuses_role_disabled_by_project(self):
        """项目里禁用岗位必须联动到派单：禁掉的岗位不能再被拉起，且拒绝原因要显形。

        走需求入口而不是直连能力：项目档案由编排层读出并作为 project_overrides 传给能力，
        sessions 不自己碰 projects 目录；引擎把失败那一步（sessions.spawn）连带 ApiError 文案带出来。
        """
        self.ctx.api.call("store.write", {"module": "agent/projects", "path": "p-demo.yaml",
            "value": {"id": "p-demo", "name": "p-demo",
                      "overrides": {"roles": ["developer"]}}}, caller=None)
        res = self.ctx.api.call("demand_engine.run", {"id": "session-spawn", "input": {
            "kind": "role", "role": "developer", "project": "p-demo",
            "ticket": "T-x", "name": "x"}}, caller=None)
        self.assertFalse(res.get("ok"))
        failed = res.get("failed") or {}
        self.assertEqual(failed.get("call"), "sessions.spawn")
        self.assertIn("已被禁用", failed.get("error", ""))
        self.assertIn("p-demo", failed.get("error", ""))
        self.ctx.api.call("store.remove", {"module": "agent/projects",
            "path": "p-demo.yaml"}, caller=None)

    def test_thread_carries_wire_brief_and_wire_at_reads_raw(self):
        """报文原文不再随群聊流下发：视图只带摘要与序位，原文按需回读同一条消息。"""
        from ai_new.modules.agent.tickets.private import _pure as ticket_pure
        from ai_new.modules.agent.sessions.private import _pure as session_pure
        raw = {"url": "http://x/v1/chat/completions", "model": "m", "status": 200,
               "stream": True, "request": '{"messages":[]}', "response": "data: {\"a\":1}"}
        stamped = ticket_pure._stamp([{"role": "assistant", "content": "hi", "wire": raw}],
                                     "s1", "pm", 1.0)
        brief = stamped[0]["wire"]
        self.assertEqual(brief["seq"], 0)
        self.assertEqual(brief["req_len"], len(raw["request"]))
        self.assertNotIn("request", brief)
        got = session_pure.wire_at({"rec": {"id": "s1", "messages": [
            {"role": "assistant", "wire": raw}]}, "seq": 0})
        self.assertTrue(got["ok"])
        self.assertEqual(got["wire"]["request"], raw["request"])
        miss = session_pure.wire_at({"rec": {"id": "s1", "messages": []}, "seq": 0})
        self.assertFalse(miss["ok"])

    def test_react_summarize_falls_back_only_without_model_summary(self):
        """逐轮压缩：模型给了摘要就听模型的；没给（步数耗尽/中断）才由系统按上限补工具往返。"""
        from ai_new.modules.agent_common.react.private import _pure as react_pure
        new = [{"role": "assistant", "tool_calls": [
                    {"function": {"name": "artifact_read", "arguments": "{\"path\":\"docs/a.md\"}"}}]},
               {"role": "tool", "content": "文件正文前 20 字…"}]
        by_model = react_pure.summarize({"summary": "本轮已定稿", "messages": new,
                                         "by_model": True, "chars": 600, "title": "兜底"})
        self.assertEqual(by_model["summary"], "本轮已定稿")
        self.assertFalse(by_model["fallback"])
        fb = react_pure.summarize({"summary": "旧摘要", "messages": new,
                                   "by_model": False, "chars": 600, "title": "兜底"})
        self.assertTrue(fb["fallback"])
        self.assertIn("旧摘要", fb["summary"])
        self.assertIn("artifact_read", fb["summary"])
        self.assertIn("文件正文", fb["summary"])
        capped = react_pure.summarize({"summary": "", "messages": new,
                                       "by_model": False, "chars": 40, "title": "兜底"})
        self.assertLessEqual(len(capped["summary"]), 41)

    def test_llm_wire_masks_secret_and_keeps_raw(self):
        """网络报文要能原样回查：请求体与响应原文保留，密钥类头打码。"""
        from ai_new.modules.agent_common.llm.private import _client as llm_client
        wire = llm_client.wire({"url": "http://x/v1/chat/completions",
            "headers": {"Content-Type": "application/json", "Authorization": "Bearer sk-1",
                        "X-Api-Key": "sk-2"},
            "request": '{"model":"m","messages":[]}',
            "status": 200, "response": 'data: {"choices":[]}', "model": "m", "stream": True})
        self.assertEqual(wire["headers"]["Authorization"], "***")
        self.assertEqual(wire["headers"]["X-Api-Key"], "***")
        self.assertEqual(wire["headers"]["Content-Type"], "application/json")
        self.assertIn('"model"', wire["request"])
        self.assertTrue(wire["response"].startswith("data:"))
        self.assertTrue(wire["stream"])

    def test_todo_ops_crud_and_patch(self):
        """待办是模型自排计划的工具：增删查改都走同一条能力，改过才回会话补丁。"""
        from ai_new.modules.agent.todos.private import _pure as todo_pure
        st = {"todos": []}
        for action, kw in [("add", {"text": "读需求", "status": "doing"}),
                           ("add", {"text": "写代码"})]:
            out = todo_pure.apply_ops({"todos": st["todos"], "limit": 40, "args": dict(action=action, **kw)})
            self.assertTrue(out["ok"])
            st["todos"] = out["todos"]
        self.assertEqual([t["id"] for t in st["todos"]], ["t1", "t2"])
        self.assertEqual(st["todos"][1]["status"], "pending")
        upd = todo_pure.apply_ops({"todos": st["todos"], "limit": 40,
                                   "args": {"action": "update", "id": "t2", "status": "done"}})
        self.assertEqual(upd["counts"], {"total": 2, "pending": 0, "doing": 1, "done": 1})
        gone = todo_pure.apply_ops({"todos": upd["todos"], "limit": 40,
                                    "args": {"action": "remove", "id": "t1"}})
        self.assertEqual([t["id"] for t in gone["todos"]], ["t2"])
        bad = todo_pure.apply_ops({"todos": gone["todos"], "limit": 40,
                                   "args": {"action": "update", "id": "t9", "status": "done"}})
        self.assertFalse(bad["ok"])
        self.assertEqual(bad["code"], "not_found")
        rep = todo_pure.apply_ops({"todos": gone["todos"], "limit": 40,
                                   "args": {"action": "replace",
                                            "items": [{"text": "甲", "status": "todo"},
                                                      {"text": "乙", "status": "done"}]}})
        self.assertEqual([t["status"] for t in rep["todos"]], ["pending", "done"])
        self.assertEqual(todo_pure.apply_ops({"todos": rep["todos"], "limit": 40,
                                              "args": {"action": "clear"}})["todos"], [])

    def test_todo_apply_declares_session_patch_only_when_changed(self):
        """落盘是会话检查点的事：只有改动才回补丁，查询不产生写盘。"""
        out = self.ctx.api.call("todos.apply", {
            "todos": [{"id": "t1", "text": "甲", "status": "doing"}], "limit": 40,
            "args": {"action": "add", "text": "乙"}}, caller=None)
        self.assertIn("session_patch", out)
        self.assertEqual(len(out["session_patch"]["todos"]), 2)
        ro = self.ctx.api.call("todos.apply", {
            "todos": out["todos"], "args": {"action": "list"}}, caller=None)
        self.assertNotIn("session_patch", ro)

    def test_todo_tool_is_demand_bound(self):
        """待办的增删查改必须是工具，且工具只是需求身份，不持有实现、不自己写盘。"""
        item = self.ctx.tools._tools.get("todo")
        self.assertIsNotNone(item)
        self.assertEqual(item["demand"], "todo-write")
        self.assertIsNone(item["fn"])

    def test_stage_tool_whitelists_keep_todo(self):
        """阶段裁剪按状态 tools 白名单走：漏了 todo 就会把待办工具裁掉，数据契约必须齐。"""
        seed = self.ctx.api.call("store.read", {
            "module": "agent/library", "path": "seed.yaml"}, caller=None)["value"]
        misses = []
        for flow in seed.get("flows") or []:
            for stage in flow.get("states") or []:
                names = stage.get("tools")
                if isinstance(names, list) and "todo" not in names:
                    misses.append("%s/%s" % (flow.get("id"), stage.get("id")))
        self.assertEqual(misses, [], "这些状态白名单没有 todo: %s" % misses)

    def test_bind_tools_marks_project_disabled(self):
        """岗位↔流程↔项目工具绑定要能一行摊开：可用数、禁用名与状态链都在行上。"""
        items = [{"id": "developer", "tools": ["artifact_read", "shell", "todo"],
                  "stages": [{"id": "understand", "cn": "研读"},
                             {"id": "implement", "cn": "实现"}]}]
        out = lib_pure.bind_tools({"items": items, "disabled": ["shell"], "kind": "roles"})
        row = out["items"][0]
        self.assertEqual(row["tools_sum"], "2/3")
        self.assertEqual(row["tools_disabled"], ["shell"])
        self.assertEqual(row["stage_text"], "研读 → 实现")

    def test_thread_members_carry_machine(self):
        """状态机可视化要显式看见每个角色在哪个阶段，members 必须带流程链与活跃集合。"""
        ticket = {"id": "T-1", "goal": "把需求做完",
                  "roles": [{"session": "role-1", "role": "developer", "display": "探针"}],
                  "transcript": {}}
        stage = {"id": "implement", "cn": "实现", "desc": "按方案落地",
                 "next": ["verify"], "tools": ["read"], "terminal": False}
        thread = {"id": "pm-1", "name": "pm-t-1", "status": "busy", "role": "",
                  "updated": 1, "meta": {"tools": []}, "messages": [],
                  "flow": {"id": "pm", "cn": "PM 流程"}, "stage": "analyze",
                  "active": ["analyze", "plan"], "stages": [stage]}
        role_threads = [{"id": "role-1", "role": "developer", "name": "探针",
                         "status": "running", "messages": [], "stage": "implement",
                         "active": ["implement"], "stages": [stage]}]
        out = ticket_pure.threadp({"ticket": ticket, "thread": thread,
                                   "role_threads": role_threads})
        by_sid = {m["session"]: m for m in out["members"]}
        pm = by_sid["pm-1"]["machine"]
        self.assertEqual(pm["stage"], "analyze")
        self.assertEqual(pm["active"], ["analyze", "plan"])
        self.assertEqual(pm["flow"]["cn"], "PM 流程")
        role = by_sid["role-1"]["machine"]
        self.assertEqual(role["stage"], "implement")
        self.assertEqual(role["states"][0]["cn"], "实现")
        self.assertNotIn("tools", role["states"][0])

    def test_thread_does_not_duplicate_pm_session(self):
        """by_ticket 会把 PM 主会话一并归集；线程视图不得把它当角色二次并入成员与消息流。"""
        intro = "工单 T-1\n\n标题：测试\n\n需求原文：\n\n测试链路是否Ok"
        ticket = {"id": "T-1", "roles": [{"session": "role-1", "role": "developer",
                                          "display": "探针", "task": "任务 x"}],
                  "transcript": {}}
        thread = {"id": "pm-1", "name": "pm-t-1", "status": "running",
                  "role": "", "updated": 1, "meta": {"tools": []},
                  "messages": [{"role": "user", "content": intro}]}
        role_threads = [
            {"id": "pm-1", "role": "", "name": "pm-t-1", "status": "running",
             "messages": [{"role": "user", "content": intro}]},
            {"id": "role-1", "role": "developer", "name": "探针", "status": "busy",
             "messages": [{"role": "user", "content": "角色任务"}]},
        ]
        out = ticket_pure.threadp({"ticket": ticket, "thread": thread,
                                   "role_threads": role_threads})
        pm_members = [m for m in out["members"] if m["session"] == "pm-1"]
        self.assertEqual(len(pm_members), 1)
        self.assertEqual(len(out["members"]), 2)
        self.assertEqual([r["session"] for r in out["roles"]], ["role-1"])
        intros = [m for m in out["thread"]["messages"] if m["content"] == intro]
        self.assertEqual(len(intros), 1)
        self.assertEqual(len(out["thread"]["messages"]), 2)

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


    def test_next_seq_seeds_from_disk_baseline(self):
        """新桶以磁盘最大号为基线，首号 = baseline + 1。"""
        self.assertEqual(self.ctx.storage.next_seq("test:seed", 9), 10)

    def test_next_seq_is_unique_under_concurrency(self):
        """AtomicAdd 发号：多线程同桶取号不重复，且从基线连续递增。"""
        import threading
        bucket = "test:counter"
        n_threads, per = 8, 50
        collected = [[] for _ in range(n_threads)]

        def worker(i):
            for _ in range(per):
                collected[i].append(self.ctx.storage.next_seq(bucket, 0))

        threads = [threading.Thread(target=worker, args=(i,), daemon=True)
                   for i in range(n_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        flat = [v for part in collected for v in part]
        self.assertEqual(len(flat), n_threads * per)
        self.assertEqual(len(set(flat)), len(flat), "并发取号出现重复: %s" % flat)
        self.assertEqual(sorted(flat), list(range(1, n_threads * per + 1)))


if __name__ == "__main__":
    unittest.main(verbosity=2)
