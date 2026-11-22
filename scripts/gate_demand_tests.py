"""需求 ↔ 用例映射门禁：映射表现算现写，陈旧就失败。

做两件事：
1) 校验每条需求都绑在某个 check 上，且这个 check 的 module 真有用例文件；
2) 把「需求 → 用例模块」算成一张表写进 agent_test/data/demand-tests.md。
   CI 跑时不写盘，只比对：表不是最新就报错，让人跑 --write 刷新——
   这样加需求/改用例，映射不会悄悄过期。
"""
from __future__ import annotations
import sys
import yaml
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEMANDS = ROOT / "ai_new/modules/agent_common/demand_engine/data/demands"
CHECKS = ROOT / "ai_new/modules/agent_test/data/checks.yaml"
MAP = ROOT / "ai_new/modules/agent_test/data/demand-tests.md"
TESTS = ROOT / "ai_new/modules/agent_test/private"


def _demands():
    out = {}
    for p in sorted(DEMANDS.glob("*.yaml")):
        rec = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        if rec.get("id"):
            out[rec["id"]] = rec
    return out


def _checks():
    return (yaml.safe_load(CHECKS.read_text(encoding="utf-8")) or {}).get("checks") or []


def problems():
    bad = []
    demands, checks = _demands(), _checks()
    claimed = {}
    for c in checks:
        mod = str(c.get("module") or "")
        f = TESTS / (mod + ".py") if mod.startswith("test_") else None
        if f is not None and not f.is_file():
            bad.append("check %s 指向的用例文件不存在: %s" % (c.get("id"), f.name))
        for d in c.get("demands") or []:
            claimed.setdefault(d, []).append(c)
    for d in sorted(set(demands) - set(claimed)):
        bad.append("需求没有绑定用例: %s" % d)
    for d in sorted(set(claimed) - set(demands)):
        bad.append("用例点了不存在的需求: %s" % d)
    # 映射表必须是最新
    fresh = render(demands, checks)
    old = MAP.read_text(encoding="utf-8") if MAP.is_file() else ""
    if old.strip() != fresh.strip():
        bad.append("映射表不是最新：跑 python3 scripts/gate_demand_tests.py --write")
    return bad


def render(demands, checks):
    rows = {}
    for c in checks:
        for d in c.get("demands") or []:
            rows.setdefault(d, []).append(c)
    lines = [
        "<!-- 由 scripts/gate_demand_tests.py 生成，勿手改；改了跑 --write 刷新 -->",
        "",
        "# 需求 → 用例映射",
        "",
        "共 %d 条需求，绑定 %d 个检查项。" % (len(demands), len({c.get('id') for c in checks})),
        "",
        "| 需求 | 业务域 | 检查项 | 用例模块 | 检查项范围 |",
        "| --- | --- | --- | --- | --- |",
    ]
    for d in sorted(demands):
        rec = demands[d]
        tag = (rec.get("tags") or ["-"])[0]
        for c in rows.get(d, []):
            lines.append("| %s | %s | %s | %s.py | %s |" % (
                d, tag, c.get("id"), c.get("module"), c.get("title") or ""))
    return "\n".join(lines) + "\n"


def main():
    write = "--write" in sys.argv
    if write:
        MAP.write_text(render(_demands(), _checks()), encoding="utf-8")
        print("已刷新映射表：%s" % MAP.relative_to(ROOT))
        return 0
    bad = problems()
    if bad:
        print("需求↔用例映射门禁未通过：")
        for x in bad:
            print("  - " + x)
        return 1
    print("需求↔用例映射门禁通过：%d 条需求全部有据可查，映射表是最新的" % len(_demands()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
