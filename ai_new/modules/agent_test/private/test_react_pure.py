"""ReAct 纯函数单测：形状成形、上下文治理、收口解析与摘要兜底。"""
import unittest

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))

from ai_new.modules.agent_common.react.private import _pure


class SchemaTest(unittest.TestCase):
    def test_list_type_becomes_array_with_items(self):
        got = _pure.schema({"name": "demo.echo", "desc": "回声", "tool": [
            {"name": "items", "type": "list", "desc": "清单", "required": True},
            {"name": "msg"},
        ]})
        self.assertEqual(got["type"], "function")
        fn = got["function"]
        self.assertEqual(fn["name"], "demo.echo")
        self.assertEqual(fn["description"], "回声")
        params = fn["parameters"]
        self.assertEqual(params["properties"]["items"]["type"], "array")
        self.assertEqual(params["properties"]["items"]["items"], {"type": "object"})
        self.assertEqual(params["properties"]["msg"]["type"], "string")
        self.assertEqual(params["properties"]["msg"]["description"], "")
        self.assertEqual(params["required"], ["items"])

    def test_no_tools_yields_empty_object(self):
        got = _pure.schema({"name": "x"})
        self.assertEqual(got["function"]["parameters"]["properties"], {})
        self.assertEqual(got["function"]["description"], "")

    def test_schemas_maps_each_tool(self):
        got = _pure.schemas({"tools": [
            {"name": "a.b", "desc": "A", "params": [{"name": "p"}]},
            {"name": "c.d"},
        ]})
        self.assertEqual([x["function"]["name"] for x in got], ["a.b", "c.d"])
        self.assertEqual(got[0]["function"]["parameters"]["required"], [])

    def test_schemas_without_tools(self):
        self.assertEqual(_pure.schemas({}), [])


class MessageShapeTest(unittest.TestCase):
    def test_assistant_minimal(self):
        self.assertEqual(_pure.assistant({}),
                         {"role": "assistant", "content": ""})

    def test_assistant_full(self):
        wire = {"raw": "x"}
        got = _pure.assistant({"content": "hi", "tool_calls": [{"id": "c"}],
                               "at": "t1", "wire": wire})
        self.assertEqual(got["tool_calls"], [{"id": "c"}])
        self.assertEqual(got["at"], "t1")
        self.assertEqual(got["wire"], wire)

    def test_assistant_ignores_empty_wire(self):
        self.assertNotIn("wire", _pure.assistant({"wire": {}}))
        self.assertNotIn("wire", _pure.assistant({"wire": "text"}))

    def test_toolnames_handles_shape_gaps(self):
        got = _pure.toolnames({"tool_calls": [{"function": {"name": "a"}}, {}, {"function": None}]})
        self.assertEqual(got, ["a", None, None])
        self.assertEqual(_pure.toolnames({}), [])

    def test_args_only_dict(self):
        self.assertEqual(_pure.args({"value": {"a": 1}}), {"a": 1})
        self.assertEqual(_pure.args({"value": ["a"]}), {})
        self.assertEqual(_pure.args({}), {})

    def test_toolmsg_defaults_and_stamp(self):
        got = _pure.toolmsg({})
        self.assertEqual(got, {"role": "tool", "tool_call_id": "call_0",
                               "name": "", "content": "{}"})
        self.assertEqual(_pure.toolmsg({"id": "c1", "name": "n", "content": "c", "at": "t"})["at"], "t")

    def test_step_shape(self):
        self.assertEqual(_pure.step({}), {"index": None, "content": "", "tools": []})
        self.assertEqual(_pure.step({"index": 1, "content": "c", "tools": ["a"]})["tools"], ["a"])

    def test_result_empty_messages(self):
        got = _pure.result({})
        self.assertIsNone(got["last"])
        self.assertFalse(got["cancelled"])
        self.assertEqual(got["new_messages"], [])
        self.assertEqual(got["checklist"], [])

    def test_result_with_messages(self):
        got = _pure.result({"messages": [{"role": "user"}], "cancelled": 1, "steps": 3,
                            "stage": "S", "summary_by_model": 1})
        self.assertEqual(got["last"], {"role": "user"})
        self.assertTrue(got["cancelled"])
        self.assertTrue(got["summary_by_model"])
        self.assertEqual(got["steps"], 3)


