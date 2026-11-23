"""需求语言与需求引擎：语法、求值、守卫、循环、插拔。

引擎不认识业务，只认语句树；所以这里用一个假 api 就能把语言全部测完。
"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))

from ai_new.modules.agent_common.demand_engine.private import _engine, _lang  # noqa: E402


class FakeApi:
    """记录被调用的服务，返回可预测的结果。"""

    def __init__(self):
        self.calls = []
        self.fail_on = set()

    def call(self, name, payload=None, caller=None):
        self.calls.append((name, payload, caller))
        if name in self.fail_on:
            raise RuntimeError("boom")
        return {"called": name, "echo": (payload or {}).get("n")}


class FakeStorage:
    """假存储：需求引擎只通过"自己的数据目录"读需求，所以这里就是它的数据。"""

    def __init__(self, records):
        self.records = records      # {id: rec}

    def own(self, anchor):
        return self

    def list_dir(self, rel=""):
        return sorted(name + ".yaml" for name in self.records)

    def json_read(self, rel, default=None):
        key = rel.split("/")[-1][:-5]
        return self.records.get(key, default)

    def json_write(self, rel, obj):
        key = rel.split("/")[-1][:-5]
        self.records[key] = obj

    def yaml_read(self, rel, default=None):
        return self.json_read(rel, default)

    def yaml_write(self, rel, obj):
        self.json_write(rel, obj)

    def stat_size(self, rel):
        return len(str(self.records.get(rel.split("/")[-1][:-5], "")))

    def stat_mtime(self, rel):
        return 0.0


class FakeCtx:
    class ApiError(Exception):
        def __init__(self, msg, code="", status=400):
            super().__init__(msg)
            self.code = code
            self.status = status

    def __init__(self, records):
        self.storage = FakeStorage(records)
        self.api = FakeApi()


def _demand(**kw):
    rec = {"id": "probe", "title": "probe", "enabled": True, "on": ["x.happened"], "do": []}
    rec.update(kw)
    return rec


class LanguageTest(unittest.TestCase):
    def test_call_gets_payload_from_event(self):
        api = FakeApi()
        results = _lang.run([{"call": "ops.record"}], {"event": {"hook": "x.happened", "n": 7}}, api, None)
        self.assertTrue(results[0]["ok"])
        self.assertEqual(api.calls[0][0], "ops.record")
        self.assertEqual(api.calls[0][1]["hook"], "x.happened")

    def test_rejected_operators_raise(self):
        """判断/逻辑/集合/度量运算符已下沉模块纯函数，需求表达式求值必须拒绝。"""
        for op in ("==", "!=", "in", "and", "or", "not", "len", ">", "<", ">=", "<=", "+", "append"):
            with self.assertRaises(ValueError):
                _lang.eval_expr({"op": op, "a": {"lit": 1}, "b": {"lit": 2}}, {})

    def test_control_flow_statement_is_recorded_not_interpreted(self):
        """控制流语句已经不在语法里：引擎记一条失败，然后照常跑后续顺序语句。"""
        api = FakeApi()
        stmt = [{"when": {"get": "event.x"}, "then": [{"call": "a.b"}]},
                {"call": "good.route"}]
        results = _lang.run(stmt, {"event": {}}, api, None)
        self.assertFalse(results[0]["ok"])
        self.assertTrue(results[1]["ok"])
        self.assertEqual([c[0] for c in api.calls], ["good.route"])

    def test_failure_is_recorded_not_raised(self):
        api = FakeApi()
        api.fail_on = {"bad.route"}
        results = _lang.run([{"call": "bad.route"}, {"call": "good.route"}], {"event": {}}, api, None)
        self.assertFalse(results[0]["ok"])
        self.assertTrue(results[1]["ok"])

    def test_routes_of_lists_sequential_calls(self):
        stmt = [{"call": "a.b"}, {"call": "c.d"}]
        self.assertEqual(sorted(_lang.routes_of(stmt)), ["a.b", "c.d"])


class EngineTest(unittest.TestCase):
    def test_dispatch_only_runs_matching_demands(self):
        ctx = FakeCtx({"probe": _demand(do=[{"call": "ops.record"}])})
        engine = _engine.Engine(ctx)
        self.assertEqual(len(engine.dispatch("x.happened", {"hook": "x.happened"})), 1)
        self.assertEqual(engine.dispatch("y.happened", {"hook": "y.happened"}), [])

    def test_on_accepts_single_string(self):
        ctx = FakeCtx({"probe": _demand(on="x.happened", do=[{"call": "ops.record"}])})
        engine = _engine.Engine(ctx)
        self.assertEqual(engine.items()[0]["on"], ["x.happened"])
        self.assertEqual(len(engine.dispatch("x.happened", {"hook": "x.happened"})), 1)

    def test_items_do_not_carry_a_demand_level_guard(self):
        ctx = FakeCtx({"probe": _demand(do=[{"call": "ops.record"}])})
        item = _engine.Engine(ctx).items()[0]
        self.assertNotIn("when", item, "需求级 when 已随控制流一起移除")

    def test_disable_takes_effect_immediately(self):
        ctx = FakeCtx({"probe": _demand(do=[{"call": "ops.record"}])})
        engine = _engine.Engine(ctx)
        engine.set_enabled("probe", False)
        self.assertEqual(engine.dispatch("x.happened", {"hook": "x.happened"}), [])
        engine.set_enabled("probe", True)
        self.assertEqual(len(engine.dispatch("x.happened", {"hook": "x.happened"})), 1)

    def test_items_expose_routes_for_static_reading(self):
        ctx = FakeCtx({"probe": _demand(do=[{"call": "a.b"}])})
        item = _engine.Engine(ctx).items()[0]
        self.assertEqual(item["do"], ["a.b"])


if __name__ == "__main__":
    unittest.main()
