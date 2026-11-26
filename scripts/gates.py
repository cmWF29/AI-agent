#!/usr/bin/env python3
"""分层防护统一入口：python3 scripts/gates.py [--only L0,L1,L2] [--json] [--timeout N]

分层口径（与 docs/testing-layers.md 一致）：
  L0 静态/架构/文档/映射  —— 转调九道门禁（含死代码/文档同步/文案/层级）
  L1 后端单元(UT)         —— 转调既有 8 个 unittest 模块
  L2 接口契约            —— 真装配 + 真 HTTP 闸，不可信输入/鉴权/越权/穿越/幂等
  L3 系统级 E2E(ST)      —— 真浏览器 + 真后端跑项目/工单闭环（岗位全链路仍待扩）
  L4 韧性                —— kill -9 / 租约 / 重复投递 / 恢复后不双跑
  L6 HTTP 黑盒业务 E2E   —— 24 个场景：项目/工单/知识/定时/节点/并发/权限/壳层

每一层独立可跑；汇总给人看（绿/红 + 失败摘要 + 耗时），``--json`` 出机读结果。
既有 ``python test_start.py`` 与本入口并行存在，互不吞掉。
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts" / "lib"))

from layers import (l0_static, l1_unit, l2_contract, l3_e2e, l4_resilience,  # noqa: E402
                    l6_blackbox)
from report import LayerResult, render_text, render_json, exit_code  # noqa: E402

# 门禁名单唯一定义在 l0_static.GATES（docsync/copy/levels 已写进去），这里不再二次追加，
# 避免同名门禁跑两遍。

# 层 id -> 运行函数。L4 仍是接线骨架。
LAYERS = [
    ("L0", "静态/架构/文档/映射", l0_static.run),
    ("L1", "后端单元（纯函数/状态机/并发/幂等/边界）", l1_unit.run),
    ("L2", "接口契约（不可信输入/鉴权/越权/穿越/幂等）", l2_contract.run),
    ("L3", "系统级 E2E（真浏览器 + 真后端）", l3_e2e.run),
    ("L4", "韧性（中断恢复/租约/幂等/不双跑）", l4_resilience.run),
    ("L6", "HTTP 黑盒业务 E2E（真服务 + 真 RPC + 真并发）", l6_blackbox.run),
]


def _parse_only(value: str | None) -> list[str]:
    if not value:
        return [lid for lid, _, _ in LAYERS]
    out: list[str] = []
    for item in value.split(","):
        item = item.strip()
        if item:
            out.append(item)
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="分层防护统一入口")
    parser.add_argument("--only", help="只跑指定层/名单，逗号分隔，如 L0,L2 或 controls,test_core")
    parser.add_argument("--json", action="store_true", help="输出机读 JSON")
    parser.add_argument("--timeout", type=float, default=120.0, help="单层超时秒数")
    args = parser.parse_args(argv)

    only = _parse_only(args.only)
    results: list[LayerResult] = []
    for lid, title, runner in LAYERS:
        # 名单式选择：可以给层 ID（L0/L1/...），也可以给层内门禁名/模块名。
        # 未命中本层的名单要整层跳过，不能把“只跑 L0”变成“五层全跑”。
        sel = None
        if only and lid not in only:
            if lid == "L0":
                sel = [g[0] for g in l0_static.GATES if g[0] in only]
            elif lid == "L1":
                sel = [m for m in l1_unit.MODULES if m in only]
            if not sel:
                continue
        started = time.monotonic()
        try:
            if lid == "L0":
                res = runner(selected=sel, timeout=args.timeout)
            elif lid == "L1":
                res = runner(selected=sel, timeout=args.timeout)
            else:
                res = runner(timeout=args.timeout)
        except Exception as e:  # noqa: BLE001 —— 层级兜底，记红不崩入口
            res = LayerResult(
                layer=lid, title=title, ok=False, duration=time.monotonic() - started,
                checks=[], output="", note="层异常: %s: %s" % (type(e).__name__, e))
        results.append(res)

    if args.json:
        print(render_json(results))
    else:
        print(render_text(results))
    return exit_code(results)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
