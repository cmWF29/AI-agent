"""需求契约：每条业务需求自带预期（输入 / 动作 / 输出），并且被验收清单点名。

为什么这是"显式化需求"而不是额外负担：
- 需求本来就隐含了预期：在什么点上、拿到什么输入、调哪些服务、结果长什么样。
  不写出来，这四件事就只存在于作者脑子里，等于运行时糊浆。
- 写出来之后三件事同时成立：静态读得懂（calls 必须出现在 do 里）、
  跑得起来（用 given 真投一次）、下线时留痕（需求没了，它的用例一起失效）。
- 所以规则是双向闭合的：**没有用例的需求不许上线，没有需求可测的用例也不许存在**。
"""
import yaml
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))

from ai_new.modules.agent_common.demand_engine.private import _engine, _lang  # noqa: E402
import _fixtures  # noqa: E402

DEMANDS = _fixtures.module_data("agent_common", "demand_engine") / "demands"
CHECKS = _fixtures.module_data("agent_test", "agent_test") / "checks.yaml"


def demand_files():
    return sorted(DEMANDS.glob("*.yaml"))


def load_all():
    return [yaml.safe_load(p.read_text(encoding="utf-8")) for p in demand_files()]


def claimed():
    """验收清单里声明覆盖了哪些需求。"""
    record = yaml.safe_load(CHECKS.read_text(encoding="utf-8"))
    out = set()
    for check in record.get("checks") or []:
        out.update(check.get("demands") or [])
    return out


def all_expected():
    """所有需求预期的服务并集：同一个点上可以有多条需求，桩要把它们全备齐。"""
    routes = set()
    for rec in load_all():
        exp = rec.get("expect") or {}
        routes.update(exp.get("calls") or [])
        for case in exp.get("cases") or []:
            routes.update(case.get("calls") or [])
    # B1 下沉：聚合能力内部编排的路由也属预期，桩要备 handler、无主动作校验要认得。
    cap_path = ROOT / "ai_new/modules/agent_common/api/data/capability-routes.yaml"
    if cap_path.is_file():
        manifest = yaml.safe_load(cap_path.read_text(encoding="utf-8")) or {}
        for name, spec in (manifest.get("capabilities") or {}).items():
            if name in routes:
                routes.update(spec.get("calls") or [])
    return sorted(routes)


def _cases(rec):
    """一条需求可以带多组 given/calls；单值 given 退化成一组。"""
    exp = rec.get("expect") or {}
    cases = exp.get("cases")
    if cases:
        for case in cases:
            yield {"given": case.get("given") or exp.get("given") or {},
                   "calls": case.get("calls") or [], "payload": case.get("payload") or {}}
    else:
        yield {"given": exp.get("given") or {}, "calls": exp.get("calls") or [],
               "payload": exp.get("payload") or {}}


def _shape(route):
    """桩回一个通用形状：需求里常见的字段名都有值，避免 None 参与拼接。"""
    shape = {"ok": True, "route": route, "value": {}, "items": [], "id": "demo",
             "exists": False, "ts": 1000.0, "text": "", "prompt": "", "counts": {},
             "modules": [], "messages": [], "content": "", "total": 0,
             "token": "demo-token", "hex": "abc"}
    if route == "store.read_text":
        shape["value"] = ""  # 空文件：文本落在 value 上
    if route == "config.get":
        shape["value"] = {"username": "admin", "password_hash": "abc",
                          "salt": "s", "ttl": 86400}
    return shape


class _Api:
    """记录器：记下每条被调用的路由和载荷，再返回一个固定结果。"""

    def __init__(self, routes):
        self.calls = []
        self.handlers = {route: (lambda payload, caller=None, r=route: _shape(r))
                         for route in routes}
        self.ApiError = RuntimeError

    def register(self, route, fn, description=""):
        self.handlers[route] = fn

    def call(self, route, payload, caller=None, **_):
        self.calls.append({"route": route, "payload": payload, "caller": caller})
        handler = self.handlers.get(route)
        if handler is None:
            raise RuntimeError("需求调用了未注册的服务: %s" % route)
        return handler(payload, caller)


class _Storage:
    """读真实 data/demands，写落在内存覆盖层（用例不碰用户数据，但下线要真生效）。"""

    def __init__(self):
        self.written = {}

    def own(self, anchor):
        """引擎读"自己的数据"：这里就是 demand_engine 的数据目录。"""
        return self

    def list_dir(self, rel=""):
        return [p.name for p in sorted(
            (_fixtures.module_data("agent_common", "demand_engine") / rel).glob("*"))]

    def list_data_dir(self, rel):
        names = self.list_dir(rel)
        for key in self.written:
            if key.startswith(rel + "/") and key.rsplit("/", 1)[-1] not in names:
                names.append(key.rsplit("/", 1)[-1])
        return sorted(names)

    def json_read(self, rel, default=None):
        if rel in self.written:
            return self.written[rel]
        path = _fixtures.module_data("agent_common", "demand_engine") / rel
        return yaml.safe_load(path.read_text(encoding="utf-8")) if path.is_file() else default

    def yaml_read(self, rel, default=None):
        return self.json_read(rel, default)

    def json_write(self, rel, obj):
        self.written[rel] = obj

    def yaml_write(self, rel, obj):
        self.json_write(rel, obj)


class _Ctx:
    def __init__(self, api, storage):
        self.api = api
        self.storage = storage
        self.ApiError = RuntimeError


