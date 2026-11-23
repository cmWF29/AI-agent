"""需求 DSL 与需求→用例映射的结构化读取。

与 demand_engine.private._lang 同口径提取 call/send 路由；映射表现算现写，
不读缓存、不依赖手工表格。
"""
from __future__ import annotations

from pathlib import Path

import yaml

DEMANDS_REL = Path("ai_new/modules/agent_common/demand_engine/data/demands")
CHECKS_REL = Path("ai_new/modules/agent_test/data/checks.yaml")


def routes_of(node) -> list[str]:
    found: list[str] = []
    if isinstance(node, dict):
        if isinstance(node.get("call"), str):
            found.append(node["call"])
        if isinstance(node.get("send"), str):
            found.append(node["send"])
        for value in node.values():
            found.extend(routes_of(value))
    elif isinstance(node, list):
        for value in node:
            found.extend(routes_of(value))
    return found


def _load_yaml(path: Path) -> dict:
    if not path.is_file():
        return {}
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def load_demands(root: Path) -> dict[str, dict]:
    out: dict[str, dict] = {}
    demands_dir = root / DEMANDS_REL
    if not demands_dir.is_dir():
        return out
    for p in sorted(demands_dir.glob("*.yaml")):
        rec = _load_yaml(p)
        if rec.get("id"):
            out[str(rec["id"])] = rec
    return out


def demand_routes(demands: dict[str, dict]) -> set[str]:
    routes: set[str] = set()
    for rec in demands.values():
        routes.update(routes_of(rec.get("do")))
        exp = rec.get("expect") or {}
        for c in exp.get("calls") or []:
            routes.add(str(c))
    return routes


def load_checks(root: Path) -> list[dict]:
    doc = _load_yaml(root / CHECKS_REL)
    return [c for c in (doc.get("checks") or []) if c.get("enabled", True)]


def demand_test_map(demands: dict[str, dict], checks: list[dict]) -> dict[str, list[str]]:
    """需求 → 绑定的检查项 id 列表。"""
    claimed: dict[str, list[str]] = {}
    for c in checks:
        for d in c.get("demands") or []:
            claimed.setdefault(str(d), []).append(str(c.get("id")))
    return {d: claimed.get(d, []) for d in demands}
