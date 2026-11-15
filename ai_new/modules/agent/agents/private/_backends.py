"""后端档案实现。"""
from __future__ import annotations

from . import _guard


def setup(ctx):
    for name, fn in [
        ("agents.backends", _route_backends),
        ("agents.pick", _route_pick),
    ]:
        ctx.api.register(name, fn, module="agents")
    return True


def backends(ctx):
    cfg = ctx.cfg.get("agents", {})
    items = cfg.get("backends") or [{
        "id": "api", "cn": "内置 API",
        "kind": "api",
    }]
    return {"default": cfg.get("default") or "api", "items": items}


def pick(ctx, backend=""):
    items = backends(ctx).get("items") or []
    want = backend or backends(ctx).get("default") or "api"
    hit = next((b for b in items if b.get("id") == want), None)
    if not hit:
        raise ctx.ApiError("后端不存在: %s" % want, code="no_backend", status=404)
    guard = _guard.check(ctx)
    return {"backend": hit, "guard": guard}


def _route_backends(ctx, payload):
    return backends(ctx)


def _route_pick(ctx, payload):
    return pick(ctx, payload.get("backend") or "")
