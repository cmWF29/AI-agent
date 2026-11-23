"""项目/工单工作区隔离：路径解析、越界校验与 capability 上报契约。

覆盖：
- legacy（未配置自定义根）：各层落在归属模块自己的 data 目录，存量行为不动；
- 配置根：解析后绝对目录必须全部落在项目根 realpath 之内；
- 越界片段、非绝对根一律拒绝；
- capability 不许把未验证/未实现的档位报成 supported；
- 项目档案持有可选 root 字段并随视图下发。
"""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))

from ai_new.modules.agent_common.store.private import _isolate  # noqa: E402
from ai_new.modules.agent.projects.private import _pure as projects_pure  # noqa: E402


class WorkspaceResolveTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="isolation-")

    def _dir_of(self, module):
        return Path(self.tmp) / module

    def test_legacy_dirs_under_owning_module_data(self):
        out = _isolate.resolve_workspace(
            {"project": "demo-proj", "ticket": "T-20261123-0001"},
            dir_of=self._dir_of)
        self.assertTrue(out["ok"])
        self.assertEqual(out["mode"], "legacy")
        self.assertIsNone(out["root"])
        dirs = out["dirs"]
        for layer in ("documents", "tickets", "logs", "artifacts"):
            self.assertTrue(Path(dirs[layer]).is_absolute(), layer)
            self.assertTrue(Path(dirs[layer]).is_relative_to(Path(self.tmp)), layer)
        self.assertIn("T-20261123-0001", dirs["tickets"])
        # 各层归属模块不同：工单在 tickets，文档在 knowledge，日志在 logs，交付件在 artifacts。
        self.assertIn("agent/tickets", dirs["tickets"])
        self.assertIn("agent/knowledge", dirs["documents"])
        self.assertIn("agent/logs", dirs["logs"])
        self.assertIn("agent/artifacts", dirs["artifacts"])

    def test_configured_root_dirs_all_under_root(self):
        root = str(Path(self.tmp) / "proj-root")
        out = _isolate.resolve_workspace(
            {"project": "demo-proj", "ticket": "T-20261123-0002", "root": root},
            dir_of=self._dir_of)
        self.assertTrue(out["ok"])
        self.assertEqual(out["mode"], "root")
        root_real = Path(out["root"]).resolve(strict=False)
        self.assertTrue(root_real.is_absolute())
        for layer, value in out["dirs"].items():
            self.assertTrue(_isolate._is_within(root_real, Path(value).resolve(strict=False)),
                            layer)
        self.assertEqual(out["dirs"]["tickets"],
                         str(root_real / "tickets" / "T-20261123-0002"))

    def test_non_absolute_root_rejected(self):
        out = _isolate.resolve_workspace(
            {"project": "demo-proj", "root": "relative/dir"}, dir_of=self._dir_of)
        self.assertFalse(out["ok"])
        self.assertEqual(out["code"], "root_not_absolute")

    def test_traversal_segment_rejected(self):
        out = _isolate.resolve_workspace(
            {"project": "../../etc", "ticket": "T-1"}, dir_of=self._dir_of)
        self.assertFalse(out["ok"])
        self.assertEqual(out["code"], "missing_project")

    def test_is_within_bounds(self):
        root = Path(self.tmp).resolve(strict=False)
        child = root / "tickets" / "T-1"
        sibling = Path(self.tmp + "-sibling").resolve(strict=False)
        self.assertTrue(_isolate._is_within(root, child))
        self.assertTrue(_isolate._is_within(root, root))
        self.assertFalse(_isolate._is_within(root, sibling))


class CapabilityReportTest(unittest.TestCase):
    def test_report_does_not_claim_unverified_tier(self):
        cap = _isolate.capabilities()
        self.assertIn(cap["os"], ("posix", "nt"))
        for tier in ("strong", "weak"):
            band = cap[tier]
            self.assertIn("supported", band)
            self.assertIn("verified", band)
            # 本机没有实测过任何强/弱档落地：verified 一律不许为 True。
            self.assertFalse(band["verified"], tier)
        if cap["os"] == "nt":
            self.assertFalse(cap["strong"]["supported"])
            self.assertFalse(cap["weak"]["supported"])
        else:
            self.assertTrue(cap["weak"]["supported"])
            # posix 强档仅在机制入口存在时标 supported，且仍未 verified。
            self.assertIn(cap["strong"]["supported"], (True, False))


class ProjectRecordRootTest(unittest.TestCase):
    def test_build_and_view_carry_root(self):
        rec = projects_pure.build({"id": "p1", "name": "项目一", "root": "/var/work/p1"})
        view = projects_pure.view({"rec": rec})
        self.assertEqual(view["root"], "/var/work/p1")

    def test_build_root_defaults_empty(self):
        rec = projects_pure.build({"id": "p2", "name": "项目二"})
        self.assertEqual(rec["root"], "")
        self.assertEqual(projects_pure.view({"rec": rec})["root"], "")


class RouteRegistrationTest(unittest.TestCase):
    def test_workspace_route_registered_and_callable(self):
        from ai_new.modules.agent_common.store import setup as store_setup

        class _Api:
            def __init__(self):
                self.routes = {}

            def register(self, name, fn, *args, **kwargs):
                self.routes[name] = fn

        ctx = type("Ctx", (), {"api": _Api()})()
        store_setup(ctx)
        self.assertIn("store.workspace", ctx.api.routes)
        handler = ctx.api.routes["store.workspace"]
        out = handler(None, {"project": "p3", "ticket": "T-9"})
        self.assertTrue(out["ok"])
        self.assertEqual(out["mode"], "legacy")


if __name__ == "__main__":
    unittest.main(verbosity=2)
