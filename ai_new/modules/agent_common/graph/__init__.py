"""图模式能力：并行合并 / 步数上限 / 门禁原因 / 子流程清单的纯规则纯函数。

能力不认识业务：合并策略、上限口径、归属规则都由入参数据驱动；不读盘、不起后台任务。
纯函数只在模块内部与纯函数层被调用，不注册为 API 路由。
"""
from __future__ import annotations

from .private import _pure


def setup(ctx):
    return True
