"""skill 拆解扩展验收：安全读包、环境 / 依赖预检阻断、登记守卫、项目引用与幂等重跑。

覆盖链路（能力内闭环，需求只编排调用与 apply）：
  读入包与清单 → 运行环境检查 → 缺失依赖检查 → 隔离安装 → 拆解岗位职责 →
  登记角色 / 工具 / 流程 → 自检门禁 → 交付可被项目引用的产物。
"""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))

from ai_new.modules.agent_common.boot.private._boot import _build as build  # noqa: E402
from ai_new.modules.agent_common.boot.private._context import Context  # noqa: E402
from _fixtures import stage, write_config  # noqa: E402

SAMPLES = ROOT / "ai_new/modules/agent/decompose/data/samples"


def _sample(name):
    return (SAMPLES / name).read_text(encoding="utf-8")


def _draft():
    """模型返回成形草稿：岗位 + 流程节点 / 边 + 一个新工具。"""
    return {
        "role": {"cn": "演示拆解员", "must_dos": ["读包正文", "拆成岗位职责"],
                 "forbidden": ["改写原始包正文"], "tools": []},
        "flow": {"checks": ["岗位职责覆盖包内步骤"],
                 "nodes": [{"id": "read", "cn": "读包"}, {"id": "split", "cn": "拆岗"}],
                 "edges": [{"from": "read", "to": "split"}]},
        "new_tools": [{"name": "demo_audit", "desc": "按包正文自检拆解结果",
                       "params": [], "deps": {"pip": []}}],
    }


def _bundle(md, requirements=None, **over):
    bundle = {
        "id": "demo_skill", "version": "v1",
        "source": "https://example.com/SKILL.md", "license": "MIT",
        "files": [{"path": "SKILL.md", "text": md}],
        "requirements": requirements or [],
        "deps": {"cli": [], "env": []},
    }
    bundle.update(over)
    return bundle


def _fake_react(draft):
    def fn(ctx, payload):
        text = json.dumps(draft, ensure_ascii=False)
        return {"steps": 1, "messages": [{"role": "assistant", "content": text}],
                "last": {"role": "assistant", "content": text},
                "cancelled": False, "failed": None}
    return fn


async def _fake_exec(ctx, payload):
    """打桩进程通道：隔离安装假装成功，不起真实 pip、不碰外壳。"""
    return {"ok": True, "seconds": 0.1, "error": ""}


