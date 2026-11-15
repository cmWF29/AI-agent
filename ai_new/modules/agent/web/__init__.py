"""Web 模块：控制台只认注册表/需求清单，不认识业务名词。页面读盘归 store。"""
from __future__ import annotations

from .private import _pure


def setup(ctx):
    for name, fn in [("web.rel", _pure.rel), ("web.mime", _pure.mime),
                     ("web.info", _pure.info)]:
        ctx.api.register(name, lambda payload, fn=fn: fn(payload), module="web")
    return True
