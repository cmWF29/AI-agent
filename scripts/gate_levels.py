#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""4 级层级判定门禁：把"某个能力/知识要不要节点级"从人工结论变成可执行判定。

输入契约（只读）：
  - ``agent_common/api/data/capability-routes.yaml``（聚合能力内部路由）
  - ``agent_common/api/data/platform-routes.yaml``（中心平台路由）
  - ``agent_common/api/data/node-levels.yaml``（层级声明表：level / why / evidence）

规则编号：
  L1 声明完整性：两表内全部 capability 必须在层级表登记；层级表不得有悬空条目。
  L2 跨节点不可见：声明 ``node`` 的能力不得出现在中心平台路由（中心面向调用方）。
  L3 中心不下沉节点通道：声明 ``center`` 的能力不得出现在节点传输专属通道
     （``via: node`` / ``channel: node`` / ``node/`` 前缀）。
  L4 命名空间不变量：``knowledge.*``、``library.*`` 必须为 center；
     ``sandbox.*``、``host.*``、``exec.*`` 必须为 node。
  L5 证据真实：``evidence`` 指向的实现/契约文件必须逐条真实存在。
  L6 需求树挂接（报告项，不判红）：``nodes-*``/``sandbox-*``/``knowledge-*``/
     ``library-*`` 层级需求在 demands 目录缺条目时列出。

退出码：有 L1–L5 违规即非 0；L6 缺口只进报告。``--self-test`` 注入样本断言会咬。

