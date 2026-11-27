"""工单/资源库/云归档接缝：归档只读理由、角色视图、目标归一与库路由钩子。"""
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))

from ai_new.modules.agent import library
from ai_new.modules.agent.cloud.private import _archive
from ai_new.modules.agent.tickets.private import _pure as tickets_pure


class TicketLockTest(unittest.TestCase):
    def test_archived_reason_from_template(self):
        out = tickets_pure.threadp({
            "rec": {"roles": []},
            "ticket": {"status": "open", "id": "t1"},
            "project_archived": True,
            "tpl_lock": {"archived": "项目已归档"},
            "messages": [],
        })
        self.assertTrue(out["locked"])
        self.assertEqual(out["lock_reason"], "项目已归档")

    def test_closed_reason_from_template(self):
        out = tickets_pure.threadp({
            "rec": {}, "ticket": {"status": "closed"}, "messages": [],
            "tpl_lock": {"closed": "已结单"},
        })
        self.assertTrue(out["locked"])
        self.assertEqual(out["lock_reason"], "已结单")

    def test_roles_view(self):
        self.assertEqual(tickets_pure.roles({"rec": {"roles": [{"role": "pm"}]}})["items"],
                         [{"role": "pm"}])
        self.assertEqual(tickets_pure.roles({})["items"], [])

    def test_resolve_target(self):
        self.assertEqual(tickets_pure.resolve_target({"rec": {"pm": "s1"}, "target": "pm"}),
                         {"session": "s1", "role": "pm"})
        self.assertEqual(tickets_pure.resolve_target({"rec": {"roles": [
            {"role": "dev", "session": "s2"}]}, "target": "dev"}),
                         {"session": "s2", "role": "dev"})
        self.assertEqual(tickets_pure.resolve_target({"rec": {}, "target": "x"}),
                         {"session": "", "role": ""})

    def test_stamp_note_keeps_existing_to(self):
        msgs = tickets_pure._stamp([{"role": "user", "kind": "note", "to": "dev"}],
                                   "s1", "system", 100.0, display="pm")
        self.assertEqual(msgs[0]["to"], "dev")
        self.assertEqual(msgs[0]["actor"], "system")
        self.assertEqual(msgs[0]["at"], 100.0)

    def test_stamp_uses_neighbor_time_for_missing_human_message(self):
        # 人类消息落盘没有 at，前后 assistant 有真实时间：必须贴着后一条排，
        # 不能按会话创建时刻铺到最前面，否则页面底部看不到新消息。
        msgs = tickets_pure._stamp([
            {"role": "assistant", "content": "a", "at": 100.0},
            {"role": "user", "content": "human", "kind": "human"},
            {"role": "assistant", "content": "b", "at": 200.0},
            {"role": "user", "content": "tail", "kind": "human"},
        ], "s1", "pm", 50.0)
        self.assertAlmostEqual(msgs[1]["at"], 199.9999)
        self.assertAlmostEqual(msgs[3]["at"], 200.0001)
        self.assertLess(msgs[1]["at"], 200.0)
        self.assertGreater(msgs[3]["at"], 200.0)


class LibraryHandlerTest(unittest.TestCase):
    def _handler(self):
        return library._as_handler(lambda p: p)

    def test_supplied_paths_kept(self):
        ctx = mock.Mock()
        ctx.api.call.return_value = {"value": {"a": 1}}
        got = self._handler()(ctx, {"paths": {"x": "y"}})
        self.assertEqual(got["paths"], {"x": "y"})
        self.assertEqual(got["tpl"], {"a": 1})

    def test_paths_from_config_when_absent(self):
        ctx = mock.Mock()
        ctx.api.call.side_effect = lambda name, payload=None, caller=None: (
            {"value": {"i": "messages.yaml"}} if name == "store.read"
            else {"value": {"root": "docs"}})
        got = self._handler()(ctx, None)
        self.assertEqual(got["paths"], {"root": "docs"})
        self.assertEqual(got["tpl"], {"i": "messages.yaml"})


class CloudArchiveSeamTest(unittest.TestCase):
    def test_wired(self):
        ctx = mock.Mock()
        ctx.api.call.return_value = {"rows": [{"path": "a"}]}
        self.assertEqual(_archive.list_archived(ctx), {"rows": [{"path": "a"}], "seam": "wired"})

    def test_unwired_falls_back(self):
        ctx = mock.Mock()
        ctx.api.call.side_effect = RuntimeError("no route")
        got = _archive.list_archived(ctx, category="c", limit=3)
        self.assertEqual(got["rows"], [])
        self.assertEqual(got["seam"], "adapter_unwired")
        self.assertEqual(got["reason"], "RuntimeError")


if __name__ == "__main__":
    unittest.main()
