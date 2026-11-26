"""timer 路由边界：跨域拒绝、更新/翻转、tick 失败与 cron 重排、工具接线与后台循环。"""
from __future__ import annotations

import copy
import json
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))

from ai_new.modules.agent import timer as t  # noqa: E402
from ai_new.modules.agent_common.clock.private import _clock  # noqa: E402


class Clock:
    schedule_next = staticmethod(_clock.schedule_next)
    due_slots = staticmethod(_clock.due_slots)


class Api:
    def __init__(self, ctx):
        self.ctx = ctx
        self.calls = []

    def call(self, route, payload=None, caller=None):
        payload = payload or {}
        self.calls.append(route)
        if route == "clock.now":
            return {"ts": self.ctx.now}
        if route == "timer.tick":
            return {"effects": [{"kind": "append_text"}]}
        if route == "clock.sleep":
            if self.ctx.sleep_raises:
                raise RuntimeError("stop-loop")
            return {"slept": payload.get("seconds")}
        if route == "config.get":
            return {"value": self.ctx.cfg}
        if route == "store.read":
            path = payload.get("path")
            if path == "messages.yaml":
                return {"value": {"missing": "missing",
                                  "forbidden_scope": "forbidden",
                                  "bad_action": "bad", "bad_cron": "bad cron",
                                  "quota_exceeded": "quota",
                                  "trigger_failed": "trigger failed"}}
            project = path.split("/")[1]
            return {"value": {"items": copy.deepcopy(self.ctx.records.get(project, []))}}
        if route == "store.glob":
            return {"items": ["projects/%s/timers.yaml" % p for p in self.ctx.records]}
        if route == "store.next_seq":
            return {"seq": self.ctx.seq}
        if route == "store.read_text":
            return {"value": self.ctx.runs}
        if route == "codec.json_encode":
            return {"text": json.dumps(payload["value"])}
        if route == "codec.json_decode":
            return {"ok": True, "value": json.loads(payload["text"])}
        if route == "secretary.push":
            if self.ctx.push_raises:
                raise ValueError("push down")
            return self.ctx.push_result
        if route == "tickets.create":
            return self.ctx.ticket_result
        raise AssertionError(route)


class Runtime:
    def __init__(self):
        self.rows = []

    def apply(self, row):
        self.rows.append(row)


class Tools:
    def __init__(self):
        self.rows = []

    def has(self, name):
        return name == "timer_list"

    def register(self, *args, **kwargs):
        self.rows.append((args, kwargs))


class Ctx:
    def __init__(self):
        self.now = 1000
        self.cfg = {"min_interval_s": 0, "max_per_project": 3, "tick_interval_s": 1,
                    "max_catchup": 2, "default_tz": "Asia/Shanghai"}
        self.records = {}
        self.runs = ""
        self.seq = 1
        self.sleep_raises = True
        self.push_result = {"ok": True}
        self.ticket_result = {"ok": True, "id": "T1"}
        self.push_raises = False
        self.api = Api(self)
        self.clock = Clock()
        self.runtime = Runtime()

    def apply(self):
        return self.runtime.rows


def caller(scope="project", project="p", ticket=""):
    return {"scope": scope, "project": project, "ticket": ticket,
            "session": "s", "role": "pm"}


def payload(**kw):
    row = {"kind": "cron", "expr": "* * * * *", "title": "t", "action": "notify",
           "project": "p", "caller": caller()}
    row.update(kw)
    return row


def apply(ctx, res):
    for effect in res.get("effects") or []:
        if effect.get("kind") == "write":
            project = effect["path"].split("/")[1]
            ctx.records.setdefault(project, [])
            ctx.records[project] = effect["value"]["items"]
    return res


