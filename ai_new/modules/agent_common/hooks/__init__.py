"""钩子机制模块：模块预留扩展点，负责"什么时候"；至于"谁来做"不归它管。

模块自己**不做**任何有政策含义的事（记日志、发通知、统计、告警）。它只在功能
执行的前后预留 hook 点，声明名字和参数：

    # 模块 setup 里声明自己的点
    ctx.hooks.point("sessions.done", ("id", "kind", "summary"))

    # 功能执行到点
    ctx.hooks.emit("sessions.done", {"id": sid, "kind": kind, "summary": s})

点了之后做什么，是**需求层**（`ctx.demand` + `data/demands/*.json`）的事：需求声明
"哪些点、按什么顺序、调哪些服务"。本模块不装订阅者，也不读任何接线表。

于是分工是干净的：模块回答"我什么时候做完了"，需求回答"那之后业务要做什么"。
"""
from __future__ import annotations

from .private import _hooks


def setup(ctx):
    """装配入口：装填 ctx.hooks；派发能力来自需求引擎（这行就是依赖）。"""
    ctx.hooks = _hooks.Hooks(ctx, ctx.demand_engine)
    ctx.api.register("hooks.points", lambda c, p: ctx.hooks.points(), "已声明的 hook 点",
                     module="hooks")
    ctx.api.register("hooks.emit",
                     lambda c, payload: ctx.hooks.emit(
                         payload.get("point") or payload.get("name"),
                         payload.get("payload") or payload.get("data"),
                         payload.get("level", "info")),
                     "触发 hook 点", module="hooks")
    return ctx.hooks


def point(ctx, name, params=()):
    """声明本模块预留的 hook 点（名字必须带本模块前缀）。"""
    return ctx.hooks.point(name, params)


def emit(ctx, name, payload=None, level="info"):
    """触发 hook 点：交给需求层派发，返回每条投递的结果。"""
    return ctx.hooks.emit(name, payload, level)


def points(ctx):
    """已声明的 hook 点（供可见性/测试）。"""
    return ctx.hooks.points()
