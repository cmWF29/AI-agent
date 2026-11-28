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
import asyncio
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))


def _is_relative_to(path: Path, root: Path) -> bool:
    """Py3.8 兼容：Path.is_relative_to 到 3.9 才有，门禁必须能在 3.8 跑。"""
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False

from ai_new.modules.agent_common.store.private import _isolate  # noqa: E402
from ai_new.modules.agent_common.exec.private import _runner  # noqa: E402
from ai_new.modules.agent.projects.private import _pure as projects_pure  # noqa: E402
from ai_new.modules.agent_common.tools import _shell_cwd  # noqa: E402


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
            self.assertTrue(_is_relative_to(Path(dirs[layer]), Path(self.tmp)), layer)
        self.assertIn("T-20261123-0001", dirs["tickets"])
        # 各层归属模块不同：工单在 tickets，文档在 knowledge，日志在 logs，交付件在 artifacts。
        posix = {k: str(v).replace("\\", "/") for k, v in dirs.items()}
        self.assertIn("agent/tickets", posix["tickets"])
        self.assertIn("agent/knowledge", posix["documents"])
        self.assertIn("agent/logs", posix["logs"])
        self.assertIn("agent/artifacts", posix["artifacts"])

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

    def test_configured_root_carries_sandbox_spec(self):
        root = str(Path(self.tmp) / "proj-root")
        out = _isolate.resolve_workspace(
            {"project": "demo-proj", "ticket": "T-20261123-0003", "root": root},
            dir_of=self._dir_of)
        sandbox = out["sandbox"]
        self.assertIn(sandbox["engine"], ("bwrap", "winjob", "path"))
        if sandbox["engine"] == "bwrap":
            self.assertEqual(sandbox["mount"], "/workspace")
            self.assertEqual(sandbox["cwd"], "/workspace/tickets/T-20261123-0003")
            self.assertEqual(Path(sandbox["root"]), Path(out["root"]))
            dests = [row["dst"] for row in sandbox["binds"]]
            self.assertIn("/workspace/tickets/T-20261123-0003", dests)
            self.assertIn("/workspace/documents", dests)
        elif sandbox["engine"] == "winjob":
            self.assertTrue(_isolate._winjob.ready())
            self.assertEqual(Path(sandbox["root"]), Path(out["root"]))
            self.assertEqual(Path(sandbox["cwd"]), Path(out["cwd"]))
            self.assertEqual(sandbox["limits"]["active_processes"], 64)

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
        if cap["os"] == "nt":
            self.assertTrue(cap["strong"]["supported"])
            self.assertEqual(cap["strong"]["tier"], "job-object-process-tree")
            self.assertEqual(cap["strong"]["verified"],
                             _isolate._winjob.ready())
            self.assertTrue(cap["weak"]["supported"])
            self.assertTrue(cap["weak"]["verified"])
        else:
            self.assertEqual(cap["strong"]["verified"], _isolate._bwrap_ready())
            self.assertTrue(cap["weak"]["supported"])
            self.assertFalse(cap["weak"]["verified"])


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


