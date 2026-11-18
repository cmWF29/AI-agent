"""运行设施：后台执行需求、执行能力声明的效果清单。

平台层，不认识任何业务名词：只认需求 id 与效果描述。
能力不留副作用：要写什么、要再驱动谁，都算成 effect 交出来，由本模块照单执行。
"""
from __future__ import annotations

from .private import _core


def setup(ctx):
    ctx.runtime = _core.Runtime(ctx)
    ctx.api.register("runtime.apply", ctx.runtime.apply,
                     "执行能力交出的效果清单（写盘/删除/追加/打包/驱动需求）", module="runtime")
    ctx.api.register("runtime.dispatch", ctx.runtime.dispatch,
                     "后台跑一条需求：同一把钥匙已在跑，就先置打断、等它退出、再以新输入重跑",
                     module="runtime")
    ctx.api.register("runtime.stream", _route_stream,
                     "读运行期草稿（内存面，不落盘）：视图轮询看外部 agent 逐行吐出的正文",
                     module="runtime")
    ctx.api.register("runtime.stream_events", _route_stream_events,
                     "SSE 长流：阻塞等待草稿槽变化，事件驱动推草稿快照（内存面，不落盘）",
                     module="runtime", stream=True)
    return True


def _route_stream(ctx, payload):
    return ctx.runtime.stream_get((payload or {}).get("key"))


def _route_stream_events(ctx, payload):
    p = payload or {}
    return ctx.runtime.stream_events(p.get("key"), p.get("cursor"))