class SkillDecomposeTest(unittest.TestCase):
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
        cls.server = cls.ctx.http
        cls.ctx.api.substitute("exec.run", _fake_exec)

    @classmethod
    def tearDownClass(cls):
        # HTTP 服务跑在非 daemon 后台线程；不显式关停，解释器会在退出时被它挂住。
        try:
            cls.server.shutdown()
        except Exception:  # noqa: BLE001 —— 关停失败不阻断用例收尾
            pass
        os.environ.pop("AI_NEW_DATA", None)
        cls.tmp.cleanup()

    # ---- 辅助读取正式库 ----

    def _lib(self, module, path):
        row = self.ctx.api.call("store.read", {"module": module, "path": path}, caller=None)
        return row.get("value") or {}

    def _positions(self, project):
        res = self.ctx.demand_engine.run_callable("project-positions", {"id": project})
        return (res.get("result") or {}).get("items") or []

    def _apply(self, effects):
        """能力产 effect，需求 runtime.apply 落地；用例直调能力时手动补这一跳。"""
        return self.ctx.api.call("runtime.apply", {"effect": effects})

    # ---- 用例 ----

    def test_normal_decompose_registers_and_is_referenceable(self):
        """正常包：预检 → 隔离装依赖 → 登记；岗位 / 工具 / 流程入库，可被项目引用并启停。"""
        md = _sample("ppt-builder.md")
        bundle = _bundle(md, requirements=["python-pptx"], id="ppt_design_skill")

        inspect = self.ctx.api.call("decompose.inspect", {"bundle": bundle})
        self.assertTrue(inspect["ok"], inspect)
        self.assertIn(inspect["status"], ("inspected", "deps_ready", "blocked_missing_deps"))
        task_key = inspect["task_key"]
        self._apply(inspect["effects"])

        deps = self.ctx.api.call("decompose.deps_install", {"task_key": task_key})
        self.assertTrue(deps["ok"], deps)
        self.assertEqual(deps["status"], "deps_ready")
        self._apply(deps["effects"])

        draft = _draft()
        draft["id"] = "ppt_design_skill"
        self.ctx.api.substitute("react.run", _fake_react(draft))
        run = self.ctx.api.call("decompose.run", {"skill_md": md, "system": ""})
        self.assertTrue(run["draft"], run)

        reg = self.ctx.api.call("decompose.register",
                                {"task_key": task_key, "draft": run["draft"], "meta": run["meta"]})
        self.assertTrue(reg["ok"], reg)
        self.assertFalse(reg["reused"])
        self._apply(reg["effects"])

        roles = self._lib("agent/library", "roles.yaml")
        tools = self._lib("agent_common/tools", "tools.yaml")
        skills = self._lib("agent/library", "skills.yaml")
        self.assertIn("ppt_design_skill", roles)
        self.assertIn("demo_audit", tools)
        self.assertIn("ppt_design_skill", skills)
        role = roles["ppt_design_skill"]
        # 流程随岗位走：节点 / 边 / 检查项成形在岗位记录里
        self.assertTrue(role.get("nodes") and role.get("edges"))
        self.assertTrue(role.get("checks"))

        # 项目岗位清单能读到该岗位，并可项目级启停
        proj = "demo-decompose-proj"
        self.ctx.demand_engine.run_callable("projects-create", {"name": proj})
        items = self._positions(proj)
        self.assertTrue(any(i.get("id") == "ppt_design_skill" for i in items))

        self.ctx.demand_engine.run_callable("project-override-toggle",
                                            {"project": proj, "kind": "roles",
                                             "id": "ppt_design_skill", "enabled": False})
        items = self._positions(proj)
        off = next(i for i in items if i.get("id") == "ppt_design_skill")
        self.assertTrue(off["disabled"])

        self.ctx.demand_engine.run_callable("project-override-toggle",
                                            {"project": proj, "kind": "roles",
                                             "id": "ppt_design_skill", "enabled": True})
        items = self._positions(proj)
        on = next(i for i in items if i.get("id") == "ppt_design_skill")
        self.assertFalse(on["disabled"])

    def test_missing_deps_blocks_registration(self):
        """缺依赖：预检进入阻断态，不登记任何岗位 / 工具 / 流程。"""
        md = _sample("image-generation.md")
        bundle = _bundle(md, requirements=["absent-pkg-xyz-12345"], id="image_gen_skill")
        inspect = self.ctx.api.call("decompose.inspect", {"bundle": bundle})
        self.assertTrue(inspect["ok"], inspect)
        self.assertEqual(inspect["status"], "blocked_missing_deps")
        self.assertTrue(inspect["deps"]["missing"])
        self._apply(inspect["effects"])

        before_roles = set(self._lib("agent/library", "roles.yaml"))
        before_tools = set(self._lib("agent_common/tools", "tools.yaml"))
        reg = self.ctx.api.call("decompose.register",
                                {"task_key": inspect["task_key"],
                                 "draft": _draft(), "meta": {}})
        self.assertFalse(reg["ok"])
        self.assertEqual(reg["code"], "deps_blocked")
        after_roles = set(self._lib("agent/library", "roles.yaml"))
        after_tools = set(self._lib("agent_common/tools", "tools.yaml"))
        self.assertEqual(before_roles, after_roles)
        self.assertEqual(before_tools, after_tools)

    def test_illegal_bundle_rejected_with_code(self):
        """非法包：穿越 / 绝对路径 / 符号链接逃逸 / 脚本类型 / 非法包名一律拒绝并给错误码。"""
        md = _sample("ppt-builder.md")

        traversal = _bundle(md, id="trav")
        traversal["files"] = [{"path": "../etc/secret.md", "text": "x"}]
        r = self.ctx.api.call("decompose.inspect", {"bundle": traversal})
        self.assertFalse(r["ok"])
        self.assertEqual(r["code"], "path_traversal")

        absolute = _bundle(md, id="abs")
        absolute["files"] = [{"path": "/etc/secret.md", "text": "x"}]
        r = self.ctx.api.call("decompose.inspect", {"bundle": absolute})
        self.assertFalse(r["ok"])
        self.assertEqual(r["code"], "absolute_path")

        symlink = _bundle(md, id="link")
        symlink["files"] = [{"path": "link.md", "text": "x",
                             "link": "../../etc/passwd", "is_link": True}]
        r = self.ctx.api.call("decompose.inspect", {"bundle": symlink})
        self.assertFalse(r["ok"])
        self.assertEqual(r["code"], "symlink_escape")

        script = _bundle(md, id="script")
        script["files"] = [{"path": "setup.sh", "text": "#!/bin/sh\n"},
                            {"path": "SKILL.md", "text": md}]
        r = self.ctx.api.call("decompose.inspect", {"bundle": script})
        self.assertFalse(r["ok"])
        self.assertEqual(r["code"], "disallowed_type")

        bad_pkg = _bundle(md, requirements=["pptx; rm -rf /"], id="badpkg")
        r = self.ctx.api.call("decompose.inspect", {"bundle": bad_pkg})
        self.assertFalse(r["ok"])
        self.assertEqual(r["code"], "bad_pkg")
        self.assertTrue(r["deps"]["rejected"])

    def test_idempotent_rerun_keeps_product_count(self):
        """同包同版本重跑：第二次登记复用既有产物，岗位 / 工具 / 流程数量不变。"""
        md = _sample("ppt-builder.md")
        bundle = _bundle(md, requirements=["python-pptx"], id="idem_skill")

        first = self.ctx.api.call("decompose.inspect", {"bundle": bundle})
        self.assertTrue(first["ok"])
        task_key = first["task_key"]
        self._apply(first["effects"])
        self._apply(self.ctx.api.call("decompose.deps_install", {"task_key": task_key})["effects"])

        draft = _draft()
        draft["id"] = "idem_skill"
        self.ctx.api.substitute("react.run", _fake_react(draft))
        run = self.ctx.api.call("decompose.run", {"skill_md": md, "system": ""})
        reg1 = self.ctx.api.call("decompose.register",
                                 {"task_key": task_key, "draft": run["draft"], "meta": run["meta"]})
        self.assertTrue(reg1["ok"])
        self._apply(reg1["effects"])

        roles1 = self._lib("agent/library", "roles.yaml")
        tools1 = self._lib("agent_common/tools", "tools.yaml")
        skills1 = self._lib("agent/library", "skills.yaml")

        # 第二次：预检 + 装依赖 + 登记全部重跑一遍
        second = self.ctx.api.call("decompose.inspect", {"bundle": bundle})
        self.assertTrue(second["ok"])
        self._apply(second["effects"])
        self._apply(self.ctx.api.call("decompose.deps_install", {"task_key": task_key})["effects"])
        run2 = self.ctx.api.call("decompose.run", {"skill_md": md, "system": ""})
        reg2 = self.ctx.api.call("decompose.register",
                                  {"task_key": task_key, "draft": run2["draft"], "meta": run2["meta"]})
        self.assertTrue(reg2["ok"])
        self.assertTrue(reg2["reused"])
        self._apply(reg2["effects"])

        roles2 = self._lib("agent/library", "roles.yaml")
        tools2 = self._lib("agent_common/tools", "tools.yaml")
        skills2 = self._lib("agent/library", "skills.yaml")
        self.assertEqual(len(roles1), len(roles2))
        self.assertEqual(len(tools1), len(tools2))
        self.assertEqual(len(skills1), len(skills2))
        self.assertIn("idem_skill", roles2)
        self.assertIn("demo_audit", tools2)

    def test_status_lists_tasks_products_and_audit(self):
        """台账只读：任务状态、产物引用、审计条目可一次取回。"""
        md = _sample("image-generation.md")
        bundle = _bundle(md, requirements=[], id="status_skill")
        inspect = self.ctx.api.call("decompose.inspect", {"bundle": bundle})
        self.assertTrue(inspect["ok"])
        self._apply(inspect["effects"])
        self._apply(self.ctx.api.call("decompose.deps_install", {"task_key": inspect["task_key"]})["effects"])
        draft = _draft()
        draft["id"] = "status_skill"
        self.ctx.api.substitute("react.run", _fake_react(draft))
        run = self.ctx.api.call("decompose.run", {"skill_md": md, "system": ""})
        reg = self.ctx.api.call("decompose.register",
                                {"task_key": inspect["task_key"], "draft": run["draft"], "meta": run["meta"]})
        self.assertTrue(reg["ok"])
        self._apply(reg["effects"])

        status = self.ctx.api.call("decompose.status", {})
        tasks = status["tasks"]
        mine = next(t for t in tasks if t["id"] == "status_skill")
        self.assertEqual(mine["status"], "registered")
        self.assertEqual(mine["products"]["role"], "status_skill")
        self.assertIn("demo_audit", mine["products"]["tools"])
        self.assertTrue(mine["audit"])
        audit = mine["audit"][-1]
        self.assertEqual(audit["source"], "https://example.com/SKILL.md")
        self.assertEqual(audit["license"], "MIT")
        self.assertTrue(status["audit_tree"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
