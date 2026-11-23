"""桩协议级回归：直连本地打桩 HTTP，不经 react 桥接。

锁定两类口径：
- 随机故障三态：断连、HTTP 故障码、上下文/token 超限，桩返回与计数器分类正确；
- 角色/PM 发言结构：角色按工具步序列逐态推进、走完收口并带下一状态；
  PM 按分派序列依次 spawn、去重后收口。
"""
import json
import sys
import unittest
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))

from ai_new.modules.agent_test.private import stub_llm  # noqa: E402

ROLE_TOOLS = [
    {"function": {"name": n, "parameters": {"type": "object"}}}
    for n in ["todo", "knowledge_search", "knowledge_read", "ticket_read_doc", "artifact_read",
              "artifact_write", "knowledge_write", "ticket_note"]
]
PM_TOOLS = [
    {"function": {"name": "role_spawn", "parameters": {"type": "object"}}},
]


def _post(base, body):
    req = urllib.request.Request(
        base + "/chat/completions",
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status, resp.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8")
    except (urllib.error.URLError, ConnectionResetError, OSError) as exc:
        return "CLOSED", repr(exc)


def _parse(text):
    """从 SSE 文本还原 (tool_name, tool_args, 累加正文)。"""
    tool = None
    args = {}
    parts = []
    for line in text.splitlines():
        if not line.startswith("data: "):
            continue
        chunk = line[6:].strip()
        if chunk == "[DONE]":
            continue
        obj = json.loads(chunk)
        delta = (obj.get("choices") or [{}])[0].get("delta") or {}
        for tc in delta.get("tool_calls", []):
            fn = tc.get("function") or {}
            tool = fn.get("name")
            try:
                args = json.loads(fn.get("arguments") or "{}")
            except Exception:  # noqa: BLE001 —— 坏参数按空对象
                args = {}
        if delta.get("content"):
            parts.append(delta["content"])
    return tool, args, "".join(parts)


class StubProtoTest(unittest.TestCase):
    def setUp(self):
        self._srv = None
        self._thr = None

    def tearDown(self):
        if self._srv is not None:
            self._srv.shutdown()
            self._srv.server_close()
        if self._thr is not None:
            self._thr.join(timeout=2)

    def _start(self, policy):
        self._srv, self._thr, url = stub_llm.start_stub(policy)
        return url

    def test_close_connection_counts_closed(self):
        url = self._start(stub_llm.StubPolicy(close_rate=1.0))
        status, _ = _post(url, {"messages": [{"role": "user", "content": "x"}]})
        self.assertEqual(status, "CLOSED")
        self.assertEqual(self._srv.stats.closed, 1)

    def test_fail_code_records_by_code(self):
        url = self._start(stub_llm.StubPolicy(fail_code=500, fail_rate=1.0))
        status, body = _post(url, {"messages": [{"role": "user", "content": "x"}]})
        self.assertEqual(status, 500)
        self.assertIn("http_500", body)
        self.assertEqual(self._srv.stats.by_code.get("500"), 1)

    def test_token_limit_returns_context_exceeded(self):
        url = self._start(stub_llm.StubPolicy(token_limit=1))
        body_msgs = [{"role": "system", "content": "p"}, {"role": "user", "content": "x"}]
        status, body = _post(url, {"messages": body_msgs})
        self.assertEqual(status, 400)
        self.assertIn("context_length_exceeded", body)

    def test_role_steps_then_close_with_next_stage(self):
        url = self._start(stub_llm.StubPolicy(pm_roles=["developer"]))
        msgs = [
            {"role": "system", "content": "开发角色 developer 当前阶段：understand（understand）"},
            {"role": "user", "content": "完成工单"},
        ]
        tool_seq = []
        rounds = 0
        closed = None
        for _ in range(10):
            status, body = _post(url, {"messages": msgs, "tools": ROLE_TOOLS})
            self.assertEqual(status, 200, body)
            tool, _args, text = _parse(body)
            rounds += 1
            if tool:
                tool_seq.append(tool)
                msgs.append({"role": "assistant",
                             "tool_calls": [{"function": {"name": tool, "arguments": "{}"}}]})
                msgs.append({"role": "tool", "tool_call_id": "c", "content": "ok"})
            else:
                closed = json.loads(text)
                break
        # 工具序列全走完，收口带 understand 的下一态 branch（seed.yaml 里 developer 的
        # 状态链是 understand → branch → implement → verify → ci → merge）。
        self.assertEqual(tool_seq, stub_llm._ROLE_STEPS)
        self.assertEqual(closed["stage"], "branch")
        self.assertGreater(len(closed["reply"]), 0)
        # 发言轮次 = 7 个工具步轮 + 1 次收口轮。
        self.assertEqual(rounds, len(stub_llm._ROLE_STEPS) + 1)

    def test_pm_spawns_roles_in_sequence_then_closes(self):
        url = self._start(stub_llm.StubPolicy(pm_roles=["developer", "tester"]))
        msgs = [
            {"role": "system", "content": "PM 编排会话"},
            {"role": "user", "content": "拆单分派"},
        ]
        spawned = []
        for _ in range(5):
            status, body = _post(url, {"messages": msgs, "tools": PM_TOOLS})
            self.assertEqual(status, 200, body)
            tool, args, text = _parse(body)
            if tool == "role_spawn":
                role = args.get("role")
                spawned.append(role)
                msgs.append({"role": "assistant",
                             "tool_calls": [{"function": {"name": "role_spawn",
                                                          "arguments": json.dumps(args, ensure_ascii=False)}}]})
                msgs.append({"role": "tool", "tool_call_id": "c", "content": "ok"})
            else:
                self.assertGreater(len(text), 0)
                break
        self.assertEqual(spawned, ["developer", "tester"])


if __name__ == "__main__":
    unittest.main()
