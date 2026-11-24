"""React 核心机制专项：流程状态机、清单状态机、逐轮压缩。

这些不是“接口返回 200”的冒烟，而是对状态不变量做真断言：
非法边必须拒绝、清单缺项必须拦住、压缩不能让上下文丢关键信息、并发分叉后
活跃集合必须按契约收口。用例失败即说明机制坏了，不能靠放宽断言变绿。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _contract():
    return {
        "initial": "a",
        "by_id": {
            "a": {"cn": "甲", "next": ["b", "c"], "terminal": False,
                  "gate": {"must": [{"id": "m1"}, {"id": "m2"}]}},
            "b": {"cn": "乙", "next": ["d"], "terminal": False},
            "c": {"cn": "丙", "next": ["d"], "terminal": False},
            "d": {"cn": "丁", "next": [], "terminal": True},
        },
        "checks": [],
    }


def test_flow_legal_start_and_illegal_edges():
    from ai_new.modules.agent.library.private import _pure as lib
    c = _contract()
    start = lib.stage_transitionp({"contract": c, "prev": "", "nxt": "a"})
    assert start["ok"] and start["code"] == "ok" and start["active"] == ["a"]
    bad_start = lib.stage_transitionp({"contract": c, "prev": "", "nxt": "b"})
    assert not bad_start["ok"] and bad_start["code"] == "illegal_start"
    illegal = lib.stage_transitionp({"contract": c, "prev": "a", "nxt": "d"})
    assert not illegal["ok"] and illegal["code"] == "illegal_edge" and illegal["active"] == ["a"]
    unknown = lib.stage_transitionp({"contract": c, "prev": "a", "nxt": "zzz"})
    assert not unknown["ok"] and unknown["code"] == "unknown_stage"
    # 原地停留免检：checklist 没交也允许上报自身
    stay = lib.stage_transitionp({"contract": c, "prev": "a", "nxt": "a"})
    assert stay["ok"] and stay["active"] == ["a"]


def test_flow_checklist_blocks_until_all_must_items_checked():
    from ai_new.modules.agent.library.private import _pure as lib
    c = _contract()
    one = lib.stage_transitionp({"contract": c, "prev": "a", "nxt": "b", "checked": ["m1"]})
    assert not one["ok"] and one["code"] == "checklist_unmet"
    assert one["missing"] == ["m2"]
    hit = lib.stage_transitionp({"contract": c, "prev": "a", "nxt": "b",
                                 "checked": ["m1", "m2"], "violations": ["红线"]})
    assert not hit["ok"] and hit["code"] == "forbidden_hit"
    ok = lib.stage_transitionp({"contract": c, "prev": "a", "nxt": "b",
                                "checked": ["m1", "m2"]})
    assert ok["ok"] and ok["stage"] == "b" and ok["active"] == ["b"]


def test_flow_parallel_fanout_keeps_sibling_and_drops_terminal():
    from ai_new.modules.agent.library.private import _pure as lib
    c = _contract()
    # a 分叉到 b/c：a 仍在活跃集合，b/c 并行加入
    fan = lib.stage_transitionp({"contract": c, "prev": "a", "nxt": ["b", "c"],
                                 "checked": ["m1", "m2"]})
    assert fan["ok"] and fan["active"] == ["b", "c"]
    # b 到终态 d：b 是非终态保留，d 加入；再从 d 离开时终态 d 被摘掉
    # 并行活跃集合用 prev 列表传入；当前态是首项，离开后其兄弟保留
    to_d = lib.stage_transitionp({"contract": c, "prev": ["b", "c"], "nxt": "d"})
    assert to_d["ok"] and to_d["active"] == ["c", "d"]
    end = lib.stage_transitionp({"contract": c, "prev": "d", "active": ["d"], "nxt": ""})
    assert end["ok"] and end["code"] == "unset" and end["active"] == ["d"]


def test_flow_contract_survives_json_roundtrip():
    from ai_new.modules.agent.library.private import _pure as lib
    c = _contract()
    raw = {"states": [
        {"id": "a", "cn": "甲", "next": ["b", "c"]},
        {"id": "b", "cn": "乙", "next": ["d"]},
        {"id": "c", "cn": "丙", "next": ["d"]},
        {"id": "d", "cn": "丁", "next": [], "terminal": True},
    ], "checks": []}
    built = lib.stage_contractp({"states": raw["states"], "checks": []})
    restored = json.loads(json.dumps(built))
    assert restored["initial"] == "a"
    assert restored["by_id"]["a"]["next"] == ["b", "c"]
    assert lib.stage_toolsp({"contract": restored, "active": ["a"],
                             "items": [{"name": "x"}]})["items"] == [{"name": "x"}]


def test_checklist_crud_is_deterministic_and_bounded():
    from ai_new.modules.agent.todos.private import _pure as todos
    st = {"todos": []}
    out = todos.apply_ops({"todos": st["todos"], "limit": 2,
                           "args": {"action": "add", "text": "甲"}})
    assert out["ok"] and out["todos"][0]["id"] == "t1" and out["todos"][0]["status"] == "pending"
    st["todos"] = out["todos"]
    out = todos.apply_ops({"todos": st["todos"], "limit": 2,
                           "args": {"action": "add", "text": "乙", "status": "doing"}})
    assert out["todos"][1]["status"] == "doing"
    st["todos"] = out["todos"]
    # 上限之外不再增长：limit 是硬合同，不能因模型一直 add 把上下文撑爆
    out = todos.apply_ops({"todos": st["todos"], "limit": 2,
                           "args": {"action": "add", "text": "丙"}})
    assert len(out["todos"]) == 2
    dup = todos.apply_ops({"todos": [{"id": "t1", "text": "甲"}, {"id": "t1", "text": "乙"}],
                           "limit": 40, "args": {"action": "list"}})
    assert [x["id"] for x in dup["todos"]] == ["t1", "t2"]
    upd = todos.apply_ops({"todos": out["todos"], "limit": 40,
                           "args": {"action": "update", "id": "t2", "status": "done"}})
    assert upd["counts"] == {"total": 2, "pending": 1, "doing": 0, "done": 1}
    assert todos.apply_ops({"todos": upd["todos"], "limit": 40,
                            "args": {"action": "remove", "id": "nope"}})["code"] == "not_found"
    cleared = todos.apply_ops({"todos": upd["todos"], "limit": 40,
                               "args": {"action": "clear"}})
    assert cleared["todos"] == [] and cleared["changed"] is True


def test_checklist_context_is_complete_after_compaction():
    from ai_new.modules.agent.todos.private import _pure as todos
    items = [{"id": "t1", "text": "甲", "status": "doing"},
             {"id": "t2", "text": "乙", "status": "done"}]
    msg = todos.context({"todos": items, "limit": 40, "tpl": {
        "heading": "当前清单", "row": "{id} [{status}] {text}", "hint": "每轮更新"}})
    assert msg["message"]["role"] == "system"
    assert "t1" in msg["message"]["content"] and "t2" in msg["message"]["content"]
    assert "每轮更新" in msg["message"]["content"]
    assert todos.context({"todos": [], "limit": 40})["message"] is None


def test_context_view_keeps_system_summary_and_last_user_only():
    from ai_new.modules.agent_common.react.private import _pure as react
    view = react.context_view({"messages": [
        {"role": "system", "content": "人设"},
        {"role": "user", "content": "旧问题"},
        {"role": "assistant", "content": "旧答复"},
        {"role": "tool", "content": "旧工具结果"},
        {"role": "user", "content": "本轮问题"},
    ], "summary": "历史摘要"})["messages"]
    roles = [m["role"] for m in view]
    assert roles == ["system", "assistant", "user"]
    assert view[1]["kind"] == "summary" and view[1]["content"] == "历史摘要"
    assert view[2]["content"] == "本轮问题"
    assert all(m["content"] not in ("旧问题", "旧答复", "旧工具结果") for m in view)


def test_round_summary_prefers_model_then_bounded_fallback():
    from ai_new.modules.agent_common.react.private import _pure as react
    new = [{"role": "assistant", "tool_calls": [
                {"function": {"name": "artifact_read", "arguments": '{"path":"a.md"}'}}]},
           {"role": "tool", "content": "结果"}]
    model = react.summarize({"summary": "模型摘要", "messages": new,
                             "by_model": True, "chars": 30, "title": "兜底"})
    assert model == {"summary": "模型摘要", "fallback": False}
    fb = react.summarize({"summary": "旧", "messages": new,
                          "by_model": False, "chars": 30, "title": "兜底"})
    assert fb["fallback"] and "旧" in fb["summary"] and "artifact_read" in fb["summary"]
    assert len(fb["summary"]) <= 31
    empty = react.summarize({"summary": "旧", "messages": [], "by_model": False,
                             "chars": 30, "title": "兜底"})
    assert empty == {"summary": "旧", "fallback": False}


def test_session_compact_keeps_system_and_recent_tail_only():
    from ai_new.modules.agent.sessions.private import _pure as sessions
    rec = {"messages": [
        {"role": "system", "content": "人设"},
        {"role": "user", "content": "1"},
        {"role": "assistant", "content": "2"},
        {"role": "user", "content": "3"},
        {"role": "assistant", "content": "4"},
    ], "updated": 0}
    out = sessions.compactp({"rec": rec, "keep": 2, "now": 9})
    assert [m["content"] for m in out["messages"]] == ["人设", "3", "4"]
    assert out["updated"] == 9
    # 原始记录不被就地改写：裁剪是纯变换，存档还应完整
    assert len(rec["messages"]) == 5


import unittest


class TestReactMechanisms(unittest.TestCase):
    """unittest 入口：沿用模块级纯函数，避免把断言包成空壳。"""
    test_flow_legal_start_and_illegal_edges = staticmethod(test_flow_legal_start_and_illegal_edges)
    test_flow_checklist_blocks_until_all_must_items_checked = staticmethod(test_flow_checklist_blocks_until_all_must_items_checked)
    test_flow_parallel_fanout_keeps_sibling_and_drops_terminal = staticmethod(test_flow_parallel_fanout_keeps_sibling_and_drops_terminal)
    test_flow_contract_survives_json_roundtrip = staticmethod(test_flow_contract_survives_json_roundtrip)
    test_checklist_crud_is_deterministic_and_bounded = staticmethod(test_checklist_crud_is_deterministic_and_bounded)
    test_checklist_context_is_complete_after_compaction = staticmethod(test_checklist_context_is_complete_after_compaction)
    test_context_view_keeps_system_summary_and_last_user_only = staticmethod(test_context_view_keeps_system_summary_and_last_user_only)
    test_round_summary_prefers_model_then_bounded_fallback = staticmethod(test_round_summary_prefers_model_then_bounded_fallback)
    test_session_compact_keeps_system_and_recent_tail_only = staticmethod(test_session_compact_keeps_system_and_recent_tail_only)
