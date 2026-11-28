"""项目秘书验收：队列、批量合并、后发修正、幂等与失败保留。

无 Web 服务进程内装配（夹具同 test_core）：真实 build 装配模块，经需求入口跑闭环；
不监听端口、不依赖外部 LLM（net 桩替换）。
"""
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


class FakeNet:
    """测试桩：不联网，回一段固定 SSE 形状（编排与编解码都真跑）。"""

    def __call__(self, ctx, payload):
        return {"ok": True, "status": 200, "headers": {},
                "items": [{"choices": [{"delta": {"content": "（测试）已完成。"},
                                        "finish_reason": "stop"}]}]}


class SecretaryTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        root = Path(cls.tmp.name)
        stage(root)
        write_config(root, {
            "server": {"host": "127.0.0.1", "port": 0, "token": "t"},
            "llm": {"base_url": "http://stub.local/v1", "api_key": "k", "model": "stub"},
            "tickets": {"stall_check": {"enabled": False}},
        })
        os.environ["AI_NEW_DATA"] = str(root)
        cls.ctx = Context(root)
        cls.loaded = build(cls.ctx)
        cls.ctx.api.substitute("net.request", FakeNet())
        cls.ctx.api.substitute("net.request_stream", FakeNet())

    @classmethod
    def tearDownClass(cls):
        http = getattr(cls.ctx, "http", None)
        if http is not None:
            http.shutdown()  # 释放非守护 serve_forever 线程，否则进程挂住不退
        os.environ.pop("AI_NEW_DATA", None)
        shutil.rmtree(cls.tmp.name, ignore_errors=True)

    # ---- 夹具小工具 ----

    def _run(self, demand, input=None):
        return self.ctx.api.call("demand_engine.run",
                                 {"id": demand, "input": input or {}})

    def _project(self, name):
        return self._run("projects-create", {"name": name})["result"]["id"]

    def _push(self, project, msg_id, text, fields=None):
        return self._run("secretary-intake", {
            "project": project, "msg_id": msg_id, "text": text, "fields": fields})

    def _flush(self, project):
        return self._run("secretary-flush", {"project": project})

    def _queue(self, project):
        return self.ctx.api.call("secretary.list", {"project": project})

    def _ticket_record(self, project, ticket_id):
        row = self.ctx.api.call("store.read", {
            "module": "agent/tickets",
            "path": "projects/%s/tickets/%s/ticket.yaml" % (project, ticket_id)})
        return row.get("value") or {}

    def _timer(self, route, payload):
        res = self.ctx.api.call("timer." + route, payload)
        effects = (res or {}).get("effects") or []
        if effects:
            self.ctx.runtime.apply({"effect": effects})
        return res

    @staticmethod
    def _caller(scope, project, ticket="", role="pm", session="s-test"):
        return {"scope": scope, "project": project, "ticket": ticket,
                "role": role, "session": session}

    def _project_ticket_ids(self, project):
        listed = self.ctx.api.call("store.glob", {
            "module": "agent/tickets",
            "pattern": "projects/%s/tickets/T-*/ticket.yaml" % project})
        return [str(i).split("/")[3] for i in listed.get("items") or []]

    # ---- 用例 ----

    def test_concurrent_flush_on_same_project_creates_one_ticket(self):
        """同一项目两条消息同时触发 flush：必须串行，只建一张单，消息不丢。"""
        import threading
        project = self._project("秘书并发处理项目")
        self._push(project, "c1", "并发消息一")
        self._push(project, "c2", "并发消息二")
        box = []

        def run():
            box.append(self._flush(project))

        threads = [threading.Thread(target=run) for _ in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(len(box), 2)
        self.assertTrue(all(x["result"]["ok"] for x in box))
        queue = self._queue(project)
        self.assertEqual(queue["counts"]["pending"], 0)
        self.assertEqual(queue["counts"]["merged"], 2)
        self.assertEqual(len(self._project_ticket_ids(project)), 1)

    def test_batch_number_continues_after_restart(self):
        """进程重启后批次号必须从磁盘最大号续，不能从 B-0001 重来撞旧幂等键。"""
        project = self._project("restart-seq")
        self._push(project, "r1", "第一条")
        first = self._flush(project)["result"]["batch"]["batch_id"]
        # 模拟重启：进程内发号器清空；磁盘批次还在。
        self.ctx.storage._counters.clear()
        self._push(project, "r2", "第二条")
        second = self._flush(project)["result"]["batch"]["batch_id"]
        self.assertNotEqual(first, second, "重启后批次号复用了 %s" % first)

    def test_autoflush_demand_processes_queue_without_manual_flush(self):
        """入队触发的自动处理需求：派发 secretary.queued 就能建单，不需要有人手点。"""
        project = self._project("秘书自动处理项目")
        pushed = self._push(project, "auto1", "第一个工单：扫描项目源码并整理架构")
        self.assertTrue(pushed["result"]["created"], pushed)
        got = self.ctx.demand_engine.dispatch("secretary.queued", {
            "hook": "secretary.queued",
            "level": "info",
            "data": {"project": project, "msg_id": "auto1"},
        })
        self.assertTrue(got)
        self.assertEqual(got[0]["demand"], "secretary-autoflush")
        queue = self._queue(project)
        self.assertEqual(queue["counts"]["pending"], 0)
        self.assertEqual(queue["counts"]["merged"], 1)
        self.assertTrue(self._project_ticket_ids(project))

    def test_batch_merge_three_into_one_ticket(self):
        """3 条消息合并成 1 张工单；后发修正覆盖同字段，来源可追溯。"""
        project = self._project("秘书批次合并项目")
        self._push(project, "m1", "做一个登录页",
                   {"goal": "登录页", "acceptance": "用户名密码登录"})
        # 后发修正：把目标从“登录页”改成“登录注册页”
        self._push(project, "m2", "改成登录加注册", {"goal": "登录注册页"})
        self._push(project, "m3", "不要引入新框架", {"constraints": "不引入新框架"})

        res = self._flush(project)
        self.assertTrue(res["result"]["ok"], res["result"])
        ticket_id = res["result"]["ticket"]
        self.assertTrue(ticket_id)

        queue = self._queue(project)
        self.assertEqual(queue["counts"]["merged"], 3)
        self.assertEqual(queue["counts"]["pending"], 0)
        # 群聊流：3 条人消息在右，1 条批次回执在左；队列明细仍留在 rows/batches
        self.assertEqual([m["role"] for m in queue["messages"]],
                         ["user", "user", "user", "secretary"])
        self.assertEqual(queue["messages"][0]["text"], "做一个登录页")
        self.assertIn(ticket_id, queue["messages"][-1]["text"])
        self.assertEqual([m["display"] for m in queue["members"]], ["我", "群聊秘书"])

        rec = self._ticket_record(project, ticket_id)
        sec = (rec.get("meta") or {}).get("secretary") or {}
        self.assertEqual(sorted(sec.get("msg_ids") or []), ["m1", "m2", "m3"])
        # 后发优先：goal 被 m2 覆盖，来源记到 m2
        self.assertEqual(sec["brief"]["goal"], "登录注册页")
        self.assertEqual(sec["sources"]["goal"], "m2")
        self.assertEqual(sec["brief"]["constraints"], "不引入新框架")
        # 一批只建一张单
        self.assertEqual(self._project_ticket_ids(project), [ticket_id])

    def test_idempotent_repush_and_reflush(self):
        """同 msg_id 重复投递只入队一次；同批次重复 flush 不二次建单。"""
        project = self._project("秘书幂等项目")
        self._push(project, "m1", "做一个导出功能")
        self._push(project, "m2", "导出 CSV")
        first = self._flush(project)
        self.assertTrue(first["result"]["ok"])
        first_ticket = first["result"]["ticket"]

        # 重复投递同一批 msg_id：不重复入队
        self._push(project, "m1", "做一个导出功能")
        self._push(project, "m2", "导出 CSV")
        queue = self._queue(project)
        self.assertEqual(len(queue["rows"]), 2)

        # 再 flush：队列已无待处理（空批），不建第二张单
        second = self._flush(project)
        self.assertTrue(second["result"]["ok"])
        self.assertTrue(second["result"].get("empty"))
        self.assertEqual(self._project_ticket_ids(project), [first_ticket])

    def test_failure_preserves_queue_and_shows_error(self):
        """建单失败：消息回待处理、attempts+1、last_error 可见，消息不丢、不出队。"""
        project = self._project("秘书失败保留项目")
        self._push(project, "m1", "需求一")
        self._push(project, "m2", "需求二")
        self._push(project, "m3", "需求三")

        routes = self.ctx.api._routes
        original = routes["tickets.create"]["fn"]

        def boom(ctx, payload):
            raise RuntimeError("create boom")

        self.ctx.api.substitute("tickets.create", boom)
        try:
            res = self._flush(project)
        finally:
            routes["tickets.create"]["fn"] = original

        self.assertFalse(res["result"]["ok"])
        self.assertEqual(res["result"]["code"], "flush_failed")

        queue = self._queue(project)
        self.assertEqual(len(queue["rows"]), 3, "失败后消息一条都不能丢")
        self.assertEqual(queue["counts"]["pending"], 3)
        self.assertEqual(queue["counts"]["merged"], 0)
        for row in queue["rows"]:
            self.assertTrue(row["last_error"], "错误必须可见")
            self.assertGreaterEqual(row["attempts"], 1)
        # 失败不留工单
        self.assertEqual(self._project_ticket_ids(project), [])

    def test_empty_flush_creates_no_ticket(self):
        """空队列 flush：不建单、不造批次。"""
        project = self._project("秘书空队列项目")
        res = self._flush(project)
        self.assertTrue(res["result"]["ok"])
        self.assertTrue(res["result"]["empty"])
        self.assertEqual(self._project_ticket_ids(project), [])
        queue = self._queue(project)
        self.assertEqual(queue["batches"], [])

    def test_discarded_message_excluded_from_merge(self):
        """撤回的消息不参与合并：只并入未撤回的那条。"""
        project = self._project("秘书撤回项目")
        self._push(project, "m1", "先写方案 A")
        self._push(project, "m2", "再写方案 B")
        self._run("secretary-discard", {"project": project, "msg_id": "m1"})

        res = self._flush(project)
        self.assertTrue(res["result"]["ok"])
        ticket_id = res["result"]["ticket"]
        rec = self._ticket_record(project, ticket_id)
        sec = (rec.get("meta") or {}).get("secretary") or {}
        self.assertEqual(sec.get("msg_ids"), ["m2"])

        queue = self._queue(project)
        m1 = next(r for r in queue["rows"] if r["msg_id"] == "m1")
        self.assertEqual(m1["status"], "discarded")

    # ---- status 契约：错误路径结构化降级，不抛裸异常、不回 500 空体 ----

    def test_status_missing_project_returns_structured_error(self):
        """缺项目：回包 ok:false + 明确错误码，调用方可整块降级。"""
        res = self.ctx.api.call("secretary.status", {"project": ""},
                                caller=None, direct=True)
        self.assertFalse(res["ok"])
        self.assertEqual(res["code"], "missing_project")
        self.assertTrue(res.get("error") is not None)

    def test_status_unknown_message_degrades_not_found(self):
        """给了 msg_id 但队列里找不到：ok:false/not_found，不静默当成空状态。"""
        project = self._project("秘书状态未知消息项目")
        self._push(project, "m1", "需求一")
        res = self.ctx.api.call("secretary.status",
                                 {"project": project, "msg_id": "no-such-msg"},
                                 caller=None, direct=True)
        self.assertFalse(res["ok"])
        self.assertEqual(res["code"], "not_found")

    def test_status_known_message_reports_ok(self):
        """正常路径：ok:true 且带状态枚举与合法迁移。"""
        project = self._project("秘书状态正常项目")
        self._push(project, "m1", "需求一")
        res = self.ctx.api.call("secretary.status",
                                 {"project": project, "msg_id": "m1"},
                                 caller=None, direct=True)
        self.assertTrue(res["ok"])
        self.assertIn("pending", res["statuses"])
        self.assertIn("processing", res["transitions"]["pending"])

    def test_status_and_list_degrade_when_state_unavailable(self):
        """读档/成形异常不裸抛：status 与 list 都回结构化 ok:false。"""
        project = self._project("秘书存储异常项目")
        self._push(project, "m1", "需求一")
        original = self.ctx.api._routes["store.read"]["fn"]

        def boom(ctx, payload):
            raise RuntimeError("storage down")

        self.ctx.api.substitute("store.read", boom)
        try:
            status = self.ctx.api.call("secretary.status", {"project": project},
                                       caller=None, direct=True)
            self.assertFalse(status["ok"])
            self.assertEqual(status["code"], "state_unavailable")
            listing = self.ctx.api.call("secretary.list", {"project": project},
                                        caller=None, direct=True)
            self.assertFalse(listing["ok"])
            self.assertEqual(listing["code"], "state_unavailable")
        finally:
            self.ctx.api._routes["store.read"]["fn"] = original

    def test_duplicate_message_flush_builds_single_ticket(self):
        """合并幂等：同一 msg_id 重复投递只入队一次；一批 flush 只建一张单。"""
        project = self._project("秘书重复消息幂等项目")
        self._push(project, "m1", "先写方案 A")
        self._push(project, "m1", "改成方案 B（重复投递，应被忽略）")
        self._push(project, "m2", "再补验收标准")

        queue = self._queue(project)
        self.assertEqual(len(queue["rows"]), 2, "重复 msg_id 不该二次入队")

        first = self._flush(project)
        self.assertTrue(first["result"]["ok"], first["result"])
        ticket_id = first["result"]["ticket"]
        self.assertTrue(ticket_id)

        # 再 flush：队列已空，不建第二张单，工单仍是同一张。
        second = self._flush(project)
        self.assertTrue(second["result"]["ok"])
        self.assertTrue(second["result"].get("empty"))
        self.assertEqual(self._project_ticket_ids(project), [ticket_id])

    def test_status_ok_with_content_under_enforce(self):
        """enforce 跨模块闸下：status/list 正常回包，不被 store→archive 内部协作误拒。

        回归：store 透明读路径回落 archive.resolve_abs 时曾继承外层业务身份，
        秘书状态块被 403 internal_call_unregistered 整块降级。
        """
        self.ctx.cfg.setdefault("api", {})["internal_call_mode"] = "enforce"
        try:
            project = self._project("秘书 enforce 状态项目")
            self._push(project, "m1", "做一个登录页")
            status = self.ctx.api.call("secretary.status", {"project": project},
                                       caller=None, direct=True)
            self.assertTrue(status["ok"], status)
            self.assertIn("pending", status["statuses"])
            self.assertIn("processing", status["transitions"]["pending"])
            listing = self.ctx.api.call("secretary.list", {"project": project},
                                        caller=None, direct=True)
            self.assertTrue(listing["ok"], listing)
            self.assertEqual(len(listing["rows"]), 1)
        finally:
            self.ctx.cfg["api"]["internal_call_mode"] = "warn"

    def test_archive_resolve_abs_registered_with_matching_contract(self):
        """archive.resolve_abs 确由 archive 注册，入参 abs / 出参 exists,raw 签名匹配。"""
        route = self.ctx.api.route("archive.resolve_abs")
        self.assertIsNotNone(route, "archive.resolve_abs 未注册")
        self.assertEqual(route["module"], "archive")
        contract = self.ctx.api.contract("archive.resolve_abs")
        self.assertIn("abs", (contract.get("in") or {}))
        out = contract.get("out") or {}
        self.assertIn("exists", out)
        self.assertIn("raw", out)

    # ---- 定时器接线：直连真实 timer 路由，作用域隔离由 timer 侧裁决，秘书侧断言可见拒绝 ----

    def test_timer_create_dedup_and_project_scoped_list(self):
        """同义重复建定时器幂等去重；秘书代理只列本项目，不暴露别的项目。"""
        pa = self._project("定时器甲项目")
        pb = self._project("定时器乙项目")
        self._timer("create", {"project": pa, "kind": "cron", "expr": "0 9 * * *",
                               "title": "每天九点提醒", "action": "notify"})
        again = self._timer("create", {"project": pa, "kind": "cron", "expr": "0 9 * * *",
                                       "title": "每天九点提醒", "action": "notify"})
        self.assertTrue(again["deduped"])

        mine = self._run("secretary-timers", {"project": pa})["result"]
        self.assertEqual(len(mine["items"]), 1)
        other = self._run("secretary-timers", {"project": pb})["result"]
        self.assertEqual(other["items"], [])

    def test_timer_forbidden_scope_is_visible(self):
        """跨项目写操作被 timer 侧拒绝；返回 forbidden_scope，秘书侧不静默吞掉。"""
        pa = self._project("越权甲项目")
        pb = self._project("越权乙项目")
        self._timer("create", {"project": pa, "kind": "once",
                               "expr": "2026-11-24T09:00:00",
                               "title": "单次提醒", "action": "notify"})
        # 以 pa 调用方身份往 pb 落定时器：作用域守卫拒绝
        denied = self._timer("create", {
            "project": pb, "kind": "once", "expr": "2026-11-25T09:00:00",
            "title": "跨项目提醒", "action": "notify",
            "caller": self._caller("project", pa)})
        self.assertFalse(denied["ok"])
        self.assertEqual(denied["code"], "forbidden_scope")

    def test_ticket_scope_isolated_within_project(self):
        """同项目内：工单 T1 的定时器对 T2 不可见；T2 写 T1 被拒；T1 可读写自己的。"""
        project = self._project("工单作用域项目")
        c1 = self._caller("ticket", project, ticket="T-0001", role="developer")
        c2 = self._caller("ticket", project, ticket="T-0002", role="tester")
        made = self._timer("create", {
            "project": project, "ticket": "T-0001", "title": "T1 提醒",
            "kind": "cron", "expr": "0 9 * * *", "action": "notify", "caller": c1})
        self.assertTrue(made["ok"], made)
        tid = made["id"]

        # T2 列表看不到 T1 的定时器
        seen_by_t2 = self._timer("list", {"project": project, "caller": c2})
        self.assertEqual([t["id"] for t in seen_by_t2["items"]], [])
        # T1 自己看得到
        seen_by_t1 = self._timer("list", {"project": project, "caller": c1})
        self.assertEqual([t["id"] for t in seen_by_t1["items"]], [tid])

        # T2 暂停/删除 T1：forbidden_scope
        denied_pause = self._timer("pause", {"id": tid, "caller": c2})
        self.assertFalse(denied_pause["ok"])
        self.assertEqual(denied_pause["code"], "forbidden_scope")
        denied_del = self._timer("delete", {"id": tid, "caller": c2})
        self.assertFalse(denied_del["ok"])
        self.assertEqual(denied_del["code"], "forbidden_scope")

        # T1 暂停自己的定时器：放行
        own_pause = self._timer("pause", {"id": tid, "caller": c1})
        self.assertTrue(own_pause["ok"], own_pause)

    def test_secretary_caller_never_global(self):
        """秘书侧 caller 只由会话记录构造：project/ticket 作用域，绝不抬到 global。"""
        from ai_new.modules.agent.secretary import _session_caller
        pm = _session_caller({"id": "s1", "project": "P", "role": "pm", "kind": "secretary"})
        self.assertEqual(pm["scope"], "project")
        self.assertEqual(pm["ticket"], "")
        role = _session_caller({"id": "s2", "project": "P", "ticket": "T-1",
                                "role": "developer", "kind": "role"})
        self.assertEqual(role["scope"], "ticket")
        self.assertNotIn(pm["scope"], ("global",))
        self.assertNotIn(role["scope"], ("global",))

    def test_timer_notify_enqueue_idempotent_and_merged(self):
        """timer notify 入队：来源/定时器 id/slot 可见；同 slot 重复投递不丢不重；随批合并进工单。"""
        project = self._project("定时器通知项目")
        notify = {"project": project, "msg_id": "timer:tm-001:s1",
                  "text": "提醒：站会九点开始", "source": "timer",
                  "timer_id": "tm-001", "slot": "s1"}
        self._run("secretary-intake", notify)
        self._run("secretary-intake", dict(notify))  # 同 slot 重复投递

        queue = self._queue(project)
        self.assertEqual(len(queue["rows"]), 1)
        row = queue["rows"][0]
        self.assertEqual(row["source"], "timer")
        self.assertEqual(row["timer_id"], "tm-001")
        self.assertEqual(row["slot"], "s1")

        self._run("secretary-intake", {"project": project, "msg_id": "u1",
                                        "text": "整理站会纪要"})
        res = self._flush(project)
        self.assertTrue(res["result"]["ok"], res["result"])
        rec = self._ticket_record(project, res["result"]["ticket"])
        sec = (rec.get("meta") or {}).get("secretary") or {}
        self.assertEqual(sorted(sec.get("msg_ids") or []), ["timer:tm-001:s1", "u1"])

    def test_spawn_ticket_same_slot_no_duplicate(self):
        """spawn_ticket 同槽位重复触发不重复建单（工单内容一致走建单幂等）。"""
        project = self._project("spawn 建单项目")
        meta = {"source": "timer", "timer_id": "tm-001", "slot": "s1"}
        payload = {"title": "定时工单", "goal": "到点建工单", "project": project,
                   "meta": {"timer": meta}, "auto_retrospective": False}
        first = self.ctx.runtime.call("ticket-create", payload)
        second = self.ctx.runtime.call("ticket-create", payload)
        self.assertEqual(first["id"], second["id"])
        self.assertEqual(self._project_ticket_ids(project), [first["id"]])

    def test_registered_timer_tools_are_scoped(self):
        """定时器工具登记给 pm/secretary；参数含周期/标题；project 由会话上下文注入。"""
        tools = {t["name"]: t for t in self.ctx.tools.list_tools()}
        for name in ("timer_create", "timer_list", "timer_pause",
                     "timer_resume", "timer_delete"):
            self.assertIn(name, tools)
            self.assertIn("secretary", tools[name]["kinds"])
            self.assertIn("pm", tools[name]["kinds"])
        create = tools["timer_create"]
        names = [p["name"] for p in create["params"]]
        self.assertIn("expr", names)
        self.assertIn("title", names)
        self.assertIn("action", names)


if __name__ == "__main__":
    unittest.main()
