"""隔离档位模块：本机能力上报、档位选择、执行计划。

- 策略与计划纯计算在 private/_pure.py；
- OS 事实探测走 host 路由（二进制在不在 PATH）与 store 路由（路径隔离/锁档位）；
- 本模块不起进程、不写盘；强档真正起进程由 exec 能力在需求编排下执行。
"""
from __future__ import annotations

from .private import _pure

_PROBE_BINARIES = ("unshare", "bwrap", "chroot", "systemd-run")


def _host_which(ctx, name):
    row = ctx.api.call("host.which", {"name": name}, caller=None)
    return bool((row or {}).get("found"))


def setup(ctx):
    routes = [
        ("sandbox.capability", _route_capability),
        ("sandbox.pick_tier", _route_pick_tier),
        ("sandbox.plan", _route_plan),
    ]
    for name, fn in routes:
        ctx.api.register(name, fn, module="sandbox")
    return True


def _route_capability(ctx, payload):
    """本机隔离能力组合视图：档位描述 + 二进制探测 + 锁/路径隔离档位。"""
    binaries = {name: _host_which(ctx, name) for name in _PROBE_BINARIES}
    lock = ctx.api.call("store.doc_lock_capability", {}, caller=None)
    workspace = ctx.api.call("store.workspace",
                             {"project": "capability-probe"}, caller=None)
    isolate_cap = (workspace or {}).get("capability") or {}
    return {
        "ok": True,
        "tiers": _pure.describe(),
        "binaries": binaries,
        "lock": lock,
        "path_isolation": isolate_cap,
    }


def _route_pick_tier(ctx, payload):
    return {"ok": True, **_pure.pick_tier(payload or {})}


def _route_plan(ctx, payload):
    payload = payload or {}
    return _pure.plan(payload.get("project"), payload.get("tier"),
                       payload.get("workspace") or {})
