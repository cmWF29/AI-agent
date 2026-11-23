"""定时器验收：调度推算、notify/spawn_ticket 两路触发、幂等、作用域隔离与审计。

无 Web 服务进程内装配（夹具同 test_core）：真实 build 装配模块，经能力入口跑闭环；
now 由 payload 注入，纯函数不读时钟；不监听端口、不依赖外部 LLM（net 桩替换）。
"""
import datetime
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).parent))

from ai_new.modules.agent_common.boot.private._boot import _build as build  # noqa: E402
from ai_new.modules.agent_common.boot.private._context import Context  # noqa: E402
from _fixtures import stage, write_config  # noqa: E402


def _future_iso(seconds):
    """相对当前 UTC 时刻的 ISO 时间（秒后），供 once 表达式使用。"""
    return (datetime.datetime.now(datetime.timezone.utc)
            + datetime.timedelta(seconds=seconds)).isoformat()


class TimerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        root = Path(cls.tmp.name)
        stage(root)
        write_config(root, {
            "server": {"host": "127.0.0.1", "port": 0, "token": "t"},
            "llm": {"base_url": "http://stub.local/v1", "api_key": "k", "model": "stub"},
            "tickets": {"stall_check": {"enabled": False}},
            "timer": {"min_interval_s": 0, "max_per_project": 20,
                      "tick_interval_s": 3600, "max_catchup": 5,
                      "default_tz": "Asia/Shanghai"},
        })
        os.environ["AI_NEW_DATA"] = str(root)
        cls.ctx = Context(root)
        cls.loaded = build(cls.ctx)
        cls.ctx.api.substitute("net.request", _FakeNet())
        cls.ctx.api.substitute("net.request_stream", _FakeNet())
        cls.push_calls = []
        cls.ticket_calls = []
        cls._stub_push()
        cls._stub_tickets()

    @classmethod
    def tearDownClass(cls):
        http = getattr(cls.ctx, "http", None)
        if http is not None:
            http.shutdown()  # 释放非守护 serve_forever 线程，否则进程挂住不退
        os.environ.pop("AI_NEW_DATA", None)
        shutil.rmtree(cls.tmp.name, ignore_errors=True)

    @classmethod
    def _stub_push(cls):
        def push(ctx, payload):
            cls.push_calls.append(dict(payload))
            return {"ok": True, "id": payload.get("msg_id")}
        cls.ctx.api.substitute("secretary.push", push)

    @classmethod
    def _stub_tickets(cls):
        def create(ctx, payload):
            cls.ticket_calls.append(dict(payload))
            return {"ok": True, "id": "T-%04d" % (len(cls.ticket_calls) + 1)}
        cls.ctx.api.substitute("tickets.create", create)

    # ---- 夹具小工具 ----

    def _apply(self, res):
        effects = (res or {}).get("effects") or []
        if effects:
            self.ctx.runtime.apply({"effect": effects})

    def _create(self, payload, caller=None):
        payload = dict(payload)
        payload["caller"] = caller or self._project_caller(payload.get("project"), "s1")
        res = self.ctx.api.call("timer.create", payload)
        self._apply(res)
        return res

    @staticmethod
    def _project_caller(project, session="s1"):
        return {"scope": "project", "project": project, "ticket": "",
                "session": session, "role": "pm"}

    @staticmethod
    def _ticket_caller(project, ticket, session="s1"):
        return {"scope": "ticket", "project": project, "ticket": ticket,
                "session": session, "role": "role-a"}

    @staticmethod
    def _global_caller(session="admin"):
        return {"scope": "global", "project": "", "ticket": "",
                "session": session, "role": "admin"}

    def _audit_rows(self):
        row = self.ctx.api.call("store.read_text", {
            "module": "agent/timer", "path": "audit.jsonl"})
        rows = []
        for line in str(row.get("value") or "").splitlines():
            if not line.strip():
                continue
            dec = self.ctx.api.call("codec.json_decode", {"text": line})
            if dec.get("ok"):
                rows.append(dec["value"])
        return rows

    def _records(self, project):
        row = self.ctx.api.call("store.read", {
            "module": "agent/timer",
            "path": "projects/%s/timers.yaml" % project})
        return (row.get("value") or {}).get("items") or []

    def _tick(self, now=None):
        res = self.ctx.api.call("timer.tick", {"now": now})
        self._apply(res)
        return res

    # ---- 用例 ----

    def test_create_once_next_at_and_view_row(self):
        """once 建单：下次触发时刻落档，列表行字段齐全。"""
        res = self._create({
            "project": "p-once", "kind": "once", "expr": _future_iso(3600),
            "title": "明早提醒", "action": "notify", "tz": "Asia/Shanghai"})
        self.assertTrue(res["ok"], res)
        self.assertIsNotNone(res["next_at"])
        self.assertEqual(res["status"], "active")

        listed = self.ctx.api.call("timer.list", {
            "project": "p-once", "caller": self._project_caller("p-once")})
        self.assertEqual(listed["total"], 1)
        row = listed["items"][0]
        for key in ("id", "project", "title", "kind", "expr", "tz", "next_at",
                    "status", "last_run", "creator", "source_session", "created"):
            self.assertIn(key, row)

    def test_create_cron_next_at(self):
        """cron 建单：每天九点的规则推算出下次触发分钟。"""
        res = self._create({
            "project": "p-cron", "kind": "cron", "expr": "0 9 * * *",
            "title": "每日早会", "action": "notify", "tz": "Asia/Shanghai"})
        self.assertTrue(res["ok"], res)
        self.assertIsNotNone(res["next_at"])

    def test_tick_notify_pushes_to_secretary_queue(self):
        """到期 notify：秘书队列收到幂等 msg_id，字段带来源 timer/timer_id/slot。"""
        before = len(self.push_calls)
        res = self._create({
            "project": "p-notify", "kind": "once", "expr": _future_iso(120),
            "title": "定时提醒", "action": "notify"})
        tid = res["id"]
        self._tick(now=datetime.datetime.now(datetime.timezone.utc).timestamp() + 200)

        self.assertEqual(len(self.push_calls) - before, 1)
        push = self.push_calls[-1]
        self.assertEqual(push["project"], "p-notify")
        self.assertTrue(push["msg_id"].startswith("timer:%s:" % tid))
        self.assertEqual(push["fields"]["source"], "timer")
        self.assertEqual(push["fields"]["timer_id"], tid)
        self.assertTrue(push["fields"]["slot"])

        history = self.ctx.api.call("timer.history", {
            "id": tid, "caller": self._project_caller("p-notify")})
        self.assertTrue(history["last_run"]["ok"])
        self.assertEqual(len(history["history"]), 1)

    def test_tick_spawn_ticket_creates_ticket_with_meta(self):
        """到期 spawn_ticket：建工单，meta 记 source=timer/timer_id/slot，同槽位不重复建。"""
        before = len(self.ticket_calls)
        res = self._create({
            "project": "p-spawn", "kind": "once", "expr": _future_iso(120),
            "title": "周期出报告", "action": "spawn_ticket", "role": "role-a"})
        tid = res["id"]
        now = datetime.datetime.now(datetime.timezone.utc).timestamp() + 200
        self._tick(now=now)

        self.assertEqual(len(self.ticket_calls) - before, 1)
        ticket = self.ticket_calls[-1]
        self.assertEqual(ticket["project"], "p-spawn")
        meta = ticket["meta"]
        self.assertEqual(meta["source"], "timer")
        self.assertEqual(meta["timer_id"], tid)
        self.assertTrue(meta["slot"])

        # 同槽位重复 tick：不重复建单
        self._tick(now=now)
        self.assertEqual(len(self.ticket_calls) - before, 1)

    def test_idempotent_create_returns_original_id(self):
        """同义重复创建：返回原 id 且 deduped=true，只落一条记录。"""
        payload = {"project": "p-dedup", "kind": "cron", "expr": "0 9 * * *",
                   "title": "每天九点提醒", "action": "notify"}
        first = self._create(payload)
        again = self._create(payload)
        self.assertTrue(first["ok"])
        self.assertTrue(again["deduped"])
        self.assertEqual(again["id"], first["id"])
        self.assertEqual(len(self._records("p-dedup")), 1)

    def test_cross_project_read_write_delete_forbidden(self):
        """项目秘书跨项目：读取/修改/删除一律 forbidden_scope，且各留 deny 审计。"""
        pa, pb = "p-xpa", "p-xpb"
        res = self._create({"project": pa, "kind": "once",
                            "expr": _future_iso(3600), "title": "甲项目定时器",
                            "action": "notify"},
                           caller=self._project_caller(pa, "sa"))
        tid = res["id"]
        pb_caller = self._project_caller(pb, "sb")

        read = self.ctx.api.call("timer.list", {"project": pb, "caller": pb_caller})
        self.assertEqual(read["total"], 0, "跨项目读取不可见")

        for route in ("timer.update", "timer.pause", "timer.resume", "timer.delete"):
            denied = self.ctx.api.call(route, {"id": tid, "caller": pb_caller})
            self._apply(denied)
            self.assertFalse(denied["ok"], route)
            self.assertEqual(denied["code"], "forbidden_scope", route)

        denies = [r for r in self._audit_rows()
                  if r["target_id"] == tid and r["decision"] == "deny"
                  and r["caller_session"] == "sb"]
        self.assertGreaterEqual(len(denies), 4)
        for entry in denies:
            self.assertEqual(entry["reason"], "cross_project")

    def test_cross_ticket_forbidden_and_same_ticket_rw(self):
        """工单岗位：同项目其他工单的定时器不可见不可改；本工单可读写。"""
        project = "p-ticket"
        own, other = "T-101", "T-102"
        res = self._create({"project": project, "kind": "once",
                            "expr": _future_iso(3600), "title": "工单内提醒",
                            "action": "notify", "ticket": own},
                           caller=self._ticket_caller(project, own, "st1"))
        tid = res["id"]

        other_caller = self._ticket_caller(project, other, "st2")
        listed = self.ctx.api.call("timer.list", {"project": project,
                                                   "caller": other_caller})
        self.assertEqual(listed["items"], [], "跨工单不可见")
        denied = self.ctx.api.call("timer.update", {
            "id": tid, "caller": other_caller, "title": "改名"})
        self._apply(denied)
        self.assertFalse(denied["ok"])
        self.assertEqual(denied["code"], "forbidden_scope")

        deny = [r for r in self._audit_rows() if r["target_id"] == tid
                and r["decision"] == "deny" and r["caller_session"] == "st2"]
        self.assertEqual(len(deny), 1)
        self.assertEqual(deny[0]["reason"], "cross_ticket")

        own_caller = self._ticket_caller(project, own, "st1")
        allow = self.ctx.api.call("timer.update", {
            "id": tid, "caller": own_caller, "title": "工单内提醒（改）"})
        self.assertTrue(allow["ok"], allow)

    def test_project_secretary_manages_all_timers_in_project(self):
        """项目秘书可管本项目全部工单下的定时器；global 可跨项目查看。"""
        project = "p-manage"
        t1 = self._create({"project": project, "kind": "once",
                           "expr": _future_iso(3600), "title": "工单 A 提醒",
                           "action": "notify", "ticket": "T-201"},
                          caller=self._ticket_caller(project, "T-201", "sa"))
        t2 = self._create({"project": project, "kind": "once",
                           "expr": _future_iso(3600), "title": "工单 B 提醒",
                           "action": "notify", "ticket": "T-202"},
                          caller=self._ticket_caller(project, "T-202", "sb"))

        mine = self.ctx.api.call("timer.list", {
            "project": project, "caller": self._project_caller(project, "sp")})
        self.assertEqual(mine["total"], 2)

        other = self._create({"project": "p-manage-other", "kind": "once",
                              "expr": _future_iso(3600), "title": "别项目",
                              "action": "notify"},
                             caller=self._global_caller())
        all_view = self.ctx.api.call("timer.list", {"caller": self._global_caller("ga")})
        ids = {r["id"] for r in all_view["items"]}
        self.assertIn(t1["id"], ids)
        self.assertIn(t2["id"], ids)
        self.assertIn(other["id"], ids)

    def test_quota_exceeded(self):
        """超量创建 → quota_exceeded，deny 审计留痕。"""
        self.ctx.api.call("config.set_value",
                          {"key": "timer.max_per_project", "value": 1})
        try:
            p = "p-quota"
            first = self._create({"project": p, "kind": "once",
                                  "expr": _future_iso(3600), "title": "配额一",
                                  "action": "notify"})
            self.assertTrue(first["ok"], first)
            second = self._create({"project": p, "kind": "once",
                                    "expr": _future_iso(3600), "title": "配额二",
                                    "action": "notify"})
            self.assertFalse(second["ok"], second)
            self.assertEqual(second["code"], "quota_exceeded")
            deny = [r for r in self._audit_rows()
                    if r["target_project"] == p and r["decision"] == "deny"
                    and r["reason"] == "quota_exceeded"]
            self.assertEqual(len(deny), 1)
        finally:
            self.ctx.api.call("config.set_value",
                              {"key": "timer.max_per_project", "value": 20})

    def test_pause_resume_delete(self):
        """暂停 → 恢复 → 删除：状态翻转落档，allow 审计齐全。"""
        res = self._create({"project": "p-toggle", "kind": "cron",
                            "expr": "* * * * *", "title": "周期任务", "action": "notify"})
        tid = res["id"]
        caller = self._project_caller("p-toggle", "st")

        paused = self.ctx.api.call("timer.pause", {"id": tid, "caller": caller})
        self._apply(paused)
        self.assertTrue(paused["ok"])
        self.assertEqual(paused["status"], "paused")

        resumed = self.ctx.api.call("timer.resume", {"id": tid, "caller": caller})
        self._apply(resumed)
        self.assertTrue(resumed["ok"])
        self.assertEqual(resumed["status"], "active")

        deleted = self.ctx.api.call("timer.delete", {"id": tid, "caller": caller})
        self._apply(deleted)
        self.assertTrue(deleted["ok"])
        self.assertEqual(self._records("p-toggle"), [])

        allows = [r for r in self._audit_rows() if r["target_id"] == tid
                  and r["decision"] == "allow"]
        actions = {r["action"] for r in allows}
        self.assertIn("pause", actions)
        self.assertIn("resume", actions)
        self.assertIn("delete", actions)

    def test_bad_cron_bad_tz_rejected(self):
        """非法表达式 → bad_cron；非法时区 → bad_tz。"""
        bad = self._create({"project": "p-bad", "kind": "cron", "expr": "99 99 * *",
                            "title": "坏规则", "action": "notify"})
        self.assertFalse(bad["ok"])
        self.assertEqual(bad["code"], "bad_cron")

        tz = self._create({"project": "p-bad", "kind": "cron", "expr": "0 9 * * *",
                           "title": "坏时区", "action": "notify",
                           "tz": "Mars/Phobos"})
        self.assertFalse(tz["ok"])
        self.assertEqual(tz["code"], "bad_tz")

    def test_failure_preserved_visible_and_retryable(self):
        """触发失败：last_run 留可见错误、attempts 累加、槽位保留；恢复后可重试成功。"""
        res = self._create({"project": "p-fail", "kind": "once",
                            "expr": _future_iso(120), "title": "会失败的提醒",
                            "action": "notify"})
        tid = res["id"]

        def boom(ctx, payload):
            raise RuntimeError("push boom")
        self.ctx.api.substitute("secretary.push", boom)
        now = datetime.datetime.now(datetime.timezone.utc).timestamp() + 200
        first = self._tick(now=now)
        self.assertEqual(first["fired"], [])
        self.assertEqual(len(first["skipped"]), 1)

        history = self.ctx.api.call("timer.history", {
            "id": tid, "caller": self._project_caller("p-fail")})
        self.assertFalse(history["last_run"]["ok"])
        self.assertIn("boom", history["last_run"]["detail"])
        self.assertGreaterEqual(history["last_run"]["attempt"], 1)
        self.assertEqual(len(history["history"]), 1)

        # 恢复通道，再 tick：同槽位重试成功，不再失败留痕
        self._stub_push()
        second = self._tick(now=now)
        self.assertEqual(len(second["fired"]), 1)
        history2 = self.ctx.api.call("timer.history", {
            "id": tid, "caller": self._project_caller("p-fail")})
        self.assertTrue(history2["last_run"]["ok"])

    def test_index_groups_by_project(self):
        """定时器总览必须按项目分组，而不是只在表格里放一列项目名。"""
        for project in ("p-grp-a", "p-grp-b"):
            self._create({"project": project, "kind": "once",
                          "expr": _future_iso(7200), "title": "分组提醒 " + project,
                          "action": "notify"})
        idx = self.ctx.api.call("timer.index", {"caller": self._global_caller()})
        groups = {g["project"]: g for g in idx["groups"]}
        self.assertIn("p-grp-a", groups)
        self.assertIn("p-grp-b", groups)
        self.assertEqual(groups["p-grp-a"]["total"], 1)
        self.assertEqual(groups["p-grp-a"]["active"], 1)

    def test_history_rejects_cross_scope(self):
        """history 同样受作用域守卫：跨项目读取被拒并留 deny 审计。"""
        res = self._create({"project": "p-hist", "kind": "once",
                            "expr": _future_iso(3600), "title": "留档提醒",
                            "action": "notify"})
        tid = res["id"]
        denied = self.ctx.api.call("timer.history", {
            "id": tid, "caller": self._project_caller("p-hist-other", "sx")})
        self._apply(denied)
        self.assertFalse(denied["ok"])
        self.assertEqual(denied["code"], "forbidden_scope")
        deny = [r for r in self._audit_rows() if r["target_id"] == tid
                and r["decision"] == "deny"]
        self.assertEqual(len(deny), 1)


class _FakeNet:
    def __call__(self, ctx, payload):
        return {"ok": True, "status": 200, "headers": {},
                "items": [{"choices": [{"delta": {"content": "（测试）已完成。"},
                                        "finish_reason": "stop"}]}]}


if __name__ == "__main__":
    unittest.main()