兼容 Python 3.8：无 match、无 functools.cache、无 X|Y 运行时求值。
"""
from __future__ import annotations

import argparse
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import yaml

ROOT = Path(__file__).resolve().parents[1]
API_DATA = ROOT / "ai_new" / "modules" / "agent_common" / "api" / "data"
CAP_YAML = API_DATA / "capability-routes.yaml"
PLAT_YAML = API_DATA / "platform-routes.yaml"
LEVELS_YAML = API_DATA / "node-levels.yaml"
DEMAND_DIR = ROOT / "ai_new" / "modules" / "agent_common" / "demand_engine" / "data" / "demands"

VALID_LEVELS = ("center", "node")
# 必须为 center / node 的命名空间前缀
CENTER_PREFIXES = ("knowledge.", "library.")
NODE_PREFIXES = ("sandbox.", "host.", "exec.")
# 中心面向调用方：经 HTTP 闸 / 控制台视图 / 注册面暴露给中心侧
CENTER_CALLER_MARKERS = ("http",)
CENTER_CALLERS = {"view", "registry", "registry/http", "view/ops", "view/sync"}
# 层级需求前缀 -> 命名空间前缀
DEMAND_GROUPS = (
    ("nodes-", "nodes."),
    ("sandbox-", "sandbox."),
    ("knowledge-", "knowledge."),
    ("library-", "library."),
)


class Violation:
    __slots__ = ("code", "capability", "message")

    def __init__(self, code: str, capability: str, message: str):
        self.code = code
        self.capability = capability
        self.message = message

    def line(self) -> str:
        return "[%s] %s —— %s" % (self.code, self.capability, self.message)


def _load(path: Path) -> dict:
    if not path.exists():
        return {}
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def build_universe(cap_doc: dict, plat_doc: dict) -> Dict[str, str]:
    """capability -> 来源表名。"""
    universe: Dict[str, str] = {}
    for name in (cap_doc.get("capabilities") or {}).keys():
        universe[name] = "capability-routes.yaml"
    for name in (plat_doc.get("routes") or {}).keys():
        universe.setdefault(name, "platform-routes.yaml")
    return universe


def _is_center_facing(entry: dict) -> bool:
    caller = str(entry.get("caller") or "")
    if any(m in caller for m in CENTER_CALLER_MARKERS):
        return True
    return caller in CENTER_CALLERS


def _is_node_channel(name: str, entry: dict) -> bool:
    if str(entry.get("via") or "") == "node" or str(entry.get("channel") or "") == "node":
        return True
    return name.startswith("node/")


def evaluate(universe: Dict[str, str], levels_doc: dict, plat_doc: dict,
             evidence_root: Path) -> List[Violation]:
    """纯判定：输入结构化文档，返回违规列表。evidence_root 用于校验证据文件存在。"""
    violations: List[Violation] = []
    levels = levels_doc.get("levels") or {}
    platform = plat_doc.get("routes") or {}

    # L1 声明完整性 / 悬空
    for name in universe:
        if name not in levels:
            violations.append(Violation("L1", name, "未在 node-levels.yaml 登记层级声明"))
    for name in levels:
        if name not in universe:
            violations.append(Violation("L1", name, "层级表悬空条目：两表均无此能力"))

    for name, decl in levels.items():
        if not isinstance(decl, dict):
            violations.append(Violation("L1", name, "声明结构不是映射（需 level/why/evidence）"))
            continue
        level = decl.get("level")
        if level not in VALID_LEVELS:
            violations.append(Violation("L1", name, "level 必须是 center|node（现=%r）" % level))
            continue
        if not str(decl.get("why") or "").strip():
            violations.append(Violation("L1", name, "缺少 why 层级理由"))

        # L4 命名空间不变量
        for prefix in CENTER_PREFIXES:
            if name.startswith(prefix) and level != "center":
                violations.append(Violation("L4", name, "%s* 必须为 center" % prefix.rstrip(".")))
        for prefix in NODE_PREFIXES:
            if name.startswith(prefix) and level != "node":
                violations.append(Violation("L4", name, "%s* 必须为 node" % prefix.rstrip(".")))

        # L2 node 不得出现在中心平台路由
        if level == "node" and name in platform and _is_center_facing(platform[name]):
            violations.append(Violation("L2", name,
                                       "node 级能力出现在中心平台路由（caller=%s，跨节点可见）"
                                       % platform[name].get("caller")))
        # L3 center 不得下沉节点通道
        if level == "center" and name in platform and _is_node_channel(name, platform[name]):
            violations.append(Violation("L3", name, "center 级能力登记在节点传输专属通道"))

        # L5 证据真实存在
        evidence = decl.get("evidence") or []
        if isinstance(evidence, str):
            evidence = [evidence]
        if not evidence:
            violations.append(Violation("L5", name, "缺少 evidence 证据路径"))
        for rel in evidence:
            rel = str(rel)
            if not (evidence_root / rel).exists():
                violations.append(Violation("L5", name, "证据文件不存在：%s" % rel))
    return violations


def _referenced_routes(demand_dir: Path) -> set:
    """收集需求 do 树里 call 引用到的全部路由。"""
    referenced: set = set()
    if not demand_dir.exists():
        return referenced
    for p in demand_dir.glob("*.yaml"):
        doc = _load(p)
        for step in doc.get("do") or []:
            if isinstance(step, dict) and step.get("call"):
                referenced.add(str(step["call"]))
    return referenced


def demand_gaps(universe: Dict[str, str], levels_doc: dict, demand_dir: Path) -> List[str]:
    """L6 报告项：层级需求挂接缺口（不判红）。

    口径：命名空间内能力若既没有同前缀需求条目，也没被任何需求 do 树 call 引用，列出。
    """
    gaps: List[str] = []
    existing = {p.stem for p in demand_dir.glob("*.yaml")} if demand_dir.exists() else set()
    referenced = _referenced_routes(demand_dir)
    for prefix, cap_prefix in DEMAND_GROUPS:
        caps = [n for n in universe if n.startswith(cap_prefix)]
        if not caps:
            continue
        group_matched = [d for d in existing if d.startswith(prefix)]
        if not group_matched:
            gaps.append("命名空间 %s* 没有任何 %s-* 需求条目" % (cap_prefix, prefix.rstrip("-")))
        for name in caps:
            if name in referenced:
                continue
            suffix = name.split(".", 1)[1].replace(".", "-") if "." in name else ""
            if suffix and ("%s%s" % (prefix, suffix) in existing):
                continue
            gaps.append("能力 %s 未挂到 %s-* 需求（do 树无 call 引用，近似条目 %s%s 缺失）"
                        % (name, prefix.rstrip("-"), prefix, suffix))
    return gaps


def run(root: Path) -> Tuple[int, List[Violation], List[str]]:
    cap_doc = _load(root / "ai_new/modules/agent_common/api/data/capability-routes.yaml")
    plat_doc = _load(root / "ai_new/modules/agent_common/api/data/platform-routes.yaml")
    levels_doc = _load(root / "ai_new/modules/agent_common/api/data/node-levels.yaml")
    universe = build_universe(cap_doc, plat_doc)
    violations = evaluate(universe, levels_doc, plat_doc, root)
    gaps = demand_gaps(universe, levels_doc,
                       root / "ai_new/modules/agent_common/demand_engine/data/demands")
    return (1 if violations else 0), violations, gaps


def _self_test() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="gate-levels-self-"))
    try:
        api = tmp / "ai_new/modules/agent_common/api/data"
        api.mkdir(parents=True)
        (api / "capability-routes.yaml").write_text(
            "capabilities:\n  demo.center_cap:\n    calls: []\n"
            "  demo.node_cap:\n    calls: []\n"
            "  knowledge.x:\n    calls: []\n"
            "  sandbox.y:\n    calls: []\n", encoding="utf-8")
        (api / "platform-routes.yaml").write_text(
            "routes:\n"
            "  demo.node_cap:\n    caller: http-gate\n"
            "  demo.center_cap:\n    via: node\n"
            "  knowledge.x:\n    caller: internal\n"
            "  sandbox.y:\n    caller: internal\n"
            "  demo.orphan_plat:\n    caller: internal\n", encoding="utf-8")
        (api / "node-levels.yaml").write_text(
            "levels:\n"
            "  demo.center_cap:\n    level: center\n    why: 中心业务能力\n"
            "    evidence: [ai_new/modules/agent/demo/__init__.py]\n"
            "  demo.node_cap:\n    level: node\n    why: 节点本地原语\n"
            "    evidence: [ai_new/modules/agent/demo/__init__.py]\n"
            "  knowledge.x:\n    level: node\n    why: 故意写错\n"
            "    evidence: [ai_new/modules/agent/demo/__init__.py]\n"
            "  sandbox.y:\n    level: node\n    why: 沙箱原语\n"
            "    evidence: [ai_new/modules/agent/demo/missing.py]\n"
            "  demo.orphan_decl:\n    level: center\n    why: 悬空\n"
            "    evidence: [ai_new/modules/agent/demo/__init__.py]\n",
            encoding="utf-8")
        demo = tmp / "ai_new/modules/agent/demo"
        demo.mkdir(parents=True)
        (demo / "__init__.py").write_text("", encoding="utf-8")

        code, violations, gaps = run(tmp)
        codes = {}
        for v in violations:
            codes[v.code] = codes.get(v.code, 0) + 1
        expected = {"L1", "L2", "L3", "L4", "L5"}
        got = set(codes)
        missing = expected - got
        if code == 0 or not violations:
            print("SELF-TEST 失败：违规样本未被抓到（退出码=%d，条数=%d）" % (code, len(violations)))
            return 1
        if missing:
            print("SELF-TEST 失败：缺规则命中 %s；已命中 %s" % (sorted(missing), sorted(got)))
            for v in violations:
                print("  " + v.line())
            return 1

        # 干净样本：全部登记、层级一致、证据存在、无悬空
        clean = Path(tempfile.mkdtemp(prefix="gate-levels-clean-"))
        try:
            capi = clean / "ai_new/modules/agent_common/api/data"
            capi.mkdir(parents=True)
            (capi / "capability-routes.yaml").write_text(
                "capabilities:\n  demo.ok:\n    calls: []\n", encoding="utf-8")
            (capi / "platform-routes.yaml").write_text("routes: {}\n", encoding="utf-8")
            (capi / "node-levels.yaml").write_text(
                "levels:\n  demo.ok:\n    level: center\n    why: 中心业务能力\n"
                "    evidence: [ai_new/modules/agent/demo/__init__.py]\n", encoding="utf-8")
            cdemo = clean / "ai_new/modules/agent/demo"
            cdemo.mkdir(parents=True)
            (cdemo / "__init__.py").write_text("", encoding="utf-8")
            ccode, cbad, _ = run(clean)
            if ccode != 0 or cbad:
                print("SELF-TEST 失败：干净样本被误判：")
                for v in cbad:
                    print("  " + v.line())
                return 1
        finally:
            shutil.rmtree(str(clean), ignore_errors=True)

        print("SELF-TEST 通过：注入样本命中 %d 条违规（%s），干净样本 0 误判。"
              % (len(violations), "/".join(sorted(got))))
        return 0
    finally:
        shutil.rmtree(str(tmp), ignore_errors=True)


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="层级判定门禁")
    parser.add_argument("--self-test", action="store_true", help="临时目录注入样本自检")
    args = parser.parse_args(argv)

    if args.self_test:
        return _self_test()

    code, violations, gaps = run(ROOT)
    if violations:
        print("层级判定门禁失败（%d 条）：" % len(violations))
        for v in violations:
            print("  " + v.line())
    else:
        print("层级判定门禁通过：声明完整、center/node 互斥、证据真实。")
    if gaps:
        print("需求挂接缺口（报告项，不判红）：")
        for g in gaps:
            print("  - " + g)
    return code


if __name__ == "__main__":
    sys.exit(main())
