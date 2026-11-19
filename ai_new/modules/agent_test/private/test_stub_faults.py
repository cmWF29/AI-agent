"""本地打桩 LLM 服务的故障与链路场景测试。

装配独立临时 data 目录，模型 endpoint 指到本地桩（stub_llm），不接真实上游：
- 脚本化多轮：tool_call → 工具结果回填 → 收口；
- HTTP 5xx / 限流、断连、上下文/token 超限：链路不掀翻，failed 透出故障码；
- 延迟抖动下正常收口。
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))

from ai_new.modules.agent_common.boot.private._boot import _build as build  # noqa: E402
from ai_new.modules.agent_common.boot.private._context import Context  # noqa: E402
from ai_new.modules.agent_test.private import _fixtures  # noqa: E402
from ai_new.modules.agent_test.private import stub_llm  # noqa: E402

TOOLS = [{
    "name": "artifact_write",
    "desc": "写交付件",
    "params": [{"name": "path", "type": "string", "required": True}],
}]


def _assemble(stub_url):
    tmp = tempfile.mkdtemp(prefix="stub_fault_")
    root = Path(tmp)
    _fixtures.stage(root)
    _fixtures.write_config(root, {
        "server": {"host": "127.0.0.1", "port": 0, "token": "t"},
        "llm": {"base_url": stub_url, "api_key": "stub", "model": "stub"},
        "tickets": {"stall_check": {"enabled": False}},
    })
    os.environ["AI_NEW_DATA"] = str(root)
    ctx = Context(root)
    build(ctx)
    return ctx, root


def _run(ctx, stub_url):
    return ctx.api.call("react.run", {
        "session": {"id": "sf-1", "summary": ""},
        "messages": [{"role": "system", "content": "人设"},
                     {"role": "user", "content": "指令"}],
        "tools": TOOLS,
        "base_url": stub_url, "api_key": "stub", "model": "stub",
        "path": "", "cancel": {"id": "sf-1", "since": 0},
    })


class StubFaultTest(unittest.TestCase):
    def setUp(self):
        self._tmp = []
        self._ctx_http = None
        self._stub = None
        self._stub_thread = None

    def tearDown(self):
        os.environ.pop("AI_NEW_DATA", None)
        if self._ctx_http is not None:
            self._ctx_http.shutdown()
            self._ctx_http.server_close()
        if self._stub is not None:
            self._stub.shutdown()
            self._stub.server_close()
            self._stub_thread.join(timeout=2)
        import shutil
        for root in self._tmp:
            shutil.rmtree(root, ignore_errors=True)

    def _start(self, policy):
        server, thread, url = stub_llm.start_stub(policy)
        self._stub, self._stub_thread = server, thread
        ctx, root = _assemble(url)
        self._ctx_http = ctx.http
        self._tmp.append(root)
        return ctx, url

    def test_scripted_tool_call_then_close(self):
        """脚本化：第一轮回 tool_call，第二轮收口；工具结果回填进消息。"""
        script = [
            {"tool_call": {"name": "artifact_write",
                           "arguments": '{"path":"a.md","content":"x"}'}},
            {"reply": '{"reply":"完成","stage":"plan"}'},
        ]
        ctx, url = self._start(stub_llm.StubPolicy(script=script))
        try:
            res = _run(ctx, url)
            self.assertIsNone(res.get("failed"), "脚本化链路不应判失败")
            self.assertEqual(res["steps"], 2)
            roles = [m.get("role") for m in res["messages"]]
            self.assertIn("assistant", roles)
            self.assertIn("tool", roles)
            tool_msg = next(m for m in res["messages"] if m.get("role") == "tool")
            self.assertTrue(tool_msg.get("tool_call_id"))
        finally:
            self._stub.shutdown()
            self._stub_thread.join(timeout=2)

    def test_http_5xx_fault_returns_failed(self):
        """服务端 5xx：重试耗尽后链路透出 failed，不抛异常。"""
        ctx, url = self._start(stub_llm.StubPolicy(fail_code=500, fail_rate=1.0))
        try:
            res = _run(ctx, url)
            self.assertIsNotNone(res.get("failed"))
            code = res["failed"].get("code") or ""
            self.assertTrue(code in ("http_500", "net_error"), code)
        finally:
            self._stub.shutdown()
            self._stub_thread.join(timeout=2)

    def test_connection_close_returns_failed(self):
        """断连：连接被关，链路透出 unreachable/net_error，不掀翻。"""
        ctx, url = self._start(stub_llm.StubPolicy(close_rate=1.0))
        try:
            res = _run(ctx, url)
            self.assertIsNotNone(res.get("failed"))
            code = res["failed"].get("code") or ""
            self.assertTrue(code in ("unreachable", "net_error"), code)
        finally:
            self._stub.shutdown()
            self._stub_thread.join(timeout=2)

    def test_token_limit_returns_failed(self):
        """上下文/token 超限：桩返 context_length_exceeded，链路透出 failed。"""
        ctx, url = self._start(stub_llm.StubPolicy(token_limit=1))
        try:
            res = _run(ctx, url)
            self.assertIsNotNone(res.get("failed"))
            self.assertEqual(res["failed"].get("code"), "context_length_exceeded")
        finally:
            self._stub.shutdown()
            self._stub_thread.join(timeout=2)

    def test_delay_jitter_still_closes(self):
        """延迟抖动下链路仍能正常收口。"""
        ctx, url = self._start(stub_llm.StubPolicy(delay_base=0.01, delay_jitter=0.02))
        try:
            res = _run(ctx, url)
            self.assertIsNone(res.get("failed"))
            self.assertEqual(res["steps"], 1)
        finally:
            self._stub.shutdown()
            self._stub_thread.join(timeout=2)


if __name__ == "__main__":
    unittest.main()
