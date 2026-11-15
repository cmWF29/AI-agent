"""工具模块：注册、白名单、执行、输出落盘。无任何业务。"""
from __future__ import annotations

from .private import _registry

def setup(ctx):
    """装配入口：ctx.tools 指向注册表。"""
    ctx.tools = _registry.ToolRegistry(ctx)
    ctx.api.register("tools.execute",
                     lambda c, payload: ctx.tools.execute(payload.get("name"),
                                                       payload.get("args"),
                                                       session=payload.get("session")),
                     module="tools")
    return ctx.tools

def register(ctx, name, desc, params, fn, module=None, kinds=None):
    """注册工具；kinds 为会话类型白名单（None=所有会话可见）。"""
    return ctx.tools.register(name, desc, params, fn, module=module, kinds=kinds)

def execute(ctx, name, args, session=None):
    """执行工具，输出超阈值时落盘 data/toolout/。"""
    return ctx.tools.execute(name, args, session=session)

def list_tools(ctx):
    """全部工具（脱敏描述）。"""
    return ctx.tools.list_tools()
