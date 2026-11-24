"""节点协调模块：控制面注册、心跳、容量/负载、租约、fencing、项目→节点分配。

职责边界：
- 分配关系由本模块自持 data（按 project id 键），不往 projects 记录结构上加字段；
- 项目内可变状态（工单/知识/交付件/日志）仍归各模块自己的路径，本模块只决定
  "该由哪个节点执行"，不做共享数据库或共享文件系统；
- 落盘是业务动作：本模块只产出 ``write`` effect，由需求 runtime 经 store 路由落地。
"""
from __future__ import annotations

from copy import deepcopy

from .private import _pure

_PATH = "registry.json"
_CAS_RETRIES = 8


def _now(ctx):
    row = ctx.api.call("clock.now", {}, caller=None)
    return (row or {}).get("ts") or 0.0


def _read_state(ctx):
    """读协调台账；每次路由都从 store 读，不持进程内全局副本。

    全局副本会在多进程/多请求之间丢更新；协调状态的唯一真相是持久化记录。
    """
    row = ctx.api.call("store.read", {"module": "agent/nodes", "path": _PATH},
                       caller=None)
    rec = row.get("value")
    state = _pure.empty_state()
    if isinstance(rec, dict):
        for key in state:
            if key in rec:
                state[key] = rec[key]
    return state


def _view_state(ctx):
    """只读视图也要按当前时间推一遍失联回收，展示口径与写入口径一致。"""
    state = _read_state(ctx)
    _pure.sweep_expired(state, _now(ctx))
    return state


def _mutate(ctx, apply):
    """在 CAS 循环里执行纯变更：读 → 失联回收 → 纯函数改 → 期望旧值提交。

    并发方只可能有一个把旧值换成新值；冲突方重读重算。超过重试上限显式报
    ``conflict_exhausted``，不把最后一次覆盖当成成功。每次变更前先回收过期
    租约，避免租约过期后仍被旧节点续用。
    """
    for _attempt in range(_CAS_RETRIES):
        before = _read_state(ctx)
        working = deepcopy(before)
        _pure.sweep_expired(working, _now(ctx))
        result = apply(working)
        if working == before:
            return result
        cas = ctx.api.call("store.cas", {
            "module": "agent/nodes", "path": _PATH,
            "expected": before, "create": True, "value": working}, caller=None)
        if cas.get("ok"):
            result = dict(result)
            result["effects"] = []
            return result
        if not cas.get("conflict"):
            return {"ok": False, "code": cas.get("code") or "cas_error"}
    return {"ok": False, "code": "conflict_exhausted"}


def _node_secret(ctx):
    """节点推送通道共享密钥：只从配置 ``nodes.node_token`` 读。

    环境变量 ``AI_NEW_NODE_TOKEN`` 由 config 引导层载入配置，模块不自己碰环境；
    为空即本机开放态（与 server.auth 开放口径一致），对外部署必须在配置里设强密钥，
    代码里不写死任何默认密钥。
    """
    row = ctx.api.call("config.get", {"key": "nodes.node_token"}, caller=None)
    secret = row.get("value") if isinstance(row, dict) else None
    return str(secret or "")


def _auth_node(ctx, payload):
    """push 通道鉴权：通过返回 None，否则返回拒绝结果 dict（未登录/令牌不符）。"""
    secret = _node_secret(ctx)
    if not secret:
        return None
    if not _pure.token_matches((payload or {}).get("node_token"), secret):
        return {"ok": False, "code": "unauthorized", "reason": "bad_node_token"}
    return None