class ContextTest(unittest.TestCase):
    def test_summary_msg_blank_returns_none(self):
        self.assertIsNone(_pure.summary_msg({}))
        self.assertIsNone(_pure.summary_msg({"summary": "   "}))

    def test_summary_msg_strips(self):
        self.assertEqual(_pure.summary_msg({"summary": " a \n"}),
                         {"role": "assistant", "kind": "summary", "content": "a"})

    def test_context_view_keeps_system_summary_and_last_user(self):
        got = _pure.context_view({"summary": "S", "messages": [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "old"},
            {"role": "assistant", "content": "mid"},
            {"role": "user", "content": "new"},
        ]})["messages"]
        self.assertEqual([m.get("content") for m in got], ["sys", "S", "new"])

    def test_context_view_without_user_or_summary(self):
        got = _pure.context_view({"messages": [{"role": "assistant", "content": "a"}]})
        self.assertEqual(got["messages"], [])

    def test_checkpoint_overlays_fields(self):
        got = _pure.checkpoint({"rec": {"id": "s"}, "messages": [{"role": "user"}],
                                "summary": "S", "steps": 2, "now": "t"})
        self.assertEqual(got["messages"], [{"role": "user"}])
        self.assertEqual(got["summary"], "S")
        self.assertEqual(got["steps"], 2)
        self.assertEqual(got["updated"], "t")

    def test_checkpoint_keeps_record_when_nothing_given(self):
        got = _pure.checkpoint({"rec": {"id": "s", "summary": "old"}})
        self.assertEqual(got, {"id": "s", "summary": "old"})

    def test_checkpoint_none_summary_kept(self):
        got = _pure.checkpoint({"rec": {"summary": "old"}, "summary": None, "steps": 0})
        self.assertEqual(got["summary"], "old")
        self.assertEqual(got["steps"], 0)

    def test_checkpoint_copies_input_list(self):
        src = [{"role": "user"}]
        got = _pure.checkpoint({"messages": src})
        got["messages"].append({"role": "x"})
        self.assertEqual(len(src), 1)

    def test_attach_protocol_without_protocol(self):
        msgs = [{"role": "system", "content": "sys"}]
        self.assertEqual(_pure.attach_protocol({"messages": msgs}), {"messages": msgs})

    def test_attach_protocol_appends_to_first_system(self):
        got = _pure.attach_protocol({"protocol": " P ",
                                     "messages": [{"role": "user", "content": "u"},
                                                  {"role": "system", "content": "sys "}]})["messages"]
        self.assertEqual(got[0], {"role": "user", "content": "u"})
        self.assertEqual(got[1]["content"], "sys\n\nP")

    def test_attach_protocol_without_system(self):
        got = _pure.attach_protocol({"protocol": "P", "messages": [{"role": "user"}]})["messages"]
        self.assertEqual([m.get("content") for m in got], [None])


class ClassifyTest(unittest.TestCase):
    def test_below_threshold(self):
        self.assertEqual(_pure.classify_tool({"content": "abc", "threshold": 5}),
                         {"large": False, "size": 3, "threshold": 5})

    def test_above_threshold(self):
        self.assertTrue(_pure.classify_tool({"content": "abcdef", "threshold": 5})["large"])

    def test_missing_content(self):
        self.assertEqual(_pure.classify_tool({"threshold": 0}),
                         {"large": False, "size": 0, "threshold": 0})


class StripFenceTest(unittest.TestCase):
    def test_plain_text(self):
        self.assertEqual(_pure.strip_fence({"text": " hi "}), {"text": "hi"})

    def test_multiline_with_language(self):
        got = _pure.strip_fence({"text": "```json\n{\"a\":1}\n```"})
        self.assertEqual(got, {"text": "{\"a\":1}"})

    def test_multiline_without_closing_fence(self):
        # 首行恒被当作语言标签剥掉（json/yaml 都是单行标签），无闭合围栏时剩余首行即正文
        self.assertEqual(_pure.strip_fence({"text": "```\nline1\nline2"})["text"], "line2")

    def test_single_line_with_content(self):
        self.assertEqual(_pure.strip_fence({"text": "```json {\"a\":1}"})["text"], "{\"a\":1}")

    def test_single_line_language_only(self):
        self.assertEqual(_pure.strip_fence({"text": "```json"})["text"], "json")

    def test_single_line_empty_body(self):
        self.assertEqual(_pure.strip_fence({"text": "```"})["text"], "")


class ExtractJsonTest(unittest.TestCase):
    def test_trims_surrounding_prose(self):
        self.assertEqual(_pure.extract_json({"text": "说明 {\"a\":1} 尾巴"})["text"], "{\"a\":1}")

    def test_no_braces(self):
        self.assertEqual(_pure.extract_json({"text": "纯文本"})["text"], "纯文本")

    def test_reversed_braces_kept(self):
        self.assertEqual(_pure.extract_json({"text": "} {"})["text"], "} {")

    def test_single_brace_kept(self):
        self.assertEqual(_pure.extract_json({"text": "{"})["text"], "{")


