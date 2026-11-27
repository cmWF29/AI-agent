"""ReAct 路由单测：装配注册、工具分级落盘、检查点与闭环（模型→工具→收口）。"""
import asyncio
import json
import unittest
from types import SimpleNamespace

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))

from ai_new.modules.agent_common.react import _msg_tpl, _rel_path, _route_run, _stash_tool_output, setup
from ai_new.modules.agent_common.react.private import _pure


class ApiError(Exception):
    def __init__(self, message, code="X"):
        super().__init__(message)
        self.message = message
        self.code = code


class FakeApi:
    def __init__(self, tools=None, store_value=None, applied=None, cfg=None):
        self.tools = tools or {}
        self.tools_calls = []
        self.store_value = {"stash_note": "已落盘 {size} 字：{path}"} if store_value is None else store_value
        self.store_text = "PROTO"
        self.record_effects = []
        self.logs_calls = []
        self.registered = []
        self.clock_broken = False
        self.cfg = {"sessions.react_cap": 2,
                    "sessions.context.tool_output_chars": 100,
                    "logs.paths": {"tool": "projects/{project}/tickets/{ticket}/logs/{fid}.txt"}}
        self.cfg.update(cfg or {})

    def register(self, name, fn, desc=None, module=None):
        self.registered.append(name)

    async def acall(self, name, payload=None, caller=None):
        self.tools_calls.append((name, payload))
        if name == "tools.execute":
            return self.tools[payload["name"]]
        raise AssertionError("unexpected acall %s" % name)

    def call(self, name, payload=None, caller=None):
        p = payload or {}
        if name.startswith("react."):
            return getattr(_pure, name.split(".", 1)[1])(p)
        if name == "store.read":
            return {"value": self.store_value}
        if name == "store.read_text":
            return {"value": self.store_text}
        if name == "config.get":
            return {"value": self.cfg.get(p.get("key"))}
        if name == "clock.now":
            if self.clock_broken:
                raise RuntimeError("clock down")
            return {"ts": "2026-01-01T00:00:00Z"}
        if name == "codec.json_decode":
            try:
                return {"value": json.loads(p.get("text"))}
            except Exception:  # noqa: BLE001
                return {"value": None}
        if name == "codec.json_encode":
            return {"text": json.dumps(p.get("value"), ensure_ascii=False)}
        if name == "logs.record":
            self.logs_calls.append(p)
            return {"effects": self.record_effects}
        raise AssertionError("unexpected api.call %s" % name)


class FakeRuntime:
    def __init__(self, answers, demands=None, applied=None):
        self.answers = list(answers)
        self.demands = list(demands or [])
        self.applied = [{"ok": True}] if applied is None else applied
        self.cancel = False
        self.cleared = []
        self.applies = []
        self.llm_calls = []

    async def acall(self, demand, payload=None):
        if demand == "llm-chat":
            self.llm_calls.append(payload)
            return self.answers.pop(0)
        return self.demands.pop(0)

    def calls_llm(self):
        return self.llm_calls

    def answers_of_llm(self):
        return self.llm_calls

    def cancelled(self, cid, since=None):
        return self.cancel

    def stream_clear(self, cid):
        self.cleared.append(cid)

    def apply(self, payload):
        self.applies.append(payload)
        return {"applied": self.applied}


def make_ctx(answers, demands=None, applied=None, **kw):
    api = FakeApi(**kw)
    runtime = FakeRuntime(answers, demands, applied)
    return SimpleNamespace(api=api, runtime=runtime, ApiError=ApiError), api, runtime


ARCHIVE = [{"role": "system", "content": "sys"}, {"role": "user", "content": "go"}]
TOOL_ANSWER = {"ok": True, "content": "先查", "tool_calls": [
    {"id": "c1", "function": {"name": "demo.echo", "arguments": "{\"a\": 1}"}}]}
FINAL_ANSWER = {"ok": True, "content": "```json\n{\"reply\": \"done\", \"summary\": \"S\", "
                                      "\"stage\": \"S2\", \"checklist\": [\"a\"], "
                                      "\"violations\": \"v1,v2\"}\n```"}


class SetupTest(unittest.TestCase):
    def test_setup_registers_all_names(self):
        ctx, api, _ = make_ctx([])
        self.assertTrue(setup(ctx))
        pure_names = [n for n in api.registered if n.startswith("react.") and n != "react.run"]
        self.assertEqual(len(pure_names), 14)
        self.assertIn("react.run", api.registered)

    def test_msg_tpl_reads_store_and_degrades(self):
        ctx, api, _ = make_ctx([], store_value={"stash_note": "n"})
        self.assertEqual(_msg_tpl(ctx), {"stash_note": "n"})
        ctx2, _, _ = make_ctx([], store_value={})
        self.assertEqual(_msg_tpl(ctx2), {})