def setup(ctx):
    """装配入口：注册协调路由；不读全局副本，不产生外部效果。"""
    routes = [
        ("nodes.register", _route_register),
        ("nodes.heartbeat", _route_heartbeat),
        ("nodes.push_register", _route_push_register),
        ("nodes.push_heartbeat", _route_push_heartbeat),
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
    _register_tools(ctx)
    return True


def _msg(ctx):
    row = ctx.api.call("store.read", {"module": "agent/nodes", "path": "messages.yaml"}, caller=None)
    return row.get("value") or {}


def _register_tools(ctx):
    """节点配置岗位的工具接线：只暴露登记、观测与租约申领，不暴露内部台账写。"""
    tools = getattr(ctx, "tools", None)
    if tools is None:
        return
    tpl = _msg(ctx)
    specs = [
        ("nodes_register", "nodes.register", "tool_nodes_register_desc", [
            {"name": "id", "type": "string", "required": True, "desc": "节点标识"},
            {"name": "endpoint", "type": "string", "required": True, "desc": "节点端点"},
            {"name": "transport", "type": "string", "desc": "传输：unix / tcp / direct"},
            {"name": "role", "type": "string", "desc": "entry / executor"},
            {"name": "public_exposed", "type": "boolean", "desc": "是否公网暴露"},
            {"name": "capacity", "type": "object", "desc": "容量：cpu / memory_mb / disk_mb"},
            {"name": "lease_ttl", "type": "number", "desc": "租约 TTL 秒"},
        ]),
        ("nodes_heartbeat", "nodes.heartbeat", "tool_nodes_heartbeat_desc", [
            {"name": "node", "type": "string", "required": True, "desc": "节点标识"},
            {"name": "load", "type": "object", "desc": "负载：running 等"},
        ]),
        ("nodes_view", "nodes.nodes_view", "tool_nodes_view_desc", []),
        ("nodes_project_node", "nodes.project_node", "tool_nodes_project_node_desc", [
            {"name": "project", "type": "string", "required": True, "desc": "项目标识"},
        ]),
        ("nodes_acquire", "nodes.acquire", "tool_nodes_acquire_desc", [
            {"name": "project", "type": "string", "required": True, "desc": "项目标识"},
            {"name": "node", "type": "string", "required": True, "desc": "节点标识"},
            {"name": "ttl", "type": "number", "desc": "租约秒数"},
            {"name": "tier", "type": "string", "desc": "档位：weak / strong"},
        ]),
        ("nodes_backups", "nodes.backups", "tool_nodes_backups_desc", []),
        ("nodes_migrations", "nodes.migrations", "tool_nodes_migrations_desc", []),
    ]
    for name, route, desc_key, params in specs:
        if tools.has(name):
            continue
        tools.register(name, tpl.get(desc_key) or "", params, _tool_fn(route),
                       module="nodes", kinds=["role", "admin"], builtin=True)


def _tool_fn(route):
    def fn(ctx, args, session=None):
        return ctx.api.call(route, dict(args or {}), caller=None)
    return fn


# ---------------------------------------------------------------- 协调路由

def _route_register(ctx, payload):
    return _mutate(ctx, lambda state: _pure.register(state, payload or {}, _now(ctx)))


def _route_heartbeat(ctx, payload):
    payload = payload or {}
    return _mutate(ctx, lambda state: _pure.heartbeat(
        state, payload.get("node"), payload.get("load"), _now(ctx)))


def _route_push_register(ctx, payload):
    """节点主动连云控面（出网）注册：先鉴权，再登记/幂等刷新。

    同 id 重复注册走 ``_pure.register`` 既有幂等口径：保留首次注册时间，只刷新
    endpoint/capacity/last_seen，不产生第二条节点记录。
    """
    payload = payload or {}
    denied = _auth_node(ctx, payload)
    if denied:
        return denied
    return _mutate(ctx, lambda state: {
        **_pure.register(state, payload, _now(ctx)),
        "channel": "push",
    })


def _route_push_heartbeat(ctx, payload):
    """push 通道心跳（租约续期信号）：鉴权后刷新负载与最后见活时间。"""
    payload = payload or {}
    denied = _auth_node(ctx, payload)
    if denied:
        return denied
    return _mutate(ctx, lambda state: {
        **_pure.heartbeat(state, payload.get("node"), payload.get("load"), _now(ctx)),
        "channel": "push",
    })


def _route_acquire(ctx, payload):
    payload = payload or {}
    return _mutate(ctx, lambda state: _pure.acquire(
        state, payload.get("project"), payload.get("node"), _now(ctx),
        ttl=payload.get("ttl"), tier=payload.get("tier")))


def _route_renew(ctx, payload):
    payload = payload or {}
    return _mutate(ctx, lambda state: _pure.renew(
        state, payload.get("project"), payload.get("token"), _now(ctx)))


def _route_release(ctx, payload):
    payload = payload or {}
    return _mutate(ctx, lambda state: _pure.release(
        state, payload.get("project"), payload.get("token"), _now(ctx)))


def _route_fence_check(ctx, payload):
    payload = payload or {}
    return _pure.fence_check(
        _view_state(ctx), payload.get("project"), payload.get("token"),
        payload.get("epoch"), now=_now(ctx))


def _route_nodes_view(ctx, payload):
    ttl = (payload or {}).get("ttl")
    return {"ok": True, "nodes": _pure.nodes_view(_view_state(ctx), _now(ctx), ttl=ttl)}


def _route_assignments(ctx, payload):
    return {"ok": True, "assignments": _pure.assignments_view(_view_state(ctx))}


def _route_overview(ctx, payload):
    state = _view_state(ctx)
    now = _now(ctx)
    return {"ok": True, "nodes": _pure.nodes_view(state, now),
            "assignments": _pure.assignments_view(state)}


def _route_status(ctx, payload):
    """运维页只读组合视图：节点状态（在线/假死/租约剩余）+ 归属 + 备份状态。"""
    payload = payload or {}
    state = _view_state(ctx)
    now = _now(ctx)
    return {"ok": True, **_pure.status_view(state, now, ttl=payload.get("ttl"))}


def _route_project_node(ctx, payload):
    return {"ok": True, "assignment": _pure.project_node(
        _view_state(ctx), (payload or {}).get("project"))}


def _route_backups(ctx, payload):
    return {"ok": True, "backups": _pure.backups_view(_view_state(ctx))}


def _route_backup_record(ctx, payload):
    payload = payload or {}
    return _mutate(ctx, lambda state: {
        "ok": True,
        "backup": _pure.record_backup(state, payload.get("project"),
                                      payload.get("snapshot") or {}),
    })


def _route_snapshot_plan(ctx, payload):
    payload = payload or {}
    return _pure.plan_snapshot(payload.get("project"), payload.get("entries"), _now(ctx))


def _route_verify_snapshot(ctx, payload):
    payload = payload or {}
    return _pure.verify_manifest(payload.get("manifest") or {}, payload.get("digests") or {})


def _route_pick_node(ctx, payload):
    payload = payload or {}
    return {"ok": True, **_pure.pick_node(
        _view_state(ctx), payload.get("project"), _now(ctx), payload.get("policy"))}


def _route_reassign(ctx, payload):
    payload = payload or {}
    return _mutate(ctx, lambda state: _pure.reassign(
        state, payload.get("project"), _now(ctx),
        policy=payload.get("policy"), candidate=payload.get("candidate"),
        reason=payload.get("reason"), checkpoint=payload.get("checkpoint")))


def _route_migrations(ctx, payload):
    return {"ok": True, "migrations": _pure.migrations_view(_view_state(ctx))}
