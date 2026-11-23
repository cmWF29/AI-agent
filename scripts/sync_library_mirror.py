#!/usr/bin/env python3
"""岗位库覆盖层镜像同步：seed.yaml 是唯一事实源，roles.yaml / flows.yaml 由它派生。

背景：library/private/_pure.py 的 _records 把种子记录盖到用户覆盖层之上，内置条目恒以
种子为准；roles.yaml / flows.yaml 只登记运行时用户自建条目。本脚本把 seed.yaml 里的
内置岗位与流程重新镜像到这两个覆盖层文件，避免两处各写各的漂移。

用法：python3 scripts/sync_library_mirror.py
"""
from __future__ import annotations

import yaml
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "ai_new/modules/agent/library/data"
SEED = DATA / "seed.yaml"
ROLES_MIRROR = DATA / "roles.yaml"
FLOWS_MIRROR = DATA / "flows.yaml"

HEADER = """# 本文件由 scripts/sync_library_mirror.py 从 seed.yaml 派生，勿手改内置条目。
# 唯一事实源是 seed.yaml；运行时用户自建条目才写本覆盖层。
"""


def _dump(obj) -> str:
    return yaml.safe_dump(obj, allow_unicode=True, sort_keys=False, default_flow_style=False)


def main() -> None:
    seed = yaml.safe_load(SEED.read_text(encoding="utf-8")) or {}
    roles = {r["id"]: r for r in seed.get("roles") or []}
    flows = {f["id"]: f for f in seed.get("flows") or []}
    ROLES_MIRROR.write_text(HEADER + _dump(roles), encoding="utf-8")
    FLOWS_MIRROR.write_text(HEADER + _dump(flows), encoding="utf-8")
    print("已同步镜像：%s（%d 岗位）、%s（%d 流程）" % (
        ROLES_MIRROR.name, len(roles), FLOWS_MIRROR.name, len(flows)))


if __name__ == "__main__":
    main()