class RelPathTest(unittest.TestCase):
    def test_template_with_project(self):
        self.assertEqual(_rel_path("projects/{project}/logs/{fid}.txt", "fb",
                                   project="p1", fid="f1"), "projects/p1/logs/f1.txt")

    def test_template_without_project_drops_segment(self):
        self.assertEqual(_rel_path("projects/{project}/tickets/{ticket}/logs/{fid}.txt", "fb",
                                   project="", ticket="t1", fid="f1"), "tickets/t1/logs/f1.txt")

    def test_collapses_double_slash(self):
        self.assertEqual(_rel_path("a//b//{fid}", "fb", fid="f"), "a/b/f")

    def test_empty_template_or_empty_result_falls_back(self):
        self.assertEqual(_rel_path("", "fb", fid="f"), "fb")
        self.assertEqual(_rel_path("/{fid}/", "fb", fid=""), "fb")


class ToolBudgetDefaultsTest(unittest.TestCase):
    """默认阈值必须容得下派角色/拆单/写文档回执；截断提示不能诱导模型读日志。"""

    def test_default_budget_keeps_control_plane_results_inline(self):
        import yaml
        root = Path(__file__).resolve().parents[4]
        cfg = yaml.safe_load(
            (root / "ai_new/modules/agent_common/config/data/config.default.yaml").read_text())
        self.assertGreaterEqual(cfg["sessions"]["context"]["tool_output_chars"], 20000)

    def test_stash_note_does_not_advertise_artifact_read(self):
        import yaml
        root = Path(__file__).resolve().parents[4]
        tpl = yaml.safe_load(
            (root / "ai_new/modules/agent_common/react/data/messages.yaml").read_text())
        self.assertIn("不能用 artifact_read 读取", tpl["stash_note"])
        self.assertIn("缩小查询范围", tpl["stash_note"])


class StashTest(unittest.TestCase):
    def test_small_output_passes_through(self):
        ctx, _, _ = make_ctx([])
        self.assertEqual(_stash_tool_output(ctx, {}, "c1", "short", 100),
                         {"content": "short", "stashed": False})

    def test_large_output_stashed_with_note(self):
        ctx, api, runtime = make_ctx([])
        api.record_effects = [{"kind": "write_text", "module": "agent/logs"}]
        got = _stash_tool_output(ctx, {"project": "p1", "ticket": "t1"}, "c1",
                                 "x" * 200, 100, "1-1")
        self.assertTrue(got["stashed"])
        self.assertEqual(got["path"], "projects/p1/tickets/t1/logs/c1.txt")
        self.assertEqual(got["size"], 200)
        self.assertIn("200", got["content"])
        self.assertEqual(len(runtime.applies), 1)
        self.assertEqual(runtime.applies[0]["effect"][0]["text"], "x" * 200)

    def test_large_output_without_ids_uses_stamp(self):
        ctx, api, _ = make_ctx([], cfg={"logs.paths": None})
        api.store_value = {"stash_note": None}
        got = _stash_tool_output(ctx, None, None, "y" * 200, 100, "2-1")
        self.assertTrue(got["stashed"])
        self.assertEqual(got["path"], "/out-2-1")
        self.assertEqual(got["content"], "")

    def test_apply_failure_falls_back_to_full_text(self):
        ctx, _, runtime = make_ctx([], applied=[{"ok": False}])
        got = _stash_tool_output(ctx, {}, "c1", "z" * 200, 100)
        self.assertEqual(got, {"content": "z" * 200, "stashed": False, "fallback": "write_failed"})

    def test_apply_returns_none_treated_as_empty(self):
        ctx, _, runtime = make_ctx([])
        runtime.applied = []
        got = _stash_tool_output(ctx, {}, "c1", "q" * 200, 100)
        self.assertTrue(got["stashed"])


