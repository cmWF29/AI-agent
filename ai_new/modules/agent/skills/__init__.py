"""技能模块：技能卡的筛选与取用；执行步骤已经变成需求（skill-<id>）。"""
from __future__ import annotations

from .private import _pure


def setup(ctx):
    for name, fn in [
        ("skills.screen", _pure.screen),
        ("skills.get", _pure.getp),
    ]:
        ctx.api.register(name, lambda payload, fn=fn: fn(payload), module="skills")
    return True
