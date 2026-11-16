"""健康模块：探针与聚合的纯计算；uptime 起点在装配期注入。"""
from __future__ import annotations

from .private import _pure

_MOUNT = {"started": 0.0, "modules": []}


def setup(ctx):
    """装配入口：只收数据（起点先占位，模块清单在 start 期补齐）。"""
    _MOUNT["started"] = 0.0
    _MOUNT["modules"] = []

    def _with_mount(fn, payload):
        data = dict(mount())
        data["now"] = ctx.clock.now()["ts"]
        if payload:
            data.update(payload)
        return fn(data)

    for name, fn in [("health.live", _pure.live), ("health.assemble", _pure.assemble)]:
        ctx.api.register(name, lambda c, p, fn=fn: _with_mount(fn, p), module="health")
    return True


def start(ctx):
    """上线入口：起点与模块清单都是数据，一次性注入。"""
    _MOUNT["started"] = ctx.clock.now()["ts"]
    _MOUNT["modules"] = sorted(ctx.loaded)
    return True


def mount():
    """装配数据：谁要算 uptime，就把这份数据当入参传进来。"""
    return dict(_MOUNT)