class ShellWorkspaceTest(unittest.TestCase):
    """shell 默认 cwd 与越界拒绝：走真实 store 工作区解析，公共层可进，目录只看自己的。"""

    class _Api:
        def __init__(self, root):
            self.root = root

        def call(self, name, payload, caller=None):
            if name == "projects.workspace":
                return _isolate.resolve_workspace({
                    "project": payload.get("id") or "p1",
                    "ticket": payload.get("ticket") or "",
                    "cwd": payload.get("cwd") or "",
                    "root": str(self.root) if self.root else ""},
                    dir_of=lambda module: Path(tempfile.mkdtemp(prefix="legacy-"))
                    if not self.root else Path(self.root) / module)
            if name == "store.read":
                return {"value": {
                    "cwd_outside": "工作目录不在本项目允许的工作区: {path}",
                    "workspace_unavailable": "项目工作区不可用: {error}"}}
            return {}

    class _Ctx:
        def __init__(self, root):
            self.api = ShellWorkspaceTest._Api(root)

    def _root(self):
        return Path(tempfile.mkdtemp(prefix="shell-ws-"))

    def test_default_cwd_is_own_ticket_dir(self):
        root = self._root()
        out = _shell_cwd(self._Ctx(root), "",
                         {"project": "p1", "ticket": "T-1"})
        self.assertTrue(out["ok"], out)
        self.assertEqual(Path(out["cwd"]), root.resolve() / "tickets" / "T-1")
        self.assertTrue(out["ensure"])

    def test_other_ticket_and_escape_rejected(self):
        root = self._root()
        ctx = self._Ctx(root)
        other = str(root.resolve() / "tickets" / "T-2")
        out = _shell_cwd(ctx, other, {"project": "p1", "ticket": "T-1"})
        self.assertFalse(out["ok"])
        self.assertEqual(out["code"], "cwd_outside")
        out2 = _shell_cwd(ctx, str(root.resolve().parent), {"project": "p1", "ticket": "T-1"})
        self.assertFalse(out2["ok"])

    def test_shared_layer_allowed(self):
        root = self._root()
        shared = str(root.resolve() / "documents")
        out = _shell_cwd(self._Ctx(root), shared,
                         {"project": "p1", "ticket": "T-1"})
        self.assertTrue(out["ok"], out)
        self.assertEqual(Path(out["cwd"]), root.resolve() / "documents")

    def test_legacy_keeps_caller_cwd(self):
        root = self._root()
        # 没配项目根：store 走 legacy，不接管 cwd。
        out = _shell_cwd(self._Ctx(None), "/tmp",
                         {"project": "p1", "ticket": "T-1"})
        self.assertTrue(out["ok"])
        self.assertEqual(out["cwd"], "/tmp")
        self.assertFalse(out["ensure"])


class SandboxMountTest(unittest.TestCase):
    """强档真实起 bwrap：项目根只以 /workspace 出现，宿主路径不可见。"""

    class _Ctx:
        class _Api:
            def call(self, name, payload, caller=None):
                return {"value": 4000}

        api = _Api()
        runtime = None

    def test_project_root_is_mounted_and_host_is_hidden(self):
        root = Path(tempfile.mkdtemp(prefix="sandbox-"))
        (root / "tickets" / "T-2").mkdir(parents=True)
        ws = _isolate.resolve_workspace(
            {"project": "p1", "ticket": "T-1", "root": str(root), "cwd": ""},
            dir_of=lambda module: root / module)
        engine = ws["sandbox"]["engine"]
        if engine == "winjob":
            self.assertFalse(_isolate._winjob is None)
            res = asyncio.run(_runner._arun(self._Ctx(), {
                "argv": [sys.executable, "-c",
                         "import os; open('job.txt','w').write(os.getcwd())"],
                "cwd": ws["cwd"], "ensure_cwd": True,
                "sandbox": ws["sandbox"], "timeout": 10}))
            self.assertTrue(res["ok"], res)
            self.assertTrue((Path(ws["cwd"]) / "job.txt").exists())
            return
        if engine != "bwrap":
            # 本机强档不可用：接口必须显式降级到 path，不能冒充 bwrap。
            self.assertEqual(engine, "path")
            self.assertFalse(_isolate._bwrap_ready())
            return
        res = asyncio.run(_runner._arun(self._Ctx(), {
            "argv": ["/bin/sh", "-c",
                     "pwd; test ! -e /home && echo HOST_HIDDEN; "
                     "ls /workspace/tickets; echo mounted > ticket.txt"],
            "cwd": ws["cwd"], "ensure_cwd": True,
            "sandbox": ws["sandbox"], "timeout": 10}))
        self.assertTrue(res["ok"], res)
        self.assertIn("/workspace/tickets/T-1", res["out"])
        self.assertIn("HOST_HIDDEN", res["out"])
        self.assertNotIn("T-2", res["out"])
        self.assertEqual((Path(ws["cwd"]) / "ticket.txt").read_text().strip(),
                         "mounted")


