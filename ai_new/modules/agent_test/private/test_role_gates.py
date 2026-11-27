"""岗位门禁契约测试：种子岗位/流程的清单完整性、唯一性、渲染一致性与迁移门禁。

覆盖：
- 每个非 ref 状态都有 gate，must 带稳定唯一 id、text 可执行可留证据，forbid 非空且具体；
- must id 全库唯一；提示词渲染出的清单与 gate 数据一致；
- 端到端桩验证：缺清单拒迁、交齐才迁、violations 拒迁；
- todo 工具在每个状态白名单内；ref 子流程契约正确展开。
"""
from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))

from ai_new.modules.agent.library.private import _pure as P  # noqa: E402

DATA = ROOT / "ai_new/modules/agent/library/data"
ID_RE = re.compile(r"^[a-z0-9]+(\.[a-z0-9]+)*\.m[0-9]+$")
# 空话词：清单条目不得用这类不可执行的措辞。
VAGUE = ("认真", "充分", "尽量", "积极", "努力", "大力", "多多")


def _load_seed():
    seed = yaml_safe_load(DATA / "seed.yaml")
    tpl = yaml_safe_load(DATA / "messages.yaml")
    return seed, tpl


def yaml_safe_load(path: Path):
    import yaml
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _iter_states(states):
    stack = list(states or [])
    while stack:
        s = stack.pop(0)
        yield s
        stack.extend(s.get("children") or [])


def _records(seed):
    """展开后的岗位与流程记录表（种子盖覆盖层后的生效形状）。"""
    roles = P._records({"seed": seed, "user": {}, "kind": "roles"})
    flows = P._records({"seed": seed, "user": {}, "kind": "flows"})
    return roles, flows


class RoleGatesTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.seed, cls.tpl = _load_seed()
        cls.roles, cls.flows = _records(cls.seed)
        cls.refs = P.stage_refsp({"seed": cls.seed, "flows": {}})["refs"]

    # ---- 形状与完整性 ----

    def _gate_states(self, rec):
        return [s for s in _iter_states(rec.get("states") or []) if not s.get("ref")]

    def test_gate_present_must_and_forbid_well_formed(self):
        bad = []
        for rid, rec in list(self.roles.items()) + list(self.flows.items()):
            for s in self._gate_states(rec):
                gate = s.get("gate") or {}
                must = gate.get("must") or []
                forbid = gate.get("forbid") or []
                if not must:
                    bad.append("%s/%s: 缺 must" % (rid, s["id"]))
                if not forbid:
                    bad.append("%s/%s: 缺 forbid" % (rid, s["id"]))
                for m in must:
                    mid = str((m or {}).get("id") or "")
                    text = str((m or {}).get("text") or "").strip()
                    if not ID_RE.match(mid):
                        bad.append("%s/%s: must id 形状非法: %s" % (rid, s["id"], mid))
                    if len(text) < 8:
                        bad.append("%s/%s: must text 过短/为空: %r" % (rid, s["id"], text))
                    if any(w in text for w in VAGUE):
                        bad.append("%s/%s: must 含空话措辞: %r" % (rid, s["id"], text))
                for f in forbid:
                    if not str(f or "").strip():
                        bad.append("%s/%s: forbid 有空条目" % (rid, s["id"]))
        self.assertEqual(bad, [], "门禁形状问题: %s" % bad)

    def test_must_ids_unique_across_library(self):
        ids = []
        for rid, rec in list(self.roles.items()) + list(self.flows.items()):
            for s in self._gate_states(rec):
                for m in (s.get("gate") or {}).get("must") or []:
                    ids.append(m["id"])
        dup = sorted({x for x in ids if ids.count(x) > 1})
        self.assertEqual(dup, [], "must id 重复: %s" % dup)
        self.assertGreater(len(ids), 0, "没有任何 must 清单条目")

    def test_mirror_files_match_seed(self):
        """覆盖层镜像必须由种子派生：roles.yaml/flows.yaml 与 seed 深一致，防双源漂移。"""
        roles_mirror = yaml_safe_load(DATA / "roles.yaml")
        flows_mirror = yaml_safe_load(DATA / "flows.yaml")
        self.assertEqual(roles_mirror, {r["id"]: r for r in self.seed["roles"]})
        self.assertEqual(flows_mirror, {f["id"]: f for f in self.seed["flows"]})

    def test_todo_in_every_state_tools(self):
        misses = []
        for rid, rec in list(self.roles.items()) + list(self.flows.items()):
            for s in self._gate_states(rec):
                tools = s.get("tools")
                if isinstance(tools, list) and "todo" not in tools:
                    misses.append("%s/%s" % (rid, s["id"]))
        self.assertEqual(misses, [], "这些状态白名单漏了 todo: %s" % misses)

    # ---- 渲染一致性 ----

    def _contract(self, rec):
        return P.stage_contractp({
            "states": rec.get("states"),
            "refs": self.refs,
            "checks": rec.get("checks"),
        })

    def test_rendered_checklist_matches_gate_data(self):
        for rid, rec in list(self.roles.items()) + list(self.flows.items()):
            contract = self._contract(rec)
            if not contract["states"]:
                continue
            active = [contract["initial"]]
            active_rec = contract["by_id"][contract["initial"]]
            out = P.flow_contextp({
                "contract": contract,
                "flow": {"id": rec["id"], "cn": rec.get("cn") or ""},
                "checks": rec.get("checks"),
                "active": active,
                "tpl": self.tpl,
            })
            content = out["content"]
            gate = active_rec.get("gate") or {}
            for m in gate.get("must") or []:
                self.assertIn(m["id"], content,
                              "%s: must id %s 未进渲染清单" % (rid, m["id"]))
                self.assertIn(m["text"], content,
                              "%s: must text 未进渲染清单: %r" % (rid, m["text"]))
            for f in gate.get("forbid") or []:
                self.assertIn(str(f), content,
                              "%s: forbid 未进渲染清单: %r" % (rid, f))
            block = P.stage_blockp({"contract": contract, "active": active, "tpl": self.tpl})
            for m in gate.get("must") or []:
                self.assertIn(m["id"], block["system"],
                              "%s: must id %s 未进 stage_block" % (rid, m["id"]))

    # ---- 迁移门禁：缺清单拒迁 / 交齐才迁 / violations 拒迁 ----

    def _enforce(self, rec, src, dst):
        contract = self._contract(rec)
        checked = [m["id"] for s in self._gate_states(rec)
                   for m in (s.get("gate") or {}).get("must") or []
                   if s["id"] == src]
        # 1) 缺清单拒迁
        miss = P.stage_transitionp({"contract": contract, "prev": src, "nxt": dst})
        self.assertFalse(miss["ok"])
        self.assertEqual(miss["code"], "checklist_unmet")
        self.assertEqual(sorted(miss["missing"]), sorted(checked))
        # 2) 交齐才迁
        ok = P.stage_transitionp({"contract": contract, "prev": src, "nxt": dst,
                                 "checked": checked})
        self.assertTrue(ok["ok"])
        self.assertEqual(ok["stage"], dst)
        # 3) violations 拒迁
        vio = P.stage_transitionp({"contract": contract, "prev": src, "nxt": dst,
                                   "checked": checked, "violations": ["直接改了业务代码"]})
        self.assertFalse(vio["ok"])
        self.assertEqual(vio["code"], "forbidden_hit")

    def test_developer_transition_gate(self):
        self._enforce(self.roles["developer"], "understand", "branch")

    def test_developer_understand_can_inspect_repo(self):
        """理解阶段必须能读真实仓库，否则只能对着交付件空转。"""
        states = {s["id"]: s for s in _iter_states(self.roles["developer"]["states"])}
        self.assertIn("shell", states["understand"].get("tools") or [])

    def test_requirement_owner_transition_gate(self):
        self._enforce(self.flows["requirement-owner"], "req.intake", "req.structure")

    # ---- skill-decomposer 第五批：全过程状态机与同源校验 ----

    DECOMPOSER_NEXT = {
        "sd.intake": ["sd.env", "sd.reject"],
        "sd.env": ["sd.deps", "sd.reject"],
        "sd.deps": ["sd.install", "sd.analyze"],
        "sd.install": ["sd.deps", "sd.analyze"],
        "sd.analyze": ["sd.roles"],
        "sd.roles": ["sd.tools"],
        "sd.tools": ["sd.flow"],
        "sd.flow": ["sd.verify"],
        "sd.verify": ["sd.roles", "sd.tools", "sd.flow", "sd.deliver"],
        "sd.deliver": [],
        "sd.reject": [],
    }

    def test_skill_decomposer_contract_and_transitions(self):
        dec = self.roles["skill-decomposer"]
        states = self._gate_states(dec)
        ids = [s["id"] for s in states]
        self.assertEqual(ids, list(self.DECOMPOSER_NEXT.keys()),
                         "拆解者状态链与契约不一致")
        by = {s["id"]: s for s in states}
        for sid, nxt in self.DECOMPOSER_NEXT.items():
            self.assertEqual(by[sid]["next"], nxt, "%s 迁移边不符" % sid)
        # 分支/回退条件必须落 when：缺依赖→install；install 失败→回 deps；
        # verify 不通过→回 roles/tools/flow；包非法→reject 终态。
        deps = by["sd.deps"]
        self.assertIn("缺失", deps["when"]["sd.install"])
        install = by["sd.install"]
        self.assertIn("失败", install["when"]["sd.deps"])
        verify = by["sd.verify"]
        self.assertIn("回退", verify["when"]["sd.roles"])
        self.assertIn("回退", verify["when"]["sd.tools"])
        self.assertIn("回退", verify["when"]["sd.flow"])
        self.assertIn("全过", verify["when"]["sd.deliver"])
        self.assertTrue(by["sd.reject"].get("terminal"))
        self.assertTrue(by["sd.deliver"].get("terminal"))
        # 必备门禁主题逐条可核对：来源/版本/许可证、环境探测、依赖比对、隔离锁版本、
        # 拆解结构、岗位/工具/流程登记、自检契约/引用/幂等、交付清单/审计/引用位置。
        must_text = " ".join(
            m["text"] for s in states for m in (s.get("gate") or {}).get("must") or [])
        for kw in ("许可证", "运行时", "requirements", "隔离", "验收",
                   "schema", "幂等", "审计", "引用位置"):
            self.assertIn(kw, must_text, "拆解者 must 缺主题: %s" % kw)
        install_forbid = (by["sd.install"].get("gate") or {}).get("forbid") or []
        for kw in ("提权", "拼命令", "锁版本", "脚本"):
            self.assertTrue(any(kw in f for f in install_forbid),
                            "install forbid 缺具体动作: %s" % kw)

    def test_prompts_are_prose_without_duplicated_checklist(self):
        """提示词只写 prose：不得复制 gate 清单（must id / 待办勾选框）。"""
        import re as _re
        prompts = sorted((DATA / "prompts" / "roles").glob("*.md"))
        prompts.append(ROOT / "ai_new/modules/agent/sessions/data/prompts/pm.md")
        id_pat = _re.compile(r"[a-z0-9]+(?:\.[a-z0-9]+)*\.m\d+")
        for path in prompts:
            if not path.exists():
                continue
            text = path.read_text(encoding="utf-8")
            self.assertFalse(id_pat.search(text),
                             "%s 复制了门禁 must id" % path.name)
            self.assertNotIn("- [ ]", text, "%s 内嵌了待办勾选清单" % path.name)

    def test_gate_must_is_the_single_checklist_source(self):
        """记录里不得另挂一份手写 todos 清单；强制清单只来自 gate.must。"""
        for rid, rec in list(self.roles.items()) + list(self.flows.items()):
            self.assertNotIn("todos", rec, "%s 另挂了待办清单字段" % rid)
            for s in self._gate_states(rec):
                gate = s.get("gate") or {}
                must_ids = [m["id"] for m in gate.get("must") or []]
                self.assertEqual(len(must_ids), len(set(must_ids)),
                                 "%s/%s must id 重复" % (rid, s["id"]))

    # ---- ref 子流程展开 ----

    def test_ref_flow_expands_into_contract(self):
        pm = self._contract(self.roles["pm"])
        self.assertEqual(pm["initial"], "owner")
        self.assertIn("owner.req.intake", [s["path"] for s in pm["states"]])
        self.assertEqual(pm["terminals"], ["owner.req.close"])
        ops = self._contract(self.roles["ops"])
        self.assertIn("health.ops.diagnose", [s["path"] for s in ops["states"]])
        self.assertIn("requirement-owner", self.refs)
        self.assertIn("ticket-health", self.refs)


if __name__ == "__main__":
    unittest.main(verbosity=2)