class ParseFinalTest(unittest.TestCase):
    def test_structured_reply(self):
        got = _pure.parse_final({"content": "raw", "obj": {
            "reply": "答", "summary": "摘", "stage": "S",
            "checklist": [" a ", 1, ""], "violations": "x，y ,"}})
        self.assertTrue(got["structured"])
        self.assertEqual(got["reply"], "答")
        self.assertEqual(got["summary"], "摘")
        self.assertEqual(got["stage"], "S")
        self.assertEqual(got["checklist"], ["a", "1"])
        self.assertEqual(got["violations"], ["x", "y"])

    def test_structured_tuple_list_and_bad_list(self):
        got = _pure.parse_final({"obj": {"summary": "s", "checklist": ("a", "b"),
                                         "violations": {"k": 1}}})
        self.assertEqual(got["checklist"], ["a", "b"])
        self.assertEqual(got["violations"], [])

    def test_structured_none_values(self):
        got = _pure.parse_final({"obj": {"stage": "S", "reply": None, "summary": None}})
        self.assertEqual(got["reply"], "")
        self.assertEqual(got["summary"], "")

    def test_unstructured_falls_back_to_content(self):
        got = _pure.parse_final({"content": "原文", "obj": {"other": 1}})
        self.assertEqual(got, {"structured": False, "reply": "原文", "summary": "",
                               "stage": "", "checklist": [], "violations": []})

    def test_obj_not_dict(self):
        self.assertFalse(_pure.parse_final({"content": "x", "obj": ["a"]})["structured"])

    def test_textify_non_str(self):
        self.assertEqual(_pure.parse_final({"obj": {"summary": 12}})["summary"], "12")


class SummarizeTest(unittest.TestCase):
    def test_by_model_passthrough(self):
        self.assertEqual(_pure.summarize({"summary": " s ", "by_model": True}),
                         {"summary": "s", "fallback": False})

    def test_no_turns_returns_base(self):
        self.assertEqual(_pure.summarize({"summary": "s", "messages": []}),
                         {"summary": "s", "fallback": False})

    def test_fallback_compresses_turns(self):
        got = _pure.summarize({"title": "T", "messages": [
            {"role": "assistant", "tool_calls": [
                {"function": {"name": "a.b", "arguments": "{}"}}, {}, {"function": None}]},
            {"role": "tool", "content": "line1\nline2"},
            {"role": "user", "content": "ignored"},
            None,
        ]})
        self.assertTrue(got["fallback"])
        self.assertIn("T", got["summary"])
        self.assertIn("a.b({})", got["summary"])
        self.assertIn("?()", got["summary"])
        self.assertIn("line1 line2", got["summary"])

    def test_base_merged_then_truncated(self):
        got = _pure.summarize({"summary": "旧摘要", "by_model": False, "chars": 6,
                               "messages": [{"role": "tool", "content": "结果"}]})
        self.assertEqual(got["summary"], "旧摘要\n\n-…")
        self.assertTrue(got["fallback"])


if __name__ == "__main__":
    unittest.main()


class CheckpointKeepAppendedTest(unittest.TestCase):
    """轮内检查点：把「快照之后人插进来的发言」接住，不整段抹掉。"""

    def _base(self):
        return [{"role": "system", "content": "s"}, {"role": "user", "content": "开工"}]

    def test_no_latest_keeps_messages(self):
        base = self._base()
        got = _pure.checkpoint({"rec": {"messages": base}, "messages": base})
        self.assertEqual(got["messages"], base)

    def test_appended_message_is_kept(self):
        base = self._base()
        run = base + [{"role": "assistant", "content": "做完"}]
        latest = {"messages": base + [{"role": "user", "content": "再补一句"}]}
        got = _pure.checkpoint({"rec": {"messages": base}, "messages": run, "latest": latest})
        self.assertEqual(got["messages"][-2:], [{"role": "assistant", "content": "做完"},
                                                {"role": "user", "content": "再补一句"}])

    def test_own_checkpoint_message_not_duplicated(self):
        base = self._base()
        run = base + [{"role": "assistant", "content": "做完"}]
        latest = {"messages": base + [{"role": "assistant", "content": "做完"}]}
        got = _pure.checkpoint({"rec": {"messages": base}, "messages": run, "latest": latest})
        self.assertEqual(len(got["messages"]), 3)

    def test_tail_dropped_by_rebuild_is_restored(self):
        base = self._base() + [{"role": "user", "content": "插话"}]
        run = self._base() + [{"role": "assistant", "content": "做完"}]
        got = _pure.checkpoint({"rec": {"messages": base}, "messages": run})
        self.assertEqual(got["messages"][-2:], [{"role": "user", "content": "插话"},
                                                {"role": "assistant", "content": "做完"}])

    def test_shorter_latest_keeps_messages(self):
        base = self._base()
        run = base + [{"role": "assistant", "content": "做完"}]
        got = _pure.checkpoint({"rec": {"messages": base}, "messages": run,
                                "latest": {"messages": base[:1]}})
        self.assertEqual(got["messages"], run)
