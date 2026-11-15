"""核心流程冒烟：真实装配（临时 data 目录）+ HTTP 端到端。"""
import json
import os
import shutil
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))

from ai_new.modules.agent_common.boot.private._boot import _build as build  # noqa: E402
from ai_new.modules.agent_common.boot.private._context import Context  # noqa: E402
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

    def test_all_modules_loaded(self):
        expect = {"config", "store", "hooks", "demand_engine", "api", "tools", "llm", "react",
                  "knowledge", "artifacts", "library", "sessions", "projects",
                  "tickets", "agents", "health", "ops", "skills", "web", "http",
                  "channel", "net", "host", "codec", "clock"}
        self.assertEqual(set(self.loaded), expect)

    def test_knowledge_roundtrip(self):
        self.ctx.api.call("knowledge.write", {"layer": "public", "name": "arch-note",
                                              "content": "架构约定：模块只能通过 api 调用。"})
        r = self.ctx.api.call("knowledge.read", {"layer": "public", "name": "arch-note"})
        self.assertIn("架构约定", r["content"])
        # public 层不跨模块借别人的提示词：没有就是没有
        with self.assertRaises(Exception):
            self.ctx.api.call("knowledge.read", {"layer": "public", "name": "secretary"})

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

    def test_channel_post_tail_and_stream_route(self):
        """频道能力：发一条、读回来、并且 watch 是流式路由。"""
        key = "probe-ch"
        self.ctx.api.call("channel.post", {"channel": key, "role": "user", "content": "一"})
        self.ctx.api.call("channel.post", {"channel": key, "role": "user", "content": "二"})
        t = self.ctx.api.call("channel.tail", {"channel": key, "limit": 5})
        mine = [m["content"] for m in t["messages"] if m["role"] == "user"]
        self.assertEqual(mine, ["一", "二"])
        w = self.ctx.api.call("channel.watch", {"channel": key, "cursor": 1, "timeout": 1})
        self.assertEqual([m["content"] for m in w["items"] if m["role"] == "user"], ["二"])
        meta = {r["name"]: r for r in self.ctx.api.routes()}
        self.assertTrue(meta["channel.watch"]["stream"], "watch 必须标 stream 才能走 SSE")

    def test_demand_calls_bind_to_real_routes(self):
        """需求绑定的 func 必须真注册：改函数名/删函数，静态和运行期都躲不过。"""
        from ai_new.modules.agent_common.demand_engine.private import _lang
        meta = {r["name"] for r in self.ctx.api.routes()}
        problems = []
        for path in sorted(_fixtures.module_data("agent_common", "demand_engine")
                           .joinpath("demands").glob("*.json")):
            rec = json.loads(path.read_text(encoding="utf-8"))
            for route in _lang.routes_of(rec.get("do")):
                if route not in meta:
                    problems.append("%s 调了不存在的 func: %s" % (rec.get("id"), route))
        self.assertEqual(problems, [], "需求绑定了不存在的功能: %s" % problems)

    def test_chat_demand_answers_and_does_not_self_trigger(self):
        """一条业务闭环：网页消息 → 模型 → 回复；回复进来不许再把模型叫一次。"""
        key = "rt-chat"
        before = self.fake_net.calls
        self.ctx.api.call("channel.post", {"channel": key, "role": "user", "content": "在吗"})
        self.assertEqual(self.fake_net.calls, before + 1, "用户消息应该触发一次模型调用")
        rows = self.ctx.api.call("channel.tail", {"channel": key, "limit": 10})["messages"]
        self.assertEqual(rows[-1]["role"], "assistant")
        self.assertIn("测试", rows[-1]["content"])
        self.assertEqual(self.fake_net.calls, before + 1, "assistant 消息不能再触发模型（会自激）")

    def test_sse_streams_new_messages(self):
        """SSE：/api/sse/<module>/<fn> 只放行流式路由，并且新消息会立刻推出来。"""
        key = "sse-ch"

        def _open(path):
            req = urllib.request.Request("http://127.0.0.1:%d%s" % (self.port, path),
                                         headers={"X-Auth-Token": "t"})
            return urllib.request.urlopen(req, timeout=5)

        with self.assertRaises(urllib.error.HTTPError) as cm:
            _open("/api/sse/tickets/list?limit=1").read()
        self.assertEqual(cm.exception.code, 400, "非流式路由必须被 SSE 入口拒绝")

        got = []

        def reader():
            try:
                with _open("/api/sse/channel/watch?channel=%s&cursor=0&timeout=3" % key) as resp:
                    for _ in range(6):
                        line = resp.readline().decode("utf-8")
                        if line.startswith("data:"):
                            got.append(json.loads(line[5:].strip()))
                            break
            except Exception:  # noqa: BLE001
                pass

        thread = threading.Thread(target=reader, daemon=True)
        thread.start()
        time.sleep(0.4)
        self.ctx.api.call("channel.post", {"channel": key, "role": "user", "content": "流一下"})
        thread.join(timeout=5)
        self.assertTrue(got, "SSE 没有推出新消息")
        self.assertEqual(got[0]["content"], "流一下")

    def test_artifacts_roundtrip_and_escape(self):
        self.ctx.api.call("demand_engine.run", {"id": "projects-create", "input": {"name": "p1"}})
        w = self.ctx.api.call("artifacts.write", {"layer": "ticket", "project": "p1",
                                                  "ticket": "T-1", "path": "docs/handoff/dev.md",
                                                  "content": "改动点：x"})
        base = self.ctx.storage.all_data()["agent/artifacts"]
        self.assertTrue((base / w["path"]).is_file())
        r = self.ctx.api.call("artifacts.read", {"layer": "ticket", "project": "p1",
                                                 "ticket": "T-1", "path": "docs/handoff/dev.md"})
        self.assertIn("改动点", r["text"])
        with self.assertRaises(Exception):
            self.ctx.api.call("artifacts.write", {"layer": "ticket", "project": "p1",
                                                  "ticket": "T-1", "path": "../../escape.md",
                                                  "content": "x"})

    def test_ticket_lifecycle_and_role_tool(self):
        t = self.ctx.api.call("tickets.create", {"title": "冒烟任务", "goal": "验证工单流程",
                                                 "project": "p1"})
        self.assertTrue(t["pm"], "PM 会话未创建")
        self.assertEqual(t["status"], "queued")
        # PM 会话里派角色（模拟工具调用上下文）
        s = self.ctx.api.call("sessions.get", {"id": t["pm"]})
        self.assertEqual(s["kind"], "pm")
        rs = self.ctx.api.call("tickets.role_spawn", {"id": t["id"], "role": "developer",
                                                      "task": "写一份 docs/handoff/developer.md"})
        self.assertTrue(rs["session"].startswith("role-"))
        # 子单
        sp = self.ctx.api.call("tickets.split", {"id": t["id"],
                                                 "children": [{"title": "子1", "goal": "g1"}]})
        self.assertEqual(len(sp["children"]), 1)
        # 子单未结，父单不能结
        with self.assertRaises(Exception):
            self.ctx.api.call("tickets.close", {"id": t["id"], "summary": "提前结单"})
        self.ctx.api.call("tickets.close", {"id": sp["children"][0], "summary": "子1完成"})
        self.ctx.api.call("tickets.close", {"id": t["id"], "summary": "验证完成"})
        got = self.ctx.api.call("tickets.get", {"id": t["id"]})
        self.assertEqual(got["status"], "closed")

    def test_matrix_denies_undeclared_cross_module_call(self):
        with self.assertRaises(Exception) as cm:
            self.ctx.api.call("tickets.get", {"id": "T-x"}, caller="sessions")
        self.assertIn("未声明", str(cm.exception))

    def test_same_module_call_allowed(self):
        r = self.ctx.api.call("tickets.list", {}, caller="tickets")
        self.assertIsInstance(r.get("items"), list)

    def test_session_run_with_fake_llm(self):
        sp = self.ctx.api.call("sessions.spawn", {"kind": "role", "role": "developer",
                                                  "name": "dev", "ticket": "T-1"})
        out = self.ctx.api.call("sessions.send", {"id": sp["id"], "text": "开始"})
        self.assertEqual(out["status"], "queued")
        done = self.ctx.api.call("sessions.wait", {"id": sp["id"], "timeout": 10})
        self.assertEqual(done["status"], "idle")
        self.assertIn("测试", done["content"])

    def test_health_and_http(self):
        h = self.ctx.api.call("demand_engine.run", {"id": "health-self"})["result"]
        self.assertTrue(h["ok"])
        self.assertGreaterEqual(len(h["modules"]), 19)
        req = urllib.request.Request(
            "http://127.0.0.1:%d/api/rpc/demand_engine/run" % self.port,
            data=json.dumps({"id": "health-self"}).encode("utf-8"), method="POST",
            headers={"X-Auth-Token": "t", "Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            body = json.loads(resp.read().decode("utf-8"))
        self.assertTrue(body["ok"])
        self.assertGreaterEqual(len(body["result"]["result"]["modules"]), 19)
        # 无 token 必须 401
        bad = urllib.request.Request("http://127.0.0.1:%d/api/tickets/list" % self.port)
        with self.assertRaises(urllib.error.HTTPError):
            urllib.request.urlopen(bad, timeout=5)

    def test_rpc_endpoint_returns_raw_result(self):
        """网络通道的服务端：/api/rpc/ 返回未包装的原始结果，供另一个进程直接消费。"""
        body = json.dumps({"layer": "public", "name": "arch-note"}).encode("utf-8")
        req = urllib.request.Request(
            "http://127.0.0.1:%d/api/rpc/knowledge/read" % self.port, data=body, method="POST",
            headers={"X-Auth-Token": "t", "Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            rec = json.loads(resp.read().decode("utf-8"))
        self.assertTrue(rec["ok"])
        self.assertIn("架构约定", rec["result"]["content"])

    def test_ops_overview_and_logs(self):
        o = self.ctx.api.call("demand_engine.run", {"id": "ops-overview"})["result"]
        self.assertIn("sessions", o)
        logs = self.ctx.api.call("ops.logs", {"lines": 20})
        self.assertIn("events", logs)
        lib = self.ctx.api.call("library.summary", {})
        self.assertGreaterEqual(lib["counts"]["roles"], 8)


if __name__ == "__main__":
    unittest.main(verbosity=2)
