"""需求引擎：业务是结构化的语言，引擎负责让它跑起来。

- **模块**（别处）只提供能力：服务 + 扩展点。
- **需求** 是 `data/demands/*.json`：一段可插拔的业务，用结构化语句写（on / when / do），
  语法见 `private/_lang.py`。

引擎只做装载、路由、解释执行，不认识任何业务名词。需求里所有服务调用都写在语句树的
`call` 字段中，所以既能跑，又能被静态扫描读全 —— 业务不再是运行时的浆糊。
"""
from __future__ import annotations

from .private import _engine


def setup(ctx):
    """装配入口：装填 ctx.demand_engine（需求装载 + 解释执行）。"""
    ctx.demand_engine = _engine.Engine(ctx)
    ctx.api.register("demand_engine.run", lambda c, p: ctx.demand_engine.run_callable(
        p.get("id"), p.get("input") or {}), "按名跑一段编排需求", module="demand_engine")
    ctx.api.register("demand_engine.list", lambda c, p: ctx.demand_engine.items(),
                     "当前需求（on/do/enabled）", module="demand_engine")
    return ctx.demand_engine


def list_demands(ctx):
    """当前全部需求（含 on/do/enabled）。"""
    return ctx.demand_engine.items()


def dispatch(ctx, hook, envelope):
    """把一次 hook 触发交给需求引擎。"""
    return ctx.demand_engine.dispatch(hook, envelope)
