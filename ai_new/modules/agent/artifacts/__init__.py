"""交付件模块：分层路径与读取成形。落盘/取盘在 artifacts-* 需求里。"""
from __future__ import annotations

from .private import _pure


def setup(ctx):
    for name, fn in [
        ("artifacts.base", _pure.base),
        ("artifacts.rel", _pure.rel),
        ("artifacts.written", _pure.written),
        ("artifacts.viewed", _pure.viewed),
        ("artifacts.decode", _pure.decode),
        ("artifacts.screen", _pure.screen),
        ("artifacts.stats", _pure.statsp),
    ]:
        ctx.api.register(name, lambda payload, fn=fn: fn(payload), module="artifacts")
    for name, desc, demand in [
        ("artifact_write", "把交付件写到指定层（ticket/project/public）", "artifacts-write"),
        ("artifact_read", "读取交付件（只读）", "artifacts-read"),
    ]:
        ctx.tools.register_demand(name, desc, [
            {"name": "layer", "type": "string", "desc": "public/project/ticket", "required": False},
            {"name": "path", "type": "string", "desc": "相对路径", "required": True},
            {"name": "content", "type": "string", "desc": "写入内容", "required": False},
            {"name": "project", "type": "string", "desc": "project/ticket 层必填", "required": False},
            {"name": "ticket", "type": "string", "desc": "ticket 层必填", "required": False},
        ], demand=demand, module="artifacts")
    return True
