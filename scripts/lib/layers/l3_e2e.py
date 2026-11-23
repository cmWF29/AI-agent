"""L3 系统级 E2E（ST）层 —— 接线骨架（用例待补）。

计划口径（落地时按此实现，不在此层 mock 断言）：
- 桩启动：``AI_NEW_STUB=1`` 起 ``agent_start.py``，临时数据目录 + 空闲端口；
- 真前端：Playwright/Chromium 打开控制台，跑完整链路
  秘书建单 → 岗位分派 → 状态机迁移（must/forbid 清单）→ 交付件产出；
- 动态可用性检查：遍历真实 DOM 的 ``data-*`` 控件与状态机声明，
  逐个走合法/非法迁移；不做截图比对。

当前状态：本文件为分层入口预留的接线位，E2E 用例尚未补齐（见交付报告未完成项）。
"""
from __future__ import annotations

from report import LayerResult, Timer


def run(timeout: float = 300.0) -> LayerResult:
    with Timer() as t:
        note = "L3 E2E 用例待补：桩启动 + 真前端链路 + DOM 动态状态机检查尚未接线。"
    return LayerResult(
        layer="L3", title="系统级 E2E（真前端 + 桩 LLM 完整链路）",
        ok=False, duration=t.elapsed, checks=[], note=note,
    )