class RouteRunTest(unittest.TestCase):
    def test_tool_then_final(self):
        ctx, api, runtime = make_ctx(
            [TOOL_ANSWER, FINAL_ANSWER],
            demands=[{"ok": True, "payload": "y" * 200, "session_patch": {"todo": [1]}}],
            tools={"demo.echo": {"deferred": True, "demand": "demo.echo", "input": {"a": 1}}})
        payload = {"session": {"id": "s1", "summary": "旧"}, "messages": ARCHIVE,
                   "path": "logs/s1.json", "tools": [{"name": "demo.echo", "params": [{"name": "a"}]}],
                   "extra": {"role": "system", "content": " TODO "},
                   "max_steps": 5}
        got = asyncio.run(_route_run(ctx, payload))
        self.assertEqual(got["steps"], 2)
        self.assertEqual(got["summary"], "S")
        self.assertTrue(got["summary_by_model"])
        self.assertEqual(got["stage"], "S2")
        self.assertEqual(got["checklist"], ["a"])
        self.assertEqual(got["violations"], ["v1", "v2"])
        self.assertEqual(len(got["new_messages"]), 3)
        self.assertEqual(got["new_messages"][2]["content"], "done")
        self.assertEqual(got["new_messages"][0]["content"], "先查")
        self.assertEqual(got["new_messages"][1]["role"], "tool")
        self.assertIn("落盘", got["new_messages"][1]["content"])
        # 工具声明的会话补丁并入快照，且不回填给模型
        self.assertEqual(payload["session"]["todo"], [1])
        # 检查点写入：工具步 + 收口步各一次（前面还有装协议后的写）
        self.assertGreaterEqual(len(runtime.applies), 3)
        self.assertEqual(runtime.calls_llm()[0]["tools"][0]["function"]["name"], "demo.echo")
        # 注入的额外注记接在视图尾部且协议已拼进 system
        first = runtime.answers_of_llm()[0]["messages"]
        self.assertEqual(first[0]["content"], "sys\n\nPROTO")
        self.assertEqual(first[-1]["content"], " TODO ")

    def test_answer_not_dict_treated_as_empty(self):
        ctx, api, runtime = make_ctx(["oops"])
        got = asyncio.run(_route_run(ctx, {"max_steps": 1}))
        self.assertEqual(got["steps"], 1)
        self.assertEqual(got["new_messages"][0]["content"], "")

    def test_llm_failure_marks_failed_and_cancelled(self):
        ctx, api, runtime = make_ctx([{"ok": False, "killed": "cancelled", "error": "boom"}])
        got = asyncio.run(_route_run(ctx, {"cancel": {"id": "g1", "since": "t"}}))
        self.assertEqual(got["steps"], 0)
        self.assertTrue(got["cancelled"])
        self.assertEqual(got["failed"]["error"], "boom")
        self.assertEqual(runtime.cleared, ["g1", "g1"])  # 每轮开跑前清一次 + 收尾清一次

    def test_gate_cancelled_before_call(self):
        ctx, api, runtime = make_ctx([])
        runtime.cancel = True
        got = asyncio.run(_route_run(ctx, {"cancel": {"id": "g1"}}))
        self.assertTrue(got["cancelled"])
        self.assertEqual(got["steps"], 0)
        self.assertEqual(runtime.answers, [])
        self.assertEqual(runtime.cleared, ["g1"])

    def test_max_steps_override_stops_after_tool_step(self):
        ctx, api, runtime = make_ctx([TOOL_ANSWER],
                                     demands=[{"ok": True}],
                                     tools={"demo.echo": {"ok": True}})
        got = asyncio.run(_route_run(ctx, {"max_steps": 1, "messages": ARCHIVE}))
        self.assertEqual(got["steps"], 1)
        self.assertEqual(got["summary"], "")
        self.assertEqual(got["stage"], "")

    def test_cap_from_config_when_no_max_steps(self):
        ctx, api, runtime = make_ctx([TOOL_ANSWER, {"ok": True, "content": "fin"}],
                                     demands=[{"ok": True}],
                                     tools={"demo.echo": {"ok": True}})
        got = asyncio.run(_route_run(ctx, {"messages": ARCHIVE}))
        self.assertEqual(got["steps"], 2)  # 配置 cap=2 生效，未传 max_steps

    def test_tool_error_becomes_observation(self):
        ctx, api, runtime = make_ctx([TOOL_ANSWER, {"ok": True, "content": "fin"}],
                                     tools={})
        api.tools["demo.echo"] = None

        async def boom(name, payload=None, caller=None):
            raise ApiError("工具炸了", "E_TOOL")

        api.acall = boom
        got = asyncio.run(_route_run(ctx, {"max_steps": 2, "messages": ARCHIVE}))
        body = json.loads(got["new_messages"][1]["content"])
        self.assertFalse(body["ok"])
        self.assertEqual(body["code"], "E_TOOL")
        self.assertEqual(got["steps"], 2)


class CheckpointTest(unittest.TestCase):
    def test_missing_path_or_session_skips(self):
        ctx, api, runtime = make_ctx([])
        from ai_new.modules.agent_common.react import _checkpoint
        _checkpoint(ctx, {}, "", [], "", 1)
        _checkpoint(ctx, {"id": "s"}, "", [], "", 1)
        self.assertEqual(runtime.applies, [])

    def test_clock_failure_swallowed(self):
        ctx, api, runtime = make_ctx([])
        api.clock_broken = True
        from ai_new.modules.agent_common.react import _checkpoint
        _checkpoint(ctx, {"id": "s"}, "p", [], "", 1)
        self.assertEqual(runtime.applies, [])

    def test_writes_record(self):
        ctx, api, runtime = make_ctx([])
        from ai_new.modules.agent_common.react import _checkpoint
        _checkpoint(ctx, {"id": "s"}, "p", [{"role": "user"}], "S", 2)
        effect = runtime.applies[0]["effect"]
        self.assertEqual(effect["path"], "p")
        self.assertEqual(effect["value"]["id"], "s")
        self.assertEqual(effect["value"]["steps"], 2)


class ThresholdTest(unittest.TestCase):
    def test_payload_wins(self):
        from ai_new.modules.agent_common.react import _tool_threshold
        ctx, api, _ = make_ctx([])
        self.assertEqual(_tool_threshold(ctx, {"tool_output_chars": "50"}), 50)
        self.assertEqual(_tool_threshold(ctx, {}), 100)


if __name__ == "__main__":
    unittest.main()
