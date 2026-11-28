"""项目秘书路由：守卫、入队、批量 flush、幂等态、撤回、定时器代理。"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))

from ai_new.modules.agent import secretary as sm  # noqa: E402
from ai_new.modules.agent.secretary.private import _pure  # noqa: E402
from ai_new.modules.agent_common.tools.private import _registry  # noqa: E402


class ApiError(Exception):
    def __init__(self, msg, code="", status=400):
        super().__init__(msg)
        self.code = code
        self.status = status


class Api:
    def __init__(self):
        self.routes = {}
        self.calls = []
        self.registered = {}

    def call(self, route, payload, caller=None):
        self.calls.append((route, payload))
        fn = self.routes.get(route)
        if isinstance(fn, Exception):
            raise fn
        if callable(fn):
            return fn(payload)
        return fn if fn is not None else {}

    def register(self, route, fn, desc="", module=None):
        self.registered[route] = fn


class Engine:
    def __init__(self):
        self.result = {"ok": True, "result": {"id": "T1"}}
        self.calls = []

    def run_callable(self, name, payload):
        self.calls.append((name, payload))
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


class Hooks:
    """秘书触发点的轻量替身：只记录声明与投递，不跑需求层。"""

    def __init__(self):
        self.points = []
        self.emitted = []

    def point(self, name, params=(), defer=False):
        self.points.append((name, tuple(params), bool(defer)))
        return name

    def emit(self, name, payload=None, level="info"):
        self.emitted.append((name, payload or {}))
        return [{"hook": name, "ok": True, "deferred": True}]


class Ctx:
    ApiError = ApiError

    def __init__(self):
        self.api = Api()
        self.demand_engine = Engine()
        self.tools = _registry.ToolRegistry(self)
        self.hooks = Hooks()


TPL = {
    "missing_project": "缺项目", "project_archived": "已归档",
    "msg_id_missing": "缺 id", "empty_text": "空文本",
    "fallback_title": "默认标题", "fallback_goal": "默认目标",
    "invalid_state": "状态非法", "not_found": "找不到 {id}",
    "chat_merge_failed": "失败 {error}", "chat_merged": "并入 {n}",
    "chat_ticket": "工单 {ticket}", "chat_goal": "目标 {goal}",
    "member_me": "我", "member_secretary": "秘书",
    "tool_timer_create_desc": "建", "tool_timer_list_desc": "列",
    "tool_timer_pause_desc": "停", "tool_timer_resume_desc": "启",
    "tool_timer_delete_desc": "删",
}


def make_ctx(project=None, state=None, claimed=None):
    ctx = Ctx()
    project = project or {"archived": False, "exists": True, "overrides": {"roles": ["pm"]}}
    state = state or {"project": "P", "messages": [], "batches": []}
    claim = {"claimed": True} if claimed is None else claimed
    ctx.api.routes.update({
        "store.read": lambda p: (
            {"value": TPL} if p.get("module") == "agent/secretary" and p.get("path") == "messages.yaml"
            else {"value": state} if p.get("module") == "agent/secretary"
            else {"value": project}),
        "config.get": lambda p: {"value": {"record": "projects/{project}/queue.yaml",
                                            "project_record": "projects/{project}.yaml"}
                                 if p.get("key") == "secretary.paths" else
                                 {"project_record": "projects/{project}.yaml"}},
        "clock.now": lambda p: {"ts": 100.0},
        "store.next_seq": lambda p: {"seq": 2},
        "codec.digest": lambda p: {"hex": "abc"},
        "store.claim": lambda p: claim,
        "store.settle": lambda p: {"ok": True},
        "timer.list": lambda p: {"items": [{"id": "t"}]},
        "timer.create": lambda p: {"ok": True, "id": "t"},
    })
    return ctx


class PureGapsTest(unittest.TestCase):
    def test_mark_without_batch(self):
        state = {"messages": [{"msg_id": "m", "status": "processing", "batch_id": "B"},
                               {"msg_id": "n", "status": "merged", "batch_id": "X"}],
                 "batches": []}
        _pure.mark_merged({"state": state, "batch_id": "B", "ticket": "T"})
        self.assertEqual(state["messages"][0]["status"], "merged")
        state["messages"][0]["status"] = "processing"
        _pure.mark_failed({"state": state, "batch_id": "B", "error": "e"})
        self.assertEqual(state["messages"][0]["status"], "pending")
    def test_enqueue_errors_and_merge_discard(self):
        state = {"messages": [], "batches": []}
        self.assertEqual(_pure.enqueue({"state": state})["code"], "msg_id_missing")
        self.assertEqual(_pure.enqueue({"state": state, "msg_id": "m"})["code"], "empty_text")
        merged = _pure.merge({"entries": [
            {"msg_id": "a", "status": "discarded", "at": 1},
            {"msg_id": "b", "fields": {"goal": " g "}, "at": 2}]})
        self.assertEqual(merged["discarded"], ["a"])
        self.assertEqual(merged["brief"]["goal"], "g")

    def test_discard_terminal_and_missing(self):
        state = {"messages": [{"msg_id": "m", "status": "merged"}], "batches": []}
        self.assertEqual(_pure.discard({"state": state, "msg_id": "none"})["code"], "not_found")
        self.assertEqual(_pure.discard({"state": state, "msg_id": "m"})["code"], "invalid_state")


class GuardAndPushTest(unittest.TestCase):
    def test_project_state_empty_and_missing(self):
        ctx = make_ctx()
        self.assertEqual(sm._project_state(ctx, " "),
                         {"archived": False, "exists": False, "roles": []})
        ctx.api.routes["store.read"] = lambda p: {"value": None}
        out = sm._route_push(ctx, {"project": "P", "text": "x"})
        self.assertEqual(out["code"], "missing_project")
        self.assertEqual(out["status"], 404)

    def test_empty_project_guard(self):
        ctx = make_ctx()
        out = sm._route_push(ctx, {"project": "", "text": "x"})
        self.assertEqual(out["code"], "missing_project")
        self.assertEqual(out["status"], 400)
        self.assertEqual(sm._assemble_goal({}, TPL), "默认目标")

    def test_archived_guard(self):
        ctx = make_ctx(project={"archived": True, "exists": True, "overrides": {}})
        for route in (sm._route_push, sm._route_flush, sm._route_discard):
            out = route(ctx, {"project": "P", "msg_id": "m", "text": "x"})
            self.assertEqual(out["code"], "project_archived")
            self.assertEqual(out["status"], 409)

    def test_push_auto_id_duplicate_and_errors(self):
        ctx = make_ctx()
        out = sm._route_push(ctx, {"project": "P", "text": "x"})
        self.assertTrue(out["created"])
        self.assertEqual(out["entry"]["msg_id"], "m-0002")
        # 模块只回写队列；触发由 secretary-intake 在写盘之后调 hooks.emit
        self.assertEqual([e["kind"] for e in out["effects"]], ["write"])
        out = sm._route_push(ctx, {"project": "P", "text": "y", "msg_id": "m-1"})
        self.assertEqual(out["entry"]["msg_id"], "m-1")
        out = sm._route_push(ctx, {"project": "P", "text": "", "msg_id": "m-2"})
        self.assertEqual(out["code"], "empty_text")
        out = sm._route_push(ctx, {"project": "P", "text": "z"})
        self.assertTrue(out["ok"])

    def test_flush_empty(self):
        ctx = make_ctx()
        out = sm._route_flush(ctx, {"project": "P"})
        self.assertTrue(out["empty"])
        self.assertEqual(out["effects"], [])

    def _state_with_msg(self):
        return {"project": "P", "messages": [{"msg_id": "m", "text": "要做 X",
                                               "status": "pending", "at": 1,
                                               "batch_id": "", "fields": {}}],
                "batches": []}

    def test_flush_success_and_error_paths(self):
        state = self._state_with_msg()
        ctx = make_ctx(state=state)
        out = sm._route_flush(ctx, {"project": "P"})
        self.assertTrue(out["ok"])
        self.assertEqual(out["ticket"], "T1")
        self.assertTrue(out["batch"])
        self.assertTrue(any(c[0] == "store.settle" and c[1]["status"] == "done"
                            for c in ctx.api.calls))
        state["messages"][0]["status"] = "pending"
        ctx.demand_engine.result = RuntimeError("boom")
        out = sm._route_flush(ctx, {"project": "P"})
        self.assertEqual(out["code"], "flush_failed")
        self.assertEqual(state["messages"][0]["status"], "pending")
        state["messages"][0]["status"] = "pending"
        ctx.demand_engine.result = {"ok": False, "failed": {"code": "bad", "error": "坏"}}
        out = sm._route_flush(ctx, {"project": "P"})
        self.assertEqual(out["code"], "flush_failed")
        state["messages"][0]["status"] = "pending"
        ctx.demand_engine.result = {"ok": True, "result": {}}
        out = sm._route_flush(ctx, {"project": "P"})
        self.assertEqual(out["error"], "建单回包缺工单号")

    def test_flush_claim_states(self):
        for status, expected in (("done", "reused"), ("abandoned", "idem_abandoned"),
                                  ("running", "idem_in_flight")):
            ctx = make_ctx(state=self._state_with_msg())
            ctx.api.routes["store.claim"] = lambda p, s=status: {
                "claimed": False, "status": s, "result_digest": "T9"}
            out = sm._route_flush(ctx, {"project": "P"})
            if expected == "reused":
                self.assertTrue(out["reused"])
                self.assertEqual(out["ticket"], "T9")
            else:
                self.assertEqual(out["code"], expected)

    def test_flush_goal_fields(self):
        state = {"project": "P", "messages": [{
            "msg_id": "m", "text": "原文", "status": "pending", "at": 1,
            "fields": {"background": "背景", "acceptance": "验收",
                       "constraints": "约束", "priority": "高"}}], "batches": []}
        ctx = make_ctx(state=state)
        sm._route_flush(ctx, {"project": "P"})
        payload = ctx.demand_engine.calls[0][1]
        self.assertEqual(payload["goal"].split("\n"),
                         ["背景", "原文", "验收", "约束", "高"])

    def test_list_events_and_error(self):
        ctx = make_ctx(state={"project": "P", "messages": [
            {"msg_id": "m", "text": "x", "status": "pending", "at": 1}],
            "batches": [{"batch_id": "B", "claimed_at": 2, "msg_ids": ["m"],
                         "ticket": "T", "brief": {"goal": "G"}, "error": ""},
                        {"batch_id": "B2", "claimed_at": 3, "msg_ids": [],
                         "ticket": "", "brief": {}}]})
        out = sm._route_list(ctx, {"project": "P"})
        self.assertIn("messages", out)
        self.assertTrue(any(m["role"] == "secretary" for m in out["messages"]))
        ctx.api.routes["store.read"] = RuntimeError("boom")
        out = sm._route_list(ctx, {"project": "P"})
        self.assertEqual(out["code"], "state_unavailable")
        out = sm._route_list(ctx, {})
        self.assertEqual(out["code"], "missing_project")

    def test_timers(self):
        ctx = make_ctx()
        self.assertEqual(sm._route_timers(ctx, {})["code"], "missing_project")
        self.assertEqual(sm._route_timers(ctx, {"project": "P"})["items"], [{"id": "t"}])
        ctx.api.routes["timer.list"] = ApiError("denied", code="forbidden")
        out = sm._route_timers(ctx, {"project": "P"})
        self.assertFalse(out["ok"])
        self.assertEqual(out["code"], "forbidden")

    def test_discard(self):
        state = self._state_with_msg()
        ctx = make_ctx(state=state)
        out = sm._route_discard(ctx, {"project": "P", "msg_id": "m"})
        self.assertTrue(out["ok"])
        out = sm._route_discard(ctx, {"project": "P", "msg_id": "none"})
        self.assertEqual(out["code"], "not_found")
        self.assertIn("找不到", out["error"])
        state["messages"][0]["status"] = "merged"
        out = sm._route_discard(ctx, {"project": "P", "msg_id": "m"})
        self.assertEqual(out["code"], "invalid_state")
        self.assertEqual(out["error"], "状态非法")

    def test_status_missing_and_exception(self):
        ctx = make_ctx()
        self.assertEqual(sm._route_status(ctx, {})["code"], "missing_project")
        ctx.api.routes["store.read"] = RuntimeError("boom")
        out = sm._route_status(ctx, {"project": "P"})
        self.assertEqual(out["code"], "state_unavailable")


class ToolsTest(unittest.TestCase):
    def test_timer_tool_and_registration(self):
        ctx = make_ctx()
        fn = sm._timer_tool("timer.create")
        out = fn(ctx, {"kind": "cron"}, {"ticket": "T", "project": "P", "id": "S",
                                          "role": "pm", "kind": "role"})
        self.assertEqual(out, {"ok": True, "id": "t"})
        payload = ctx.api.calls[-1][1]
        self.assertEqual(payload["project"], "P")
        self.assertEqual(payload["kind"], "cron")
        self.assertEqual(payload["caller"]["scope"], "ticket")

        ctx2 = make_ctx()
        ctx2.tools = None
        sm._register_timer_tools(ctx2)
        ctx3 = make_ctx()
        ctx3.tools.register("timer_list", "x", [], None)
        sm._register_timer_tools(ctx3)
        self.assertEqual(ctx3.tools._tools["timer_list"]["desc"], "x")
        sm.setup(ctx3)
        self.assertIn("secretary.push", ctx3.api.registered)
        self.assertTrue(ctx3.tools.has("timer_create"))


if __name__ == "__main__":
    unittest.main()
