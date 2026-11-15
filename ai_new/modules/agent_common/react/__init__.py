"""ReAct 模块：只提供消息/工具形状的纯计算。循环在 react-run 需求里。"""
from __future__ import annotations

from .private import _pure


def setup(ctx):
    for name, fn in [
        ("react.schema", _pure.schema),
        ("react.schemas", _pure.schemas),
        ("react.assistant", _pure.assistant),
        ("react.toolnames", _pure.toolnames),
        ("react.args", _pure.args),
        ("react.toolmsg", _pure.toolmsg),
        ("react.step", _pure.step),
        ("react.result", _pure.result),
        ("react.toolerr", _pure.toolerr),
    ]:
        ctx.api.register(name, lambda payload, fn=fn: fn(payload), module="react")
    return True
