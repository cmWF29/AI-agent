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

    def test_view_index_ships_forms_of_keyless_pages(self):
        """表单是跨页能力：没有 key 的表单页也必须随目录下发，否则弹窗拿不到规格。"""
        ctx = FakeCtx({
            "projects": _demand(id="projects", view={"key": "projects", "sections": []}),
            "forms": _demand(id="forms", view={"forms": [{"id": "project.new"}]}),
        })
        index = _engine.Engine(ctx).view_index()
        form_ids = [f.get("id") for item in index
                    for f in ((item.get("view") or {}).get("forms") or [])]
        self.assertEqual(form_ids, ["project.new"])


    def test_manifest_counts_steps_views_callable_and_drift(self):
        """清单要把视图/可调/步骤数、非结构语句与 expect 漂移都摊平。"""
        ctx = FakeCtx({
            "v": _demand(id="v", title="视图", tags=["view"], view={"key": "v1"},
                         do=[{"call": "a.b", "as": "x", "with": {"k": 1}}, "raw-step"],
                         expect={"calls": ["a.b", "a.c"], "promise": "做一件事"}),
            "c": _demand(id="c", title="可调", tags=["write"], callable=True,
                         do=[{"call": "a.b"}]),
        })
        out = _engine.Engine(ctx).manifest()
        self.assertEqual(out["count"], 2)
        self.assertEqual(out["views"], 1)
        self.assertEqual(out["callable"], 1)
        self.assertGreaterEqual(out["steps"], 3)
        item = next(x for x in out["items"] if x["id"] == "v")
        self.assertEqual(item["view"], "v1")
        self.assertEqual(item["routes"], ["a.b"])
        self.assertEqual(item["drift"], ["a.c"])
        self.assertEqual(item["promise"], "做一件事")
        node_v = next(n for n in out["nodes"] if n["label"] == "v")
        leaf = next(x for x in node_v["children"] if x["path"] == "非结构语句")
        self.assertIn("raw-step", leaf["name"])
        self.assertTrue(out["groups"])

    def test_view_spec_and_missing_view(self):
        ctx = FakeCtx({"v": _demand(id="v", view={"key": "v1", "heading": "页"})})
        spec = _engine.Engine(ctx).view_spec("v1")
        self.assertEqual(spec["heading"], "页")
        with self.assertRaises(ctx.ApiError) as caught:
            _engine.Engine(ctx).view_spec("nope")
        self.assertEqual(caught.exception.code, "no_view")

    def test_console_menus_group_order_and_short_name(self):
        """菜单从视图声明汇总，不另存一份；组序/短名/底栏序都必须保留。"""
        ctx = FakeCtx({
            "v1": _demand(id="v1", view={"key": "v1", "nav": "v1",
                                         "menu": {"key": "m1", "label": "一",
                                                  "short": "1", "order": 2,
                                                  "group": {"name": "G", "order": 1},
                                                  "tab": {"order": 3}} }),
            "v2": _demand(id="v2", view={"key": "v2", "nav": "v2",
                                         "menu": {"label": "二", "order": 1}}),
            "console": {"brand": {"name": "Hive"}, "login": {"title": "登录"}},
        })
        shell = _engine.Engine(ctx).console()
        menus = shell["menus"]
        self.assertEqual([m["key"] for m in menus], ["m1", "v2"])
        self.assertEqual(menus[0]["short"], "1")
        self.assertEqual(menus[0]["group"], "G")
        self.assertEqual(menus[0]["tab_order"], 3)
        self.assertEqual(_engine.Engine(ctx).chrome()["brand"]["name"], "Hive")

    def test_screens_builds_pages_routes_controls_and_overlays(self):
        """页面地图/控件清单从视图自动推导：跳页、弹窗、父级返回都要有边。"""
        ctx = FakeCtx({
            "root": _demand(id="root", view={
                "key": "root", "screen_label": "首页", "menu": {"label": "首页", "order": 1},
                "actions": [{"label": "去详情", "view": "detail"},
                            {"label": "打开表单", "modal": "project.new"},
                            {"label": "刷新", "demand": "projects-list"}]}),
            "detail": _demand(id="detail", view={
                "key": "detail", "screen_label": "详情", "parent": {"view": "root"},
                "actions": [{"label": "返回", "view": "root"}]}),
            "console": {"screen_machine": {"entry": "view:root",
                                           "overlays": [{"key": "sidebar", "label": "侧栏"}]}},
        })
        out = _engine.Engine(ctx).screens()
        self.assertGreaterEqual(out["stats"]["pages"], 2)
        self.assertGreaterEqual(out["stats"]["edges"], 4)
        self.assertGreaterEqual(out["stats"]["controls"], 4)
        keys = {s["id"] for s in out["states"]}
        self.assertIn("overlay:form:project.new", keys)
        self.assertIn("overlay:sidebar", keys)
        page = next(p for p in out["pages"] if p["key"] == "view:root")
        self.assertTrue(page["entry"])
        self.assertIn("详情", [x["label"] for x in page["to"]])

    def test_callable_run_error_paths(self):
        """按名调用：不存在/未可调/已下线/无调用都要明确 code，不吞成 None。"""
        ctx = FakeCtx({
            "ok": _demand(id="ok", callable=True, do=[{"call": "a.b"}]),
            "view": _demand(id="view", callable=False, do=[{"call": "a.b"}]),
            "off": _demand(id="off", enabled=False, callable=True, do=[{"call": "a.b"}]),
            "empty": _demand(id="empty", callable=True, do=[]),
        })
        engine = _engine.Engine(ctx)
        out = engine.run_callable("ok")
        self.assertTrue(out["ok"])
        self.assertEqual(out["calls"], ["a.b"])
        self.assertEqual(engine.run_callable("off")["code"], "disabled")
        with self.assertRaises(ctx.ApiError) as caught:
            engine.run_callable("view")
        self.assertEqual(caught.exception.code, "not_callable")
        self.assertEqual(engine.run_callable("empty")["code"], "empty")
        with self.assertRaises(ctx.ApiError) as caught:
            engine.run_callable("nope")
        self.assertEqual(caught.exception.code, "no_demand")


if __name__ == "__main__":
    unittest.main()
