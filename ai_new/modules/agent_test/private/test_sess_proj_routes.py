"""sessions / projects 路由与装配覆盖。"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))
from unittest import mock

from ai_new.modules.agent import sessions as sess
from ai_new.modules.agent import projects as proj
from ai_new.modules.agent.sessions.private import _pure as spure
from ai_new.modules.agent.projects.private import _pure as ppure


class ApiError(Exception):
    def __init__(self, msg, code="bad", status=400):
        super().__init__(msg)
        self.code = code
        self.status = status


class FakeCtx:
    ApiError = ApiError

    def __init__(self):
        self.calls = {}
        self.conf = {"logs": {"session_glob": "sessions/*.yaml", "session": "s/{id}.yaml",
                              "ticket_glob": "projects/*/tickets/*/ticket.yaml",
                              "ticket_prefix": "projects/{project}/tickets/{seg}"},
                     "sessions": {"paths": {"prompt": "p/{kind}.md"}},
                     "projects": {"paths": {"record": "projects/{id}.yaml",
                                           "project_dir": "projects/{pid}"}},
                     "knowledge": {"paths": {"ticket": "tickets/{ticket}"}}}
        self.rows = {}
        self.reads = {}
        self.globs = {}
        self.claim = {"claimed": True}
        self.hooks = mock.Mock()
        self.api = mock.Mock()
        self.api.call = self._call
        self.api.register = mock.Mock()
        self.runtime = mock.Mock()
        self.runtime.active_keys.return_value = []
        self.runtime.dispatch = mock.Mock()
        self.runtime.call = mock.Mock()
        self.demand_engine = mock.Mock()
        self.demand_engine.run_callable = mock.Mock()

    def _call(self, name, payload=None, caller=None):
        p = payload or {}
        fn = self.calls.get(name)
        if fn:
            return fn(p)
        if name == "config.get":
            key = p.get("key") or ""
            if key == "logs.paths":
                return {"value": self.conf.get("logs")}
            if key == "sessions.paths":
                return {"value": self.conf.get("sessions", {}).get("paths")}
            if key == "projects.paths":
                return {"value": self.conf.get("projects", {}).get("paths")}
            if key == "knowledge.paths":
                return {"value": self.conf.get("knowledge", {}).get("paths")}
            return {"value": None}
        if name == "codec.digest":
            return {"hex": "k"}
        if name == "store.read":
            key = p.get("path")
            if key not in self.reads:
                key = "%s/%s" % (str(p.get("module") or "").rsplit("/", 1)[-1], key)
            return {"value": self.reads.get(key)}
        if name == "store.read_text":
            key = p.get("path")
            if key not in self.reads:
                key = "%s/%s" % (str(p.get("module") or "").rsplit("/", 1)[-1], key)
            return {"value": self.reads.get(key)}
        if name == "store.glob":
            return {"items": self.globs.get(p.get("module"), [])}
        if name == "store.id":
            return {"id": str(p.get("value") or "").lower()}
        if name == "store.exists":
            return {"exists": p.get("path") in self.reads}
        if name == "store.next_seq":
            return {"seq": 7}
        if name == "store.claim":
            return self.claim
        if name == "store.settle":
            return {"settled": True}
        if name == "clock.now":
            return {"ts": 10}
        if name == "clock.since":
            return {"seconds": 30}
        if name == "sessions.view":
            return dict(p.get("rec") or {})
        if name == "sessions.build":
            return {"id": "s1", "kind": p.get("kind"), "ticket": p.get("ticket"),
                    "project": p.get("project"), "meta": p.get("meta") or {}}
        if name == "sessions.active_same_role":
            return {"items": [{"id": "dup"}] if p.get("role") == "dup" else []}
        if name == "projects.build":
            return {"id": p.get("id"), "name": p.get("name"), "root": p.get("root")}
        if name == "projects.rooted":
            return ppure.rooted(p)
        if name == "projects.view":
            return dict(p.get("rec") or {})
        if name == "projects.toggle_override":
            return ppure.toggle_override(p)
        if name == "projects.override_parts":
            return ppure.override_parts(p)
        if name == "projects.archive":
            return ppure.archive(p)
        if name == "projects.renamed":
            return ppure.renamed(p)
        if name == "projects.conflict":
            return {"ok": False, "code": "exists"}
        if name == "projects.missing":
            return {"ok": False, "code": "not_found"}
        if name == "projects.deleted":
            return {"deleted": True, "id": p.get("id")}
        if name == "logs.record":
            return {"effects": []}
        if name == "logs.purge":
            return {"effects": [{"kind": "index"}]}
        if name == "tickets.rebind":
            return {"effects": [{"kind": "rebind"}]}
        if name == "store.workspace":
            return {"ok": True, "root": p.get("root") or "/w",
                    "dirs": {"documents": "/w/docs", "logs": "/w/logs",
                             "artifacts": "/w/art", "tickets": "/w/tickets"}}
        raise AssertionError("unexpected route " + name)


class SessionsRoutesTest(unittest.TestCase):
    def ctx(self, **kw):
        c = FakeCtx()
        for k, v in kw.items():
            setattr(c, k, v)
        return c

    def test_setup_start(self):
        ctx = self.ctx()
        self.assertTrue(sess.setup(ctx))
        self.assertEqual(ctx.api.register.call_count, 29)
        ctx.runtime.call.side_effect = RuntimeError("x")
        sess.start(ctx)
        ctx.runtime.call.side_effect = None
        sess.start(ctx)
        self.assertEqual(ctx.api.register.call_args_list[0][0][0], "sessions.build")

    def test_helpers(self):
        ctx = self.ctx()
        h = sess._as_handler(spure.build)
        self.assertEqual(h(ctx, None)["kind"], "role")
        self.assertEqual(sess._record_path({}, "s"), "s")
        self.assertEqual(sess._record_path({"session": "x/{id}"}, "s"), "x/s")
        self.assertEqual(sess._msg_tpl(ctx), {})
        self.assertEqual(sess._cfg_logs(ctx), ctx.conf["logs"])
        self.assertEqual(sess._cfg_prompt(ctx), {"prompt": "p/{kind}.md"})
        self.assertEqual(sess._seq_of("role", ["a/role-2.yaml", "x", "role-a"]) + 0, 3)

    def test_resume_scan(self):
        ctx = self.ctx()
        ctx.globs["agent/logs"] = ["a", "b"]
        ctx.reads.update({"a": {"id": "a", "status": "running"},
                          "b": None})
        ctx.calls["sessions.resume_plan"] = lambda p: {
            "resume": [{"id": "a", "path": "a", "rec": {"x": 1}}],
            "stale": [{"id": "b", "path": "b", "rec": {"x": 2}}]}
        out = sess._route_resume(ctx, {"enabled": False, "max": 1})
        self.assertEqual(len(out["effects"]), 3)
        self.assertEqual(out["resumed"], ["a"])
        ctx.calls["sessions.resume_plan"] = lambda p: {"resume": [{"path": "a", "rec": {}}],
                                                        "stale": []}
        self.assertEqual(len(sess._route_resume(ctx, {})["effects"]), 1)
        ctx.calls["sessions.stuck_plan"] = lambda p: {"stuck": [{"id": "b", "path": "b",
                                                                  "rec": {}}], "keep": []}
        out = sess._route_scan_stuck(ctx, {"enabled": False, "idle_minutes": 2})
        self.assertEqual(out["stuck"], ["b"])

    def test_ensure_talk_by_ticket(self):
        ctx = self.ctx()
        with self.assertRaises(ApiError):
            sess._route_ensure(ctx, {"role": ""})
        ctx.reads["s/old.yaml"] = {"id": "old", "role": "r", "kind": "role",
                                    "status": "idle", "meta": {"purpose": "p"}}
        ctx.globs["agent/logs"] = ["s/old.yaml"]
        out = sess._route_ensure(ctx, {"role": "r", "meta": {"purpose": "p"}})
        self.assertTrue(out["reused"])
        ctx.reads["s/old.yaml"]["status"] = "gone"
        out = sess._route_ensure(ctx, {"role": "r", "meta": {"purpose": "p"}})
        self.assertEqual(out["id"], "s1")
        with self.assertRaises(ApiError):
            sess._route_talk(ctx, {})
        with self.assertRaises(ApiError):
            sess._route_talk(ctx, {"id": "x"})
        with self.assertRaises(ApiError):
            sess._route_talk(ctx, {"id": "x", "text": "t"})
        ctx.reads["s/x.yaml"] = {"id": "x"}
        out = sess._route_talk(ctx, {"id": "x", "text": "t"})
        self.assertTrue(out["ok"])
        ctx.globs["agent/logs"] = ["s/a.yaml", "s/b.yaml"]
        ctx.reads.update({"s/a.yaml": {"id": "a", "ticket": "t"},
                          "s/b.yaml": None})
        self.assertEqual(len(sess._route_by_ticket(ctx, {"ticket": "t"})["items"]), 1)

    def test_emit_guard_spawn(self):
        ctx = self.ctx()
        self.assertEqual(sess._route_emit_finished(ctx, {})["ok"], True)
        ctx.hooks = None
        sess._route_emit_finished(ctx, {"rec": {"id": "x"}})
        ctx.hooks = mock.Mock()
        sess._route_emit_finished(ctx, {"rec": {"id": "x"}})
        self.assertEqual(sess._role_guard(ctx, {}), "")
        self.assertEqual(sess._role_guard(ctx, {"role": "r", "project": "p",
                                                "kind": "pm", "project_overrides": {}}), "")
        self.assertEqual(sess._role_guard(ctx, {"role": "r", "project": "p",
                                                "project_overrides": {"roles": ["x"]}}), "")
        ctx.reads["messages.yaml"] = {"role_disabled": "no {role} {project}"}
        with self.assertRaises(ApiError) as e:
            sess._spawn(ctx, {"role": "r", "project": "p",
                              "project_overrides": {"roles": ["r"]}})
        self.assertEqual(e.exception.code, "role_disabled")
        self.assertEqual(sess._role_guard(ctx, {"role": "r", "project": "p",
                                                "project_overrides": {"roles": ["r"]},
                                                "role_system": True}), "")
        self.assertEqual(sess._role_guard(ctx, {"role": "r", "project": "p",
                                                "project_overrides": {"roles": ["r"]},
                                                "role_readonly": True}), "")
        ctx.claim = {"claimed": False, "status": "abandoned"}
        with self.assertRaises(ApiError) as e:
            sess._route_spawn(ctx, {"role": "r"})
        self.assertEqual(e.exception.code, "idem_abandoned")
        ctx.claim = {"claimed": False, "status": "done"}
        self.assertEqual(sess._route_spawn(ctx, {"role": "r"})["id"], "s1")
        ctx.claim = {"claimed": True}
        sess._route_spawn(ctx, {"role": "r"})
        self.assertTrue(ctx.api.call("store.settle", {}).get("settled"))

    def test_spawn_full(self):
        ctx = self.ctx()
        ctx.globs["agent/logs"] = ["s/a.yaml"]
        ctx.reads["s/a.yaml"] = {"id": "a"}
        out = sess._spawn(ctx, {"role": "dup", "name": "n", "ticket": "t",
                                "project": "p", "seq": 3, "tools": ["x"],
                                "machine": "m", "flow": "f", "active": "a",
                                "stages": ["s"], "stage": "st", "role_prompt": "rp",
                                "constraint": "c", "task": "t", "intro": "i",
                                "max_steps": 3, "kind": "pm"})
        self.assertTrue(out["duplicate"])
        ctx.calls["sessions.active_same_role"] = lambda p: {"items": []}
        out = sess._spawn(ctx, {"role": "r", "ticket": "t", "project": "p",
                                "meta": {"m": 1}})
        self.assertEqual(out["id"], "s1")
        self.assertEqual(len(out["effects"]), 1)
        ctx.reads["s/empty.yaml"] = None
        ctx.globs["agent/logs"] = ["s/a.yaml", "s/empty.yaml"]
        out = sess._spawn(ctx, {"role": "r", "ticket": "t", "tools": ["x"],
                                "machine": "m", "flow": "f", "active": True,
                                "stages": ["s"], "stage": "st", "seq": 1})
        self.assertEqual(out["rec"]["meta"]["tools"], ["x"])
        ctx.calls["sessions.active_same_role"] = lambda p: {"items": []}
        ctx.calls["sessions.build"] = lambda p: {"id": "s1", "meta": p.get("meta")}
        out = sess._spawn(ctx, {"role": "r", "ticket": "t", "kind": "x"})
        self.assertEqual(out["rec"]["meta"], {})
        out = sess._spawn(ctx, {"role": "r", "role_prompt": "rp"})
        self.assertEqual(out["rec"]["meta"], {})
        h = sess._as_handler(spure.build)
        self.assertEqual(h(ctx, {"tpl": {}, "paths": {}})["kind"], "role")
        ctx.reads["p/role.md"] = {"prompt": "x"}
        out = sess._spawn(ctx, {"role": "r", "kind": "role", "name": ""})
        self.assertEqual(out["effects"][0]["kind"], "write")


class ProjectsRoutesTest(unittest.TestCase):
    def ctx(self, **kw):
        c = FakeCtx()
        for k, v in kw.items():
            setattr(c, k, v)
        return c

    def test_create(self):
        ctx = self.ctx()
        self.assertTrue(proj.setup(ctx))
        self.assertEqual(ctx.api.register.call_count, 20)
        self.assertEqual(proj._route_create(ctx, {})["code"], "missing_name")
        out = proj._route_create(ctx, {"name": "P", "root": "/r"})
        self.assertEqual(out["effects"][0]["path"], "projects/p.yaml")
        ctx.reads["projects/p.yaml"] = {"id": "p"}
        self.assertEqual(proj._route_create(ctx, {"name": "P"})["code"], "exists")
        ctx.calls["store.workspace"] = lambda p: {"ok": False, "error": "bad",
                                                  "code": "bad", "status": 400}
        with self.assertRaises(ApiError):
            proj._route_create(ctx, {"name": "x", "root": "/x"})
        self.assertEqual(proj._record({}, "p"), "p")

    def test_set_root_workspace_toggle(self):
        ctx = self.ctx()
        self.assertEqual(proj._route_set_root(ctx, {"id": "p"})["code"], "not_found")
        ctx.reads["projects/p.yaml"] = {"id": "p", "archived": True}
        self.assertEqual(proj._route_set_root(ctx, {"id": "p"})["code"],
                         "project_archived")
        ctx.reads["projects/p.yaml"] = {"id": "p"}
        out = proj._route_set_root(ctx, {"id": "p", "root": "/r"})
        self.assertEqual(out["root"], "/r")
        ctx.reads["projects/p.yaml"]["archived"] = True
        self.assertEqual(proj._route_workspace(ctx, {"id": "p"})["project"]["archived"], True)
        ctx.calls["store.workspace"] = lambda p: {"ok": True, "root": "/w", "dirs": {}}
        out = proj._route_workspace(ctx, {"id": "p"})
        self.assertEqual(out["ticket_pattern"], "")
        self.assertEqual(out["layers"][0]["path"], "/w")
        self.assertEqual(proj._route_workspace(ctx, {"id": "none"})["code"], "not_found")
        ctx.reads["projects/p.yaml"] = {"id": "p"}
        self.assertEqual(proj._route_toggle(ctx, {"project": "none"})["code"], "not_found")
        self.assertEqual(proj._route_toggle(ctx, {"project": "p", "kind": "roles",
                                                   "id": "r"})["code"], "role_not_found")
        ctx.reads["library/seed.yaml"] = {"roles": [{"id": "r"}]}
        ctx.reads["library/roles.yaml"] = {"rr": {"cn": "R", "tools": ["x"]},
                                            "zz": {"cn": "Z", "tools": []}}
        out = proj._route_toggle(ctx, {"project": "p", "kind": "roles", "id": "r",
                                        "enabled": False})
        self.assertIn("r", out["overrides"]["roles"])
        out = proj._route_toggle(ctx, {"project": "p", "kind": "tools", "id": "x",
                                        "enabled": False})
        self.assertEqual(out["cascaded"], ["rr"])
        self.assertEqual(out["cascaded_names"], ["R"])
        ctx.reads["projects/p.yaml"] = {"id": "p", "archived": True}
        self.assertEqual(proj._route_toggle(ctx, {"project": "p"})["code"],
                         "project_archived")
        self.assertEqual(proj._purge_sessions(ctx, []), [])
        ctx.globs["agent/logs"] = []
        self.assertEqual(proj._purge_sessions(ctx, ["none"]), [])
        ctx.reads["s/b.yaml"] = {"id": "b", "ticket": "other"}
        ctx.globs["agent/logs"] = ["s/a.yaml", "s/b.yaml"]
        ctx.reads["s/a.yaml"] = {"id": "a", "ticket": "t1"}
        proj._purge_sessions(ctx, ["t1"])
        h = proj._as_handler(ppure.view)
        self.assertEqual(h(ctx, {"tpl": {}, "paths": {}})["id"], None)
        self.assertEqual(h(ctx, None)["id"], None)

    def test_remove(self):
        ctx = self.ctx()
        ctx.calls["store.glob"] = lambda p: {"items": (
            ["projects/p/tickets/t1/ticket.yaml", "x",
             "projects/q/tickets/t2/ticket.yaml"] if p.get("module") == "agent/tickets"
            else ["s/a.yaml"])}
        ctx.calls["store.read"] = lambda p: {"value": (
            {"id": "a", "ticket": "t1"} if str(p.get("path", "")).startswith("s/")
            else {"id": "t1", "ticket": "t1"})}
        ctx.globs["agent/logs"] = ["s/a.yaml"]
        ctx.reads["s/a.yaml"] = {"id": "a", "ticket": "t1"}
        ctx.reads["projects/p.yaml"] = {"id": "p"}
        out = proj._route_remove(ctx, {"id": "p", "purge": True})
        self.assertTrue(out["deleted"])
        self.assertIn("remove_dir", [e["kind"] for e in out["effects"]])
        ctx.runtime.stop.assert_called_with("a")
        ctx.calls.pop("store.glob")
        ctx.calls.pop("store.read")
        ctx.calls["store.glob"] = lambda p: {"items": (
            ["projects/p/tickets/t1/ticket.yaml"] if p.get("module") == "agent/tickets"
            else [])}
        ctx.calls["store.read"] = lambda p: {"value": {"id": "t1", "status": "open"}}
        out = proj._route_remove(ctx, {"id": "p"})
        self.assertEqual(out["code"], "open_tickets")
        ctx.calls["store.read"] = lambda p: {"value": {"id": "t1", "status": "closed"}}
        out = proj._route_remove(ctx, {"id": "p"})
        self.assertTrue(out["archived"])
        ctx.calls["store.glob"] = lambda p: {"items": ["x", "projects/q/tickets/t2/ticket.yaml"]}
        ctx.calls["store.read"] = lambda p: {"value": None}
        self.assertTrue(proj._route_remove(ctx, {"id": "p"})["archived"])

    def test_rename_toggle_more(self):
        ctx = self.ctx()
        self.assertEqual(proj._route_rename(ctx, {"id": "x", "name": "y"})["code"],
                         "not_found")
        ctx.reads["projects/old.yaml"] = {"id": "old", "archived": True}
        self.assertEqual(proj._route_rename(ctx, {"id": "old", "name": "new"})["code"],
                         "project_archived")
        ctx.reads["projects/old.yaml"] = {"id": "old"}
        ctx.reads["projects/new.yaml"] = {"id": "new"}
        self.assertEqual(proj._route_rename(ctx, {"id": "old", "name": "new"})["code"],
                         "exists")
        ctx.reads.pop("projects/new.yaml")
        out = proj._route_rename(ctx, {"id": "old", "name": "new"})
        self.assertEqual(len(out["effects"]), 3)
        out = proj._route_rename(ctx, {"id": "old", "name": "old"})
        self.assertEqual(len(out["effects"]), 1)
        ctx.reads["projects/x.yaml"] = {"id": "x"}
        out = proj._route_toggle(ctx, {"project": "x", "kind": "bad", "id": "a"})
        self.assertEqual(out["code"], "bad_kind")


if __name__ == "__main__":
    unittest.main()
