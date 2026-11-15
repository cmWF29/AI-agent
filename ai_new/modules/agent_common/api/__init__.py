"""API 模块：路由注册 + 跨模块调用 + 调用矩阵校验 + 通信通道编译。无任何业务。"""
from __future__ import annotations

from .private import _gen, _registry
from .private._errors import ApiError


def setup(ctx):
    """装配入口：装填 ctx.ApiError 与 ctx.api（这两个面由赋值动作本身声明）。"""
    ctx.ApiError = ApiError
    ctx.api = _registry.Registry(ctx)
    ctx.api.register("api.transport", lambda c, p: ctx.api.transport.describe(),
                     "通信通道绑定（编译产物）", module="api")
    ctx.api.register("api.transport_compile", lambda c, p: compile_transport(ctx),
                     "重新编译通信通道绑定", module="api")
    return ctx.api


def compile_transport(ctx, out=None, deploy=None):
    """把 data/deploy.json 编译成 data/gen/bindings.json（模板代码不变，换拓扑只重编）。"""
    return _gen.compile_transport(ctx, out=out, deploy=deploy)


def register(ctx, name, fn, doc="", module=None, stream=False):
    """注册路由 name（约定 "module.fn"）；stream=True 表示它可以被当流读。"""
    return ctx.api.register(name, fn, doc=doc, module=module, stream=stream)


def call(ctx, name, payload=None, caller=None):
    """调用路由。caller 是发起方模块名，会被调用矩阵校验。"""
    return ctx.api.call(name, payload, caller=caller)


def routes(ctx):
    """全部已注册路由（name/doc/module）。"""
    return ctx.api.routes()


def matrix(ctx):
    """当前调用矩阵数据（懒加载，首次调用时读取 data/rules/calls.json）。"""
    return ctx.api.matrix()


def transport(ctx):
    """当前通信通道绑定（由 api.transport_compile 编译）。"""
    return ctx.api.transport.describe()
