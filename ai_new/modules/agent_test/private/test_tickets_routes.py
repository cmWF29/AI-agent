"""工单路由闭环：建、发、备注、拆、结、改挂、停滞扫描全部走真实路由函数。

只替换 I/O 出口（store/config/clock/runtime），纯函数与守卫仍用生产实现，
避免用 mock 把错误分支“演”过去。
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))

from ai_new.modules.agent import tickets  # noqa: E402
from ai_new.modules.agent.tickets.private import _pure  # noqa: E402

PATHS = {
    "record": "projects/{project}/tickets/{id}/ticket.yaml",
    "project_record": "{project}.yaml",
    "glob": "projects/*/tickets/T-*/ticket.yaml",
    "walk_glob": "**/tickets/T-*/ticket.yaml",
    "root": "projects",
}
MSGS = {
    "missing": "缺单", "project_archived": "项目归档", "ticket_closed": "已结单",
    "pm_started": "PM 已启动", "default_title": "默认标题", "ticket_conflict": "冲突 {id}",
    "pm_intro": "工单 {ticket} {title} {goal}", "child_open": "子单 {id} 未结",
    "close_accepted": "通过", "close_rejected": "驳回", "child_split": "拆出 {child}",
    "too_many_children": "超过 {max}", "audit_title": "审计 {id}",
    "audit_goal": "检查 {id}", "child_closed": "子单 {id} 已结",
    "bad_children_list": "子单要列表", "bad_child": "子单形状坏",
    "bad_project_type": "项目类型坏", "bad_text_type": "文本类型坏",
    "bad_text_long": "文本太长", "bad_nonempty": "字段空", "bad_from_to_same": "同值",
}


class ApiError(Exception):
    def __init__(self, message, code="", status=0):
        super().__init__(message)
        self.code = code
        self.status = status


class Runtime:
    def __init__(self):
        self.calls = []
        self.dispatched = []
        self.stopped = []

    def call(self, name, payload):
        self.calls.append((name, payload))
        if name == "session-spawn":
            return {"id": "S-PM"}
        if name == "ticket-create":
            return {"id": "T-CHILD"}
        return {}

    def dispatch(self, payload):
        self.dispatched.append(payload)

    def stop(self, sid):
        self.stopped.append(sid)


class Demand:
    def __init__(self):
        self.calls = []

    def run_callable(self, name, payload):
        self.calls.append((name, payload))


class ToolBox:
    def __init__(self):
        self.rows = []

    def register_demand(self, *args, **kwargs):
        self.rows.append((args, kwargs))


class Ctx:
    """按路由名分发的假 ctx：只在 I/O 出口做表，不绕过业务函数。"""

    ApiError = ApiError

    def __init__(self):
        self.api = self
        self.records = {}
        self.config = {"tickets.paths": PATHS, "tickets.max_children": 2}
        self.messages = dict(MSGS)
        self.runtime = Runtime()
        self.demand_engine = Demand()
        self.tools = ToolBox()
        self.claim = {"claimed": True}
        self.settles = []
        self.calls = []
        self.exists = False
        self.digest = "a" * 64
        self.walk_rows = []
        self.since = 1
        self.reused = None
        self.log_items = []
        self.registrations = []

    def register(self, name, fn, desc=None, module=None):
        self.registrations.append((name, fn, desc, module))

    def call(self, name, payload=None, caller=None):
        payload = payload or {}
        self.calls.append((name, payload))
        if name == "config.get":
            return {"value": self.config.get(payload.get("key"))}
        if name == "store.read":
            key = (payload.get("module"), payload.get("path"))
            if payload.get("module") == "agent/tickets" and payload.get("path") == "messages.yaml":
                return {"value": dict(self.messages)}
            return {"value": self.records.get(key)}
        if name == "store.glob":
            pattern = payload.get("pattern") or ""
            if pattern.startswith("projects/*/tickets/"):
                tid = pattern.split("/")[3]
                items = [k[1] for k, v in self.records.items()
                         if k[0] == "agent/tickets" and "/tickets/%s/" % tid in k[1]]
                return {"items": items}
            if payload.get("module") == "agent/logs":
                return {"items": list(self.log_items)}
            return {"items": []}
        if name == "store.walk":
            return {"rows": self.walk_rows}
        if name == "store.exists":
            return {"exists": self.exists}
        if name == "store.claim":
            return dict(self.claim)
        if name == "store.settle":
            self.settles.append(payload)
            return {}
        if name == "store.next_seq":
            return {"seq": 1}
        if name == "clock.now":
            return {"iso": "2026-11-25T10:00:00", "ts": "T"}
        if name == "clock.since":
            return {"seconds": self.since}
        if name == "codec.digest":
            return {"hex": self.digest}
        if name == "logs.purge":
            return {"effects": [{"kind": "purged"}]}
        if name == "projects.missing":
            return {"ok": False, "code": "project_missing"}
        if name == "ops.assemble":
            return {"scan": payload.get("parts", {}).get("scan", []), "effects": []}
        if name.startswith("tickets."):
            fn = getattr(_pure, name.split(".", 1)[1], None)
            if fn is None:
                return {"ok": True}
            return fn(payload)
        raise AssertionError("unexpected route %s" % name)


def ticket(status="open", **kw):
    rec = {"id": "T-1", "project": "P", "status": status, "pm": "S-PM",
           "roles": [], "history": [], "children": [], "title": "标题"}
    rec.update(kw)
    return rec


class LookupTest(unittest.TestCase):
    def setUp(self):
        tickets._TICKET_PROJECT.clear()
        self.ctx = Ctx()

    def test_lookup_ambiguous_owner_and_missing(self):
        self.ctx.records[("agent/tickets", "projects/A/tickets/T-1/ticket.yaml")] = {}
        self.ctx.records[("agent/tickets", "projects/B/tickets/T-1/ticket.yaml")] = {}
        with self.assertRaises(ApiError) as err:
            tickets._lookup_project(self.ctx, "T-1")
        self.assertEqual(err.exception.code, "ticket_ambiguous")
        self.assertEqual(tickets._lookup_project(self.ctx, "none"), "")
        self.assertEqual(tickets._lookup_project(self.ctx, ""), "")
        self.assertEqual(tickets._ticket_path(self.ctx, "T-1", "P"),
                         "projects/P/tickets/T-1/ticket.yaml")

    def test_project_state_blank_and_values(self):
        self.assertEqual(tickets._project_state(self.ctx, ""),
                         {"archived": False, "roles": [], "exists": False})
        self.ctx.records[("agent/projects", "P.yaml")] = {
            "archived": True, "overrides": {"roles": ["pm", 2]}}
        self.assertEqual(tickets._project_state(self.ctx, "P"),
                         {"archived": True, "roles": ["pm", "2"], "exists": True})


class SendNoteTest(unittest.TestCase):
    def setUp(self):
        tickets._TICKET_PROJECT.clear()
        self.ctx = Ctx()
        self.path = "projects/P/tickets/T-1/ticket.yaml"

    def test_send_error_paths_and_success(self):
        self.assertEqual(tickets._route_send(self.ctx, {"id": "T-1", "text": "x"})["code"],
                         "not_found")
        self.ctx.records[("agent/tickets", self.path)] = ticket(status="closed")
        self.assertEqual(tickets._route_send(self.ctx, {"id": "T-1", "text": "x"})["code"],
                         "ticket_closed")
        self.ctx.records[("agent/tickets", self.path)] = ticket()
        self.ctx.records[("agent/projects", "P.yaml")] = {"archived": True}
        self.assertEqual(tickets._route_send(self.ctx, {"id": "T-1", "text": "x"})["code"],
                         "project_archived")
        self.ctx.records[("agent/projects", "P.yaml")] = {}
        self.ctx.records[("agent/tickets", self.path)] = ticket(pm="")
        self.assertEqual(tickets._route_send(self.ctx, {"id": "T-1", "text": "x"})["code"],
                         "no_session")
        self.ctx.records[("agent/tickets", self.path)] = ticket()
        out = tickets._route_send(self.ctx, {"id": "T-1", "text": " hi ", "target": "pm"})
        self.assertEqual(out["id"], "T-1")
        self.assertEqual(self.ctx.demand_engine.calls[0][0], "session-send")
        self.assertEqual(self.ctx.runtime.dispatched[0]["key"], "S-PM")
        self.assertEqual(tickets._route_send(self.ctx, {"id": "T-1", "text": ""})["code"],
                         "empty_text")
        self.assertEqual(tickets._route_send(self.ctx, {"id": "T-1", "text": 1})["code"],
                         "bad_input")

    def test_note_write_errors_and_success(self):
        self.assertEqual(tickets._route_note_write(self.ctx, {"id": "T-1", "text": "x"})["code"],
                         "not_found")
        self.ctx.records[("agent/tickets", self.path)] = ticket(status="closed")
        self.assertEqual(tickets._route_note_write(self.ctx, {"id": "T-1", "text": "x"})["code"],
                         "ticket_closed")
        self.ctx.records[("agent/tickets", self.path)] = ticket()
        self.ctx.records[("agent/projects", "P.yaml")] = {"archived": True}
        self.assertEqual(tickets._route_note_write(self.ctx, {"id": "T-1", "text": "x"})["code"],
                         "project_archived")
        self.ctx.records[("agent/projects", "P.yaml")] = {}
        self.assertEqual(tickets._route_note_write(self.ctx, {"id": "T-1", "text": 1})["code"],
                         "bad_input")
        self.assertEqual(tickets._route_note_write(self.ctx, {"id": "T-1", "text": " "})["code"],
                         "empty_text")
        out = tickets._route_note_write(self.ctx, {"id": "T-1", "text": " 备注 "})
        self.assertEqual(out["effects"][0]["kind"], "write")
        self.assertEqual(out["history"][-1]["text"], "备注")


class SetupTest(unittest.TestCase):
    def test_setup_registers_routes_tools_and_handler(self):
        ctx = Ctx()
        self.assertTrue(tickets.setup(ctx))
        self.assertTrue(any(r[0] == "tickets.close" for r in ctx.registrations))
        self.assertEqual(len(ctx.tools.rows), 7)
        handler = dict((r[0], r[1]) for r in ctx.registrations)["tickets.msg"]
        self.assertEqual(handler(ctx, {"tpl": "{a}", "vars": {"a": "x"},
                                       "paths": {"x": 1}})["text"], "x")
        self.assertEqual(handler(ctx, {"tpl": "", "vars": {}})["text"], "")
        self.assertEqual(tickets._route_record_path(ctx, {"id": "T-9"}),
                         {"path": "tickets/T-9/ticket.yaml"})
        self.assertEqual(tickets._route_record_path(ctx, {"id": "T-9", "project": "P"}),
                         {"path": "projects/P/tickets/T-9/ticket.yaml"})


class CreateTest(unittest.TestCase):
    def setUp(self):
        tickets._TICKET_PROJECT.clear()
        self.ctx = Ctx()
        self.ctx.records[("agent/projects", "P.yaml")] = {"archived": False}

    def test_validate_and_claim_replay_paths(self):
        self.assertEqual(tickets._route_create(self.ctx, {"project": 1})["code"], "bad_project")
        self.ctx.claim = {"claimed": False, "status": "done", "result_digest": "T-1"}
        self.ctx.records[("agent/tickets", "projects/P/tickets/T-1/ticket.yaml")] = ticket()
        out = tickets._route_create(self.ctx, {"project": "P", "title": "x"})
        self.assertTrue(out["reused"])
        self.ctx.claim = {"claimed": False, "status": "done", "result_digest": ""}
        with self.assertRaises(ApiError) as err:
            tickets._route_create(self.ctx, {"project": "P", "title": "x"})
        self.assertEqual(err.exception.code, "idem_ghost")
        self.ctx.claim = {"claimed": False, "status": "abandoned"}
        with self.assertRaises(ApiError) as err:
            tickets._route_create(self.ctx, {"project": "P", "title": "x"})
        self.assertEqual(err.exception.code, "idem_abandoned")
        self.ctx.claim = {"claimed": False, "status": "claimed"}
        with self.assertRaises(ApiError) as err:
            tickets._route_create(self.ctx, {"project": "P", "title": "x"})
        self.assertEqual(err.exception.code, "idem_in_flight")

    def test_create_validation_project_and_exception(self):
        self.ctx.claim = {"claimed": True}
        self.assertEqual(tickets._route_create(self.ctx, {"project": "", "title": "x"})["code"],
                         "missing_project")
        self.ctx.records.pop(("agent/projects", "P.yaml"))
        self.assertEqual(tickets._route_create(self.ctx, {"project": "P", "title": "x"})["code"],
                         "project_missing")
        self.ctx.records[("agent/projects", "P.yaml")] = {}
        old = tickets._create
        tickets._create = lambda ctx, payload: (_ for _ in ()).throw(RuntimeError("boom"))
        try:
            with self.assertRaises(RuntimeError):
                tickets._route_create(self.ctx, {"project": "P", "title": "x"})
        finally:
            tickets._create = old
        self.assertEqual(self.ctx.settles[-1]["status"], "failed")
        self.assertIsNone(tickets._reuse_created(self.ctx, ""))
        self.assertIsNone(tickets._reuse_created(self.ctx, "T-GONE"))

    def test_create_guards_conflict_and_success(self):
        self.ctx.claim = {"claimed": True}
        out = tickets._route_create(self.ctx, {"project": "P", "title": "x",
                                               "goal": "g", "kind": "stall-audit"})
        self.assertTrue(out["id"].startswith("T-20261125-"))
        self.assertEqual(self.ctx.settles[-1]["status"], "done")
        self.assertEqual(out["effects"][0]["kind"], "write")
        self.ctx.records[("agent/projects", "P.yaml")] = {"archived": True}
        self.assertEqual(tickets._route_create(self.ctx, {"project": "P", "title": "x"})["code"],
                         "project_archived")
        self.ctx.records[("agent/projects", "P.yaml")] = {"overrides": {"roles": ["pm"]}}
        self.assertEqual(tickets._route_create(self.ctx, {"project": "P", "title": "x"})["code"],
                         "pm_disabled")
        self.ctx.records[("agent/projects", "P.yaml")] = {}
        self.ctx.exists = True
        self.assertEqual(tickets._route_create(self.ctx, {"project": "P", "title": "x"})["code"],
                         "ticket_id_conflict")
        self.ctx.exists = False
        self.ctx.records[("agent/tickets", "projects/P/tickets/T-1/ticket.yaml")] = ticket()
        self.ctx.claim = {"claimed": True}
        # 文件已存在时 store.exists 才是权威；这里断言建单仍按 claim 结果结算。
        out = tickets._route_create(self.ctx, {"project": "P", "title": "x"})
        self.assertEqual(out["id"], "T-20261125-0001")


class CloseSplitTest(unittest.TestCase):
    def setUp(self):
        tickets._TICKET_PROJECT.clear()
        self.ctx = Ctx()
        self.path = "projects/P/tickets/T-1/ticket.yaml"
        self.ctx.records[("agent/tickets", self.path)] = ticket()

    def test_close_guards_child_and_success(self):
        self.assertEqual(tickets._route_close(self.ctx, {"id": "none"})["code"], "not_found")
        self.ctx.records[("agent/projects", "P.yaml")] = {"archived": True}
        self.assertEqual(tickets._route_close(self.ctx, {"id": "T-1"})["code"],
                         "project_archived")
        self.ctx.records[("agent/projects", "P.yaml")] = {}
        self.ctx.records[("agent/tickets", self.path)] = ticket(children=["T-2"])
        self.ctx.records[("agent/tickets", "projects/P/tickets/T-2/ticket.yaml")] = ticket()
        self.assertEqual(tickets._route_close(self.ctx, {"id": "T-1"})["code"],
                         "children_open")
        self.ctx.records[("agent/tickets", "projects/P/tickets/T-2/ticket.yaml")] = \
            ticket(status="closed", id="T-2")
        self.ctx.records[("agent/logs", "sessions/S-PM.yaml")] = {
            "id": "S-PM", "name": "PM", "messages": []}
        self.ctx.records[("agent/logs", "sessions/S-R.yaml")] = {
            "id": "S-R", "role": "dev", "display": "开发", "ticket": "T-1", "messages": []}
        self.ctx.config["logs.paths"] = {"session": "sessions/{id}.yaml",
                                         "session_glob": "sessions/*.yaml"}
        self.ctx.records[("agent/tickets", self.path)] = ticket(children=["T-2"], pm="S-PM",
                                                                parent="T-P",
                                                                roles=[{"role": "dev",
                                                                        "session": "S-R"}])
        out = tickets._route_close(self.ctx, {"id": "T-1", "summary": "完"})
        self.assertEqual(out["status"], "closed")
        self.assertTrue(any(e["kind"] == "demand" for e in out["effects"]))
        self.assertIn("S-PM", self.ctx.runtime.stopped)
        self.ctx.log_items = ["sessions/S-EXTRA.yaml"]
        self.ctx.records[("agent/logs", "sessions/S-EXTRA.yaml")] = {
            "id": "S-EXTRA", "role": "qa", "ticket": "T-1", "messages": []}
        out = tickets._route_close(self.ctx, {"id": "T-1"})
        self.assertEqual(out["status"], "closed")
        self.assertIsNone(tickets._session_snapshot(self.ctx, ""))
        self.assertIsNone(tickets._session_snapshot(self.ctx, "S-GONE"))
        self.ctx.log_items = ["sessions/S-NONE.yaml"]
        self.ctx.records[("agent/logs", "sessions/S-EXTRA.yaml")] = {
            "id": "S-EXTRA", "role": "qa", "ticket": "T-1", "messages": []}
        out = tickets._route_close(self.ctx, {"id": "T-1"})
        self.assertEqual(out["status"], "closed")

    def test_close_simple_no_children_no_parent(self):
        self.ctx.records[("agent/projects", "P.yaml")] = {}
        self.ctx.records[("agent/tickets", self.path)] = ticket(parent="", children=[],
                                                                roles=[])
        self.ctx.config["logs.paths"] = {"session": "sessions/{id}.yaml",
                                         "session_glob": "sessions/*.yaml"}
        out = tickets._route_close(self.ctx, {"id": "T-1"})
        self.assertEqual(out["status"], "closed")
        self.assertFalse(any(e["kind"] == "demand" for e in out["effects"]))
        self.ctx.records[("agent/tickets", self.path)] = ticket(children=["T-NONE"])
        self.assertEqual(tickets._route_close(self.ctx, {"id": "T-1"})["status"], "closed")
        self.ctx.records[("agent/tickets", self.path)] = ticket(children=[], roles=[])
        self.ctx.log_items = ["rows/S-X.yaml"]
        self.ctx.records[("agent/logs", "rows/S-X.yaml")] = {
            "id": "S-X", "ticket": "T-1", "role": "qa"}
        self.assertEqual(tickets._route_close(self.ctx, {"id": "T-1"})["status"], "closed")
        self.ctx.records[("agent/tickets", self.path)] = ticket(
            children=[], roles=[{"role": "qa", "session": "S-NONE"}])
        self.assertEqual(tickets._route_close(self.ctx, {"id": "T-1"})["status"], "closed")
        self.ctx.records[("agent/tickets", self.path)] = ticket(children=[], roles=[])
        self.ctx.log_items = ["rows/S-X.yaml"]
        self.ctx.records[("agent/logs", "rows/S-X.yaml")] = {
            "id": "S-X", "ticket": "T-1", "role": "qa"}
        self.assertEqual(tickets._route_close(self.ctx, {"id": "T-1"})["status"], "closed")

    def test_split_validation_limit_and_success(self):
        self.assertEqual(tickets._route_split(self.ctx, {"id": "T-1", "children": "x"})["code"],
                         "bad_input")
        self.ctx.records[("agent/tickets", self.path)] = ticket(children=["a", "b"])
        self.assertEqual(tickets._route_split(self.ctx, {"id": "T-1",
                                                          "children": [{"title": "x"}],
                                                          "max_children": 2})["code"],
                         "too_many_children")
        self.ctx.records[("agent/tickets", self.path)] = ticket()
        out = tickets._route_split(self.ctx, {"id": "T-1", "children": [{"title": "x"}]})
        self.assertEqual(len(out["effects"]), 1)
        self.assertEqual(out["children"], ["T-CHILD"])


class RebindStallTest(unittest.TestCase):
    def setUp(self):
        tickets._TICKET_PROJECT.clear()
        self.ctx = Ctx()

    def test_rebind_validation_and_rows(self):
        self.assertEqual(tickets._route_rebind(self.ctx, {"from": "", "to": "B"})["code"],
                         "bad_input")
        self.assertEqual(tickets._route_rebind(self.ctx, {"from": "A", "to": "A"})["code"],
                         "bad_input")
        self.ctx.walk_rows = [{"id": "T-1", "project": "A"},
                              {"id": "T-2", "project": "B"}, None]
        out = tickets._route_rebind(self.ctx, {"from": "A", "to": "C", "now": "T"})
        self.assertEqual(out["tickets"], ["T-1"])
        self.assertEqual(out["effects"][0]["path"], "projects/C/tickets/T-1/ticket.yaml")

    def test_stall_scan_disabled_and_audit(self):
        self.ctx.since = 120
        out = tickets._route_stall_scan(self.ctx, {"enabled": False})
        self.assertEqual(out["scan"], [])
        self.ctx.walk_rows = [{"id": "T-1", "updated": "T"}]
        out = tickets._route_stall_scan(self.ctx, {"enabled": True, "idle_minutes": 1,
                                                   "max_per_scan": 2,
                                                   "create_audit": True})
        self.assertEqual(out["scan"], ["T-1"])
        self.assertEqual(self.ctx.runtime.dispatched[0]["key"], "audit-T-1")
        self.ctx.walk_rows = [{"id": "T-2", "updated": "T", "status": "closed"}]
        out = tickets._route_stall_scan(self.ctx, {"enabled": True, "idle_minutes": 1,
                                                   "max_per_scan": 2,
                                                   "create_audit": False})
        self.assertEqual(out["scan"], [])


if __name__ == "__main__":
    unittest.main()


class CollectSessionIdsTest(unittest.TestCase):
    """结单回收名单：登记 ∪ 目录兜底，别的工单/空 id 不算本单。"""

    def test_collects_registered_and_matched_rows_only(self):
        from ai_new.modules.agent.tickets.private import _pure as pure
        rec = {"id": "T-1", "pm": "pm-1",
               "roles": [{"session": "role-1"}, {"session": ""}, {}]}
        rows = [{"id": "role-2", "ticket": "T-1"},     # 登记漏挂的异常会话
                {"id": "role-9", "ticket": "T-2"},     # 别的工单
                {"id": "pm-1", "ticket": "T-1"}]       # 已登记，不重复
        got = pure.collect_session_ids({"rec": rec, "rows": rows})
        self.assertEqual(got["sids"], ["pm-1", "role-1", "role-2"])
