"""HTTP 模块：路由 → api 注册表、静态资源、鉴权。无任何业务。

分两段：setup 只建服务绑端口；start 才真正接收请求。这样"监听必须最后"
就不是一条要人记住的规则，而是由生命周期结构保证的 —— 组合根在所有模块
setup 完成后才调用 start。
"""
from __future__ import annotations

from .private import _server


def setup(ctx):
    """装配入口：建服务、绑端口（不接请求），并预留监听与失败两个 hook 点。"""
    ctx.http = _server.setup(ctx)
    return ctx.http


def start(ctx):
    """启动入口（第二段）：开始接收请求。"""
    return _server.start(ctx, ctx.http)