class TimerRoutesEdgeTest(unittest.TestCase):
    def test_create_scope_and_quota(self):
        ctx = Ctx()
        denied = t._route_create(ctx, payload(caller=caller(project="x")))
        self.assertEqual(denied["code"], "forbidden_scope")
        denied = t._route_create(ctx, payload(caller=caller(scope="ticket",
                                                             ticket="a")))
        self.assertEqual(denied["code"], "forbidden_scope")
        ctx.cfg["max_per_project"] = 1
        ctx.records["p"] = [{"id": "tm-1", "project": "p"}]
        self.assertEqual(t._route_create(ctx, payload())["code"], "quota_exceeded")
        ctx.cfg["max_per_project"] = 0
        ctx.seq = 2
        ok = t._route_create(ctx, payload(kind="once",
                                          expr="2020-01-01T00:00:00Z"))
        self.assertEqual(ok["id"], "tm-0002")
        self.assertTrue(ok["effects"])

    def test_list_update_toggle_and_missing(self):
        ctx = Ctx()
        ctx.records["p"] = [{"id": "tm-1", "project": "p", "title": "a",
                             "kind": "cron", "expr": "* * * * *",
                             "tz": "UTC", "status": "active", "signature": "s"}]
        rows = t._route_list(ctx, payload(id="tm-1"))
        self.assertEqual(rows["total"], 1)
        rows = t._route_list(ctx, payload(id="none"))
        self.assertEqual(rows["total"], 0)
        self.assertEqual(t._route_update(ctx, payload(id="none"))["code"], "not_found")
        bad = t._route_update(ctx, payload(id="tm-1", expr="bad"))
        self.assertEqual(bad["code"], "bad_cron")
        good = t._route_update(ctx, payload(id="tm-1", title="b"))
        self.assertTrue(good["ok"])
        self.assertEqual(t._route_toggle(ctx, payload(id="tm-1",
                                                      action="bad"))["code"],
                         "bad_action")
        self.assertEqual(t._route_toggle(ctx, payload(id="tm-1",
                                                      action="pause"))["status"],
                         "paused")
        ctx.cfg["min_interval_s"] = 0
        self.assertEqual(t._route_toggle(ctx, payload(id="tm-1",
                                                      action="resume"))["status"],
                         "active")
        ctx.records["p"][0]["expr"] = "bad"
        self.assertEqual(t._route_toggle(ctx, payload(id="tm-1",
                                                      action="resume"))["status"],
                         "active")
        self.assertEqual(t._baseline([{"id": "x"}, {"id": "tm-x"},
                                      {"id": "tm-3"}]), 3)
        self.assertEqual(t._route_delete(ctx, payload(id="tm-1"))["status"],
                         "deleted")
        self.assertEqual(t._route_history(ctx, payload(id="none"))["code"],
                         "not_found")

    def test_tick_due_failures_and_cron_advance(self):
        ctx = Ctx()
        ctx.records["p"] = [{"id": "tm-1", "project": "p", "title": "a",
                             "kind": "cron", "expr": "bad", "tz": "UTC",
                             "action": "notify", "status": "active",
                             "created": 0, "attempts": 0, "fired": []}]
        out = apply(ctx, t._route_tick(ctx, {"now": 100}))
        self.assertEqual(out["skipped"][0]["reason"], "bad_cron")
        ctx.records["p"][0]["expr"] = "* * * * *"
        out = apply(ctx, t._route_tick(ctx, {"now": 120}))
        self.assertTrue(out["fired"])
        # 触发后 next_at 必须严格晚于触发时刻：停在 120 就是「下次=刚才那一分」
        self.assertEqual(ctx.records["p"][0]["next_at"], 180)
        ctx.push_raises = True
        ctx.records["p"][0]["last_run"] = {"at": 0}
        ctx.records["p"][0]["fired"] = []
        out = apply(ctx, t._route_tick(ctx, {"now": 120}))
        self.assertEqual(out["skipped"][0]["reason"], "push down")
        ctx.push_raises = False
        ctx.clock.schedule_next = lambda p: {"ok": False}
        ctx.records["p"][0]["kind"] = "cron"
        ctx.records["p"][0]["expr"] = "* * * * *"
        ctx.records["p"][0]["last_run"] = {"at": 0}
        ctx.records["p"][0]["fired"] = []
        ctx.records["p"][0]["status"] = "active"
        apply(ctx, t._route_tick(ctx, {"now": 120}))
        ctx.clock.schedule_next = staticmethod(_clock.schedule_next)
        ctx.records["p"][0]["kind"] = "once"
        ctx.records["p"][0]["expr"] = "1970-01-01T00:02:00Z"
        ctx.records["p"][0]["last_run"] = {"at": 0}
        ctx.records["p"][0]["fired"] = []
        out = apply(ctx, t._route_tick(ctx, {"now": 120}))
        self.assertEqual(ctx.records["p"][0]["status"], "done")

    def test_history_blank_lines_and_tools(self):
        ctx = Ctx()
        ctx.records["p"] = [{"id": "tm-1", "project": "p", "kind": "cron",
                             "expr": "* * * * *", "status": "active"}]
        ctx.runs = '\n{"ok":true}\nbad-json\n{"ok":false}\n'
        orig = ctx.api.call

        def selective(route, payload=None, caller=None):
            if route == "store.read_text":
                return {"value": ctx.runs}
            if route == "codec.json_decode":
                try:
                    return {"ok": True, "value": json.loads(payload["text"])}
                except ValueError:
                    return {"ok": False}
            return orig(route, payload, caller)

        ctx.api.call = selective
        hist = t._route_history(ctx, payload(id="tm-1", limit=1))
        self.assertEqual(len(hist["history"]), 1)
        ctx.tools = Tools()
        ctx.api.call = lambda route, payload=None, caller=None: (
            {"value": {"tool_timer_list_desc": "list"}}
            if route == "store.read" else {"ts": 1} if route == "clock.now" else
            (_ for _ in ()).throw(AssertionError(route)))
        t._register_tools(ctx)
        self.assertEqual(len(ctx.tools.rows), 4)
        fn = ctx.tools.rows[0][0][3]
        ctx.api.call = lambda route, p=None, caller=None: {"ok": True,
                                                           "received": p}
        out = fn(ctx, {"kind": "cron"}, {"id": "s", "project": "p", "ticket": "t"})
        self.assertEqual(out["received"]["caller"]["scope"], "ticket")
        self.assertEqual(t._session_caller(None)["scope"], "project")

    def test_start_loop_effect_and_error(self):
        ctx = Ctx()
        captured = {}

        class Thread:
            def __init__(self, target, daemon, name):
                captured["target"] = target

            def start(self):
                try:
                    captured["target"]()
                except RuntimeError:
                    pass

        with mock.patch.object(t.threading, "Thread", Thread):
            self.assertTrue(t.start(ctx))
        self.assertEqual(len(ctx.runtime.rows), 1)
        ctx.sleep_raises = True
        ctx.tools = None
        ctx.api.call = lambda route, payload=None, caller=None: (
            (_ for _ in ()).throw(RuntimeError("tick down"))
            if route == "timer.tick" else
            (_ for _ in ()).throw(RuntimeError("stop-loop"))
            if route == "clock.sleep" else
            {"value": {"tick_interval_s": 0}}
            if route == "config.get" else None)
        try:
            captured["target"]()
        except RuntimeError:
            pass
        ctx.cfg = {}
        ctx.api.call = lambda route, payload=None, caller=None: (
            {"value": {}} if route == "config.get" else
            (_ for _ in ()).throw(RuntimeError("stop-loop")))
        try:
            captured["target"]()
        except RuntimeError:
            pass


if __name__ == "__main__":
    unittest.main()