class DemandContractTest(unittest.TestCase):
    def test_every_demand_declares_expect(self):
        """预期三件事：在哪个点（given.on）、什么输入（given.event）、调什么（calls）。"""
        problems = []
        for rec in load_all():
            exp = rec.get("expect") or {}
            given = exp.get("given") or {}
            if rec.get("callable"):
                # 编排需求不挂在点上，它被"按名调用"，所以预期的是 input
                if not isinstance(given.get("input"), dict):
                    problems.append("%s 是 callable 需求，必须有 expect.given.input" % rec.get("id"))
                if rec.get("on"):
                    problems.append("%s 是 callable 需求，不该再挂 hook 点" % rec.get("id"))
            else:
                if not given.get("on"):
                    problems.append("%s 没有 expect.given.on" % rec.get("id"))
                elif given["on"] not in (rec.get("on") or []):
                    problems.append("%s 的 given.on 不在自己的 on 列表里: %s"
                                    % (rec.get("id"), given["on"]))
                if not isinstance(given.get("event"), dict):
                    problems.append("%s 的 given.event 必须是对象" % rec.get("id"))
            if not exp.get("calls"):
                problems.append("%s 没有 expect.calls（预期要调哪些服务）" % rec.get("id"))
        self.assertEqual(problems, [], "需求预期不完整: %s" % problems)

    def test_expect_calls_exist_in_do(self):
        """预期里写的服务调用必须真在语句树里 —— 预期不能凭空写。"""
        problems = []
        for rec in load_all():
            declared = set(_lang.routes_of(rec.get("do")))
            for route in (rec.get("expect") or {}).get("calls") or []:
                if route not in declared:
                    problems.append("%s 预期调 %s，但 do 里没有" % (rec.get("id"), route))
        self.assertEqual(problems, [], "预期与语句树不一致: %s" % problems)

    def test_every_demand_is_claimed_by_a_check(self):
        """没有用例的需求不许上线。"""
        orphans = [rec.get("id") for rec in load_all()
                   if rec.get("id") not in claimed()]
        self.assertEqual(orphans, [], "这些需求没有被任何验收清单点名: %s" % orphans)

    def test_checks_claim_only_existing_demands(self):
        """反过来：清单不许点名不存在的需求（需求下线后清单必须跟着改）。"""
        ids = {rec.get("id") for rec in load_all()}
        ghosts = sorted(claimed() - ids)
        self.assertEqual(ghosts, [], "验收清单点名了不存在的需求: %s" % ghosts)

    def test_expectation_holds(self):
        """真投一次：按 given 触发，调用顺序和载荷必须与预期一致。支持多组 cases。"""
        for rec in load_all():
            exp = rec.get("expect") or {}
            for case in _cases(rec):
                given = case["given"]
                routes = case["calls"]
                api = _Api(all_expected())
                ctx = _Ctx(api, _Storage())
                engine = _engine.Engine(ctx)
                if rec.get("callable"):
                    engine.run_callable(rec.get("id"), given.get("input") or {})
                    results = []
                else:
                    results = engine.dispatch(given.get("on"), given.get("event") or {})

                fired = [c["route"] for c in api.calls]
                position = 0
                for route in routes:
                    found = next((i for i in range(position, len(fired)) if fired[i] == route), None)
                    self.assertIsNotNone(found, "%s 预期调 %s，实际只调了 %s"
                                         % (rec.get("id"), routes, fired))
                    position = found + 1
                mine_results = [r for r in results if r.get("demand") == rec.get("id")]
                self.assertTrue(all(r.get("ok") for r in mine_results),
                                "%s 执行出现错误: %s" % (rec.get("id"), mine_results))

                scope = {"event": given.get("event") or {}, "hook": given.get("on"),
                         "input": given.get("input") or {}}
                for call in api.calls:
                    for key, expr in ((case["payload"].get(call["route"])) or {}).items():
                        self.assertEqual(
                            call["payload"].get(key), _lang.eval_expr(expr, scope),
                            "%s: %s 收到的 %s 与预期不符" % (rec.get("id"), call["route"], key))

    def test_no_route_fires_without_an_expectation(self):
        """这个点上任何被调起的服务，都必须属于某条需求的预期 —— 没有无主动作。"""
        known = set(all_expected())
        for rec in load_all():
            given = (rec.get("expect") or {}).get("given") or {}
            api = _Api(known)
            ctx = _Ctx(api, _Storage())
            _engine.Engine(ctx).dispatch(given.get("on"), given.get("event") or {})
            stray = sorted({c["route"] for c in api.calls} - known)
            self.assertEqual(stray, [], "%s 触发了没有预期解释的调用: %s" % (rec["id"], stray))

    def test_disabled_demand_is_silent(self):
        """下线就是下线：enabled=false 的需求在同一个点上不许再调服务。"""
        for rec in load_all():
            given = (rec.get("expect") or {}).get("given") or {}
            mine = (rec.get("expect") or {}).get("calls") or []
            api = _Api(mine)
            ctx = _Ctx(api, _Storage())
            engine = _engine.Engine(ctx)
            engine.set_enabled(rec["id"], False)
            engine.dispatch(given.get("on"), given.get("event") or {})
            fired = [c["route"] for c in api.calls]
            self.assertEqual([r for r in fired if r in mine], [],
                             "%s 下线后仍在执行（同一批里还有别人: %s）" % (rec["id"], fired))


if __name__ == "__main__":
    unittest.main(verbosity=2)
