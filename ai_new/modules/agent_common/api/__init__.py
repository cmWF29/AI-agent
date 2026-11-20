"""API 模块：路由注册 + 跨模块消息 + 消息契约 + 通信通道编译。无任何业务。"""
from __future__ import annotations

import atexit

from .private import _gen, _registry, _serve
from .private._errors import ApiError


def setup(ctx):
    """装配入口：装填 ctx.ApiError 与 ctx.api（这两个面由赋值动作本身声明）。"""
    ctx.ApiError = ApiError
    ctx.api = _registry.Registry(ctx)
    ctx.api.register("api.snapshot", _route_snapshot,
                     "通信通道 + 消息契约的现状快照（谁走直连/内存/网络，路由各自收发什么）",
                     module="api")
    ctx.api.register("api.transport_compile", _route_compile,
                     "按部署意图 data/deploy.yaml 重编通信绑定（只在进程内可调）",
                     module="api", internal=True)
    return ctx.api


def start(ctx):
    """装配末尾（绑定已编好）：按绑定里实际用到的通道起本机 IPC 监听。

    默认全直连时什么都不开——单机就是单进程，不额外占端口和 socket 文件。
    """
    bindings = ctx.api.transport.bindings()
    kinds = _serve.kinds_in(bindings)
    if not kinds:
        return []
    server = _serve.Server(ctx)
    started = server.start(bindings.get("listen") or {}, kinds)
    atexit.register(server.stop)
    ctx.api.server = server
    return started


def _route_snapshot(ctx, payload):
    """现状快照：通道分布 + 路由契约键，给需求层与巡检看，不改任何状态。"""
    routes = ctx.api.routes()
    return {"transport": ctx.api.transport.describe(),
            "routes": len(routes),
            "items": routes}


def _route_compile(ctx, payload):
    return compile_transport(ctx, out=(payload or {}).get("out"),
                             deploy=(payload or {}).get("deploy"))


def compile_transport(ctx, out=None, deploy=None):
    """把部署意图 data/deploy.yaml 编译成 data/gen/bindings.yaml（模板代码不变，换拓扑只重编）。

    编译完立刻让运输层丢掉旧绑定缓存，否则装配早期读过一次就把旧通道钉死到进程结束。
    """
    record = _gen.compile_transport(ctx, out=out, deploy=deploy)
    if getattr(ctx, "api", None) is not None:
        ctx.api.transport.reload()
    return record


def register(ctx, name, fn, doc="", module=None, stream=False):
    """注册路由 name（约定 "module.fn"）；stream=True 表示它可以被当流读。"""
    return ctx.api.register(name, fn, doc=doc, module=module, stream=stream)


def call(ctx, name, payload=None, caller=None):
    """调用路由。caller 是发起方模块名：只有需求（demand_engine）与被装配的系统面能调。"""
    return ctx.api.call(name, payload, caller=caller)


def notify(ctx, name, payload=None, caller=None):
    """单向通知：不取返回值，只承诺"已投递"。"""
    return ctx.api.notify(name, payload, caller=caller)


def routes(ctx):
    """全部已注册路由（name/doc/module + 契约的 in/out 键）。"""
    return ctx.api.routes()


def contract(ctx, name=None):
    """消息契约：给名字返回单条，不给就返回全表（来自各模块 data/api.yaml）。"""
    return ctx.api.contract(name) if name else ctx.api._load_contracts()


def contract_warnings(ctx):
    """契约校验的告警（warn 模式下缺必填字段的记录，最多留 200 条）。"""
    return ctx.api.warn_log()


def transport(ctx):
    """当前通信通道绑定（direct / memory / http 的分布与来源）。"""
    return ctx.api.transport.describe()
