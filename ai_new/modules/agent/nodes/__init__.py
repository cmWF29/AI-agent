"""节点协调模块：控制面注册、心跳、容量/负载、租约、fencing、项目→节点分配。

职责边界：
- 分配关系由本模块自持 data（按 project id 键），不往 projects 记录结构上加字段；
- 项目内可变状态（工单/知识/交付件/日志）仍归各模块自己的路径，本模块只决定
  "该由哪个节点执行"，不做共享数据库或共享文件系统；
- 落盘是业务动作：本模块只产出 ``write`` effect，由需求 runtime 经 store 路由落地。
"""
from __future__ import annotations

from .private import _pure

_PATH = "registry.json"
_MOUNT = _pure.empty_state()


def _now(ctx):
    row = ctx.api.call("clock.now", {}, caller=None)
    return (row or {}).get("ts") or 0.0


def _read_state(ctx):
    row = ctx.api.call("store.read", {"module": "agent/nodes", "path": _PATH},
                       caller=None)
    rec = row.get("value")
    if isinstance(rec, dict):
        state = _pure.empty_state()
        for key in ("nodes", "leases", "backups"):
            if isinstance(rec.get(key), dict):
                state[key] = rec[key]
        return state
    return _pure.empty_state()


def _effect(state):
    return {"kind": "write", "module": "agent/nodes",
            "path": _PATH, "value": state}


def setup(ctx):
    """装配入口：读自持台账，注册协调路由；不产生外部效果。"""
    global _MOUNT
    _MOUNT = _read_state(ctx)
    routes = [
        ("nodes.register", _route_register),
        ("nodes.heartbeat", _route_heartbeat),
        ("nodes.acquire", _route_acquire),
        ("nodes.renew", _route_renew),
        ("nodes.release", _route_release),
        ("nodes.fence_check", _route_fence_check),
        ("nodes.nodes_view", _route_nodes_view),
        ("nodes.assignments", _route_assignments),
        ("nodes.overview", _route_overview),
        ("nodes.status", _route_status),
        ("nodes.project_node", _route_project_node),
        ("nodes.backups", _route_backups),
        ("nodes.backup_record", _route_backup_record),
        ("nodes.snapshot_plan", _route_snapshot_plan),
        ("nodes.verify_snapshot", _route_verify_snapshot),
        ("nodes.pick_node", _route_pick_node),
        ("nodes.reassign", _route_reassign),
        ("nodes.migrations", _route_migrations),
    ]
    for name, fn in routes:
        ctx.api.register(name, fn, module="nodes")
    return True


# ---------------------------------------------------------------- 协调路由

def _route_register(ctx, payload):
    res = _pure.register(_MOUNT, payload or {}, _now(ctx))
    if res.get("ok"):
        return {"ok": True, "node": res["node"], "effects": [_effect(_MOUNT)]}
    return res


def _route_heartbeat(ctx, payload):
    payload = payload or {}
    res = _pure.heartbeat(_MOUNT, payload.get("node"), payload.get("load"), _now(ctx))
    if res.get("ok"):
        return {"ok": True, "node": res["node"], "effects": [_effect(_MOUNT)]}
    return res


def _route_acquire(ctx, payload):
    payload = payload or {}
    res = _pure.acquire(
        _MOUNT, payload.get("project"), payload.get("node"), _now(ctx),
        ttl=payload.get("ttl"), tier=payload.get("tier"))
    if res.get("ok"):
        return {"ok": True, "lease": res["lease"], "reused": res["reused"],
                "effects": [_effect(_MOUNT)]}
    return res


def _route_renew(ctx, payload):
    payload = payload or {}
    res = _pure.renew(_MOUNT, payload.get("project"), payload.get("token"), _now(ctx))
    if res.get("ok"):
        return {"ok": True, "lease": res["lease"], "effects": [_effect(_MOUNT)]}
    return res


def _route_release(ctx, payload):
    payload = payload or {}
    res = _pure.release(_MOUNT, payload.get("project"), payload.get("token"), _now(ctx))
    if res.get("ok"):
        return {"ok": True, "lease": res["lease"], "effects": [_effect(_MOUNT)]}
    return res


def _route_fence_check(ctx, payload):
    payload = payload or {}
    return _pure.fence_check(
        _MOUNT, payload.get("project"), payload.get("token"), payload.get("epoch"))


def _route_nodes_view(ctx, payload):
    ttl = (payload or {}).get("ttl")
    return {"ok": True, "nodes": _pure.nodes_view(_MOUNT, _now(ctx), ttl=ttl)}


def _route_assignments(ctx, payload):
    return {"ok": True, "assignments": _pure.assignments_view(_MOUNT)}


def _route_overview(ctx, payload):
    now = _now(ctx)
    return {"ok": True, "nodes": _pure.nodes_view(_MOUNT, now),
            "assignments": _pure.assignments_view(_MOUNT)}


def _route_status(ctx, payload):
    """运维页只读组合视图：节点状态（在线/假死/租约剩余）+ 归属 + 备份状态。"""
    payload = payload or {}
    now = _now(ctx)
    return {"ok": True, **_pure.status_view(_MOUNT, now,
                                            ttl=payload.get("ttl"))}


def _route_project_node(ctx, payload):
    return {"ok": True, "assignment": _pure.project_node(_MOUNT, (payload or {}).get("project"))}


def _route_backups(ctx, payload):
    return {"ok": True, "backups": _pure.backups_view(_MOUNT)}


def _route_backup_record(ctx, payload):
    payload = payload or {}
    record = _pure.record_backup(_MOUNT, payload.get("project"), payload.get("snapshot") or {})
    return {"ok": True, "backup": record, "effects": [_effect(_MOUNT)]}


def _route_snapshot_plan(ctx, payload):
    payload = payload or {}
    return _pure.plan_snapshot(payload.get("project"), payload.get("entries"), _now(ctx))


def _route_verify_snapshot(ctx, payload):
    payload = payload or {}
    return _pure.verify_manifest(payload.get("manifest") or {}, payload.get("digests") or {})


def _route_pick_node(ctx, payload):
    payload = payload or {}
    return {"ok": True, **_pure.pick_node(
        _MOUNT, payload.get("project"), _now(ctx), payload.get("policy"))}


def _route_reassign(ctx, payload):
    payload = payload or {}
    res = _pure.reassign(
        _MOUNT, payload.get("project"), _now(ctx),
        policy=payload.get("policy"), candidate=payload.get("candidate"),
        reason=payload.get("reason"), checkpoint=payload.get("checkpoint"))
    if res.get("migration") is not None:
        return {**res, "effects": [_effect(_MOUNT)]}
    return res


def _route_migrations(ctx, payload):
    return {"ok": True, "migrations": _pure.migrations_view(_MOUNT)}
