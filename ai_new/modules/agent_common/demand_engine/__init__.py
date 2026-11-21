"""需求引擎：业务是结构化的语言，引擎负责让它跑起来。

- **模块**（别处）只提供能力：服务 + 扩展点。
- **需求** 是 `data/demands/*.json`：一段可插拔的业务，用结构化语句写（on / when / do），
  语法见 `private/_lang.py`。

引擎只做装载、路由、解释执行，不认识任何业务名词。需求里所有服务调用都写在语句树的
`call` 字段中，所以既能跑，又能被静态扫描读全 —— 业务不再是运行时的浆糊。
"""
from __future__ import annotations

from .private import _engine


async def _route_run(ctx, payload):
    return await ctx.demand_engine.arun_callable(
        payload.get("id"), payload.get("input") or {})


async def _route_batch(ctx, payload):
    """一次往返跑多条需求：控制台每翻一页要好几份数据，跨公网每条一个 RTT 就是几秒。

    calls 是同层可并行的 [{id, input}]；同一层的依赖关系由调用方（前端）算好，
    这里只负责并发跑、按序回。任一条失败只把那条标错，不拖垮同批其它数据。
    """
    import asyncio

    calls = payload.get("calls") or []
    if not isinstance(calls, list):
        raise ctx.ApiError("calls 必须是列表", code="bad_calls", status=400)

    async def one(call):
        try:
            out = await ctx.demand_engine.arun_callable(
                (call or {}).get("id"), (call or {}).get("input") or {})
            return {"ok": True, "result": out}
        except Exception as exc:  # noqa: BLE001 — 单条失败单独回报
            return {"ok": False, "error": str(exc), "code": getattr(exc, "code", "") or "demand_fail"}

    items = await asyncio.gather(*[one(c) for c in calls])
    return {"items": list(items)}


def setup(ctx):
    """装配入口：装填 ctx.demand_engine（需求装载 + 解释执行）。"""
    ctx.demand_engine = _engine.Engine(ctx)
    ctx.api.register("demand_engine.run", _route_run, "按名跑一段编排需求", module="demand_engine")
    ctx.api.register("demand_engine.batch", _route_batch, "同层多条需求一次往返", module="demand_engine")
    ctx.api.register("demand_engine.list", lambda c, p: ctx.demand_engine.items(),
                     "当前需求（on/do/enabled）", module="demand_engine")
    ctx.api.register("demand_engine.manifest", lambda c, p: ctx.demand_engine.manifest(),
                     "全量需求的可视化形状（执行链 + 树节点）", module="demand_engine")
    ctx.api.register("demand_engine.console", lambda c, p: ctx.demand_engine.console(),
                     "控制台外壳（品牌、词表、配色、导航菜单）", module="demand_engine")
    ctx.api.register("demand_engine.chrome", lambda c, p: ctx.demand_engine.chrome(),
                     "登录页外壳（只回品牌与登录文案，未登录可读）", module="demand_engine")
    return ctx.demand_engine


def list_demands(ctx):
    """当前全部需求（含 on/do/enabled）。"""
    return ctx.demand_engine.items()


def dispatch(ctx, hook, envelope):
    """把一次 hook 触发交给需求引擎。"""
    return ctx.demand_engine.dispatch(hook, envelope)
