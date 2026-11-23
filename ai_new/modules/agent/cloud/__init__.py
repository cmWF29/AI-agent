"""全局云端资料库：通用存储适配层 + 增量同步 + 公共级配置岗位。

职责边界：
- 适配层：统一连接/上传/下载/列目录/删除/校验接口，多套 profile 切换；
- 增量同步：清单 + 摘要 + 幂等；失败重试指数退避；冲突记录不覆盖；压缩件直推；
- 权限：配置动作仅公共级/管理员；项目角色只看只读状态；
- 落盘：本模块不留副作用，状态变更算成 write/append effect 交需求 runtime.apply。

出站只经平台能力（store/clock/codec/host/archive/net）；不 import 其他业务模块。
"""
from __future__ import annotations

from .private import _pure, _providers, _seal, _archive

_MODULE = "agent/cloud"
_STATE_PATH = "state.yaml"
_AUDIT_PATH = "audit.jsonl"


def setup(ctx):
    pairs = [
        ("cloud.providers", _route_providers),
        ("cloud.profile_save", _route_profile_save),
        ("cloud.profile_list", _route_profile_list),
        ("cloud.profile_get", _route_profile_get),
        ("cloud.profile_switch", _route_profile_switch),
        ("cloud.profile_delete", _route_profile_delete),
        ("cloud.connection_test", _route_connection_test),
        ("cloud.probe_roundtrip", _route_probe_roundtrip),
        ("cloud.sync_plan", _route_sync_plan),
        ("cloud.sync_run", _route_sync_run),
        ("cloud.status", _route_status),
        ("cloud.project_status", _route_project_status),
        ("cloud.audit_list", _route_audit_list),
    ]
    for name, fn in pairs:
        ctx.api.register(name, fn, _doc(name), module="cloud")
    _register_tools(ctx)
    return True


# ---------------------------------------------------------------- 配置与文案

def _cfg(ctx):
    row = ctx.api.call("config.get", {"key": "cloud"}, caller=None)
    return row.get("value") or {}


def _msg(ctx):
    row = ctx.api.call("store.read", {"module": _MODULE, "path": "messages.yaml"}, caller=None)
    return row.get("value") or {}


def _doc(name):
    return {
        "cloud.providers": "提供方清单：类型、通道、落地状态",
        "cloud.profile_save": "保存/更新云端 profile：校验端点与凭证密封",
        "cloud.profile_list": "profile 列表（凭证脱敏）",
        "cloud.profile_get": "单个 profile 详情（凭证脱敏）",
        "cloud.profile_switch": "切换当前生效 profile",
        "cloud.profile_delete": "删除 profile 及其清单与运行摘要",
        "cloud.connection_test": "连通性测试：按 profile 探活",
        "cloud.probe_roundtrip": "往返验证：上传探针→下载→摘要校验→清理",
        "cloud.sync_plan": "增量计划：本地清单 × 上次推送 × 远端现状差分",
        "cloud.sync_run": "执行增量推送：重试退避、冲突记录、清单与摘要落盘",
        "cloud.status": "全局同步状态：当前 profile、最近运行、计数",
        "cloud.project_status": "项目只读视图：是否已纳入同步",
        "cloud.audit_list": "配置变更审计台账（只读）",
    }.get(name, "")


# ---------------------------------------------------------------- 台账读写

def _load_state(ctx):
    row = ctx.api.call("store.read", {"module": _MODULE, "path": _STATE_PATH}, caller=None)
    value = row.get("value") if isinstance(row, dict) else None
    state = _pure.empty_state()
    if isinstance(value, dict):
        for key in state:
            if isinstance(value.get(key), dict):
                state[key] = value[key]
    return state


def _state_effect(state):
    return {"kind": "write", "module": _MODULE, "path": _STATE_PATH, "value": state}


def _json_line(ctx, entry):
    out = ctx.api.call("codec.json_encode", {"value": entry}, caller=None)
    return (out.get("text") or "") + "\n"


def _audit_effect(ctx, entry):
    return {"kind": "append_text", "module": _MODULE, "path": _AUDIT_PATH,
            "text": _json_line(ctx, entry)}


def _audit(ctx, caller, action, target_id, decision, reason):
    now = ctx.api.call("clock.now", {}, caller=None).get("ts")
    entry = {
        "at": now,
        "caller_scope": caller.get("scope"),
        "caller_session": caller.get("session"),
        "role": caller.get("role"),
        "action": action,
        "target_id": target_id or "",
        "decision": decision,
        "reason": reason or "",
    }
    return [_audit_effect(ctx, entry)]


def _err(code, status, message):
    return {"ok": False, "code": code, "status": status, "error": message}


def _denied(ctx, caller, action, reason, tpl):
    effects = _audit(ctx, caller, action, "", "deny", reason)
    return {**_err("forbidden_scope", 403, tpl.get("forbidden_scope") or ""),
            "effects": effects}


# ---------------------------------------------------------------- 路由：提供方与 profile

def _route_providers(ctx, payload):
    return {"items": _providers.provider_meta()}


def _route_profile_save(ctx, payload):
    payload = dict(payload or {})
    caller = _pure.normalize_caller(payload)
    tpl = _msg(ctx)
    verdict = _pure.authorize(caller, "profile_save")
    if verdict["ok"] is False:
        return _denied(ctx, caller, "profile_save", verdict["reason"], tpl)

    cfg = _cfg(ctx)
    validated = _pure.validate_profile(payload, cfg)
    if validated["ok"] is False:
        effects = _audit(ctx, caller, "profile_save", payload.get("id"), "deny",
                         ",".join(validated["errors"]))
        first = validated["errors"][0]
        return {**_err(first, 400, tpl.get(first) or first), "effects": effects}

    state = _load_state(ctx)
    profile = validated["profile"]
    existing = (state.get("profiles") or {}).get(profile["id"])
    # 凭证：入参明文密封落盘；未传凭证则沿用已密封的旧凭证。
    if payload.get("credentials"):
        profile["credentials"] = _seal.seal_map(ctx, payload["credentials"])
    elif existing:
        profile["credentials"] = existing.get("credentials") or {}
    else:
        effects = _audit(ctx, caller, "profile_save", profile["id"], "deny",
                         "bad_credentials")
        return {**_err("bad_credentials", 400, tpl.get("bad_credentials") or ""),
                "effects": effects}

    now = ctx.api.call("clock.now", {}, caller=None).get("ts")
    if existing:
        profile["created"] = existing.get("created") or now
    else:
        profile["created"] = now
    profile["updated"] = now
    state["profiles"][profile["id"]] = profile

    effects = [_state_effect(state)]
    effects += _audit(ctx, caller, "profile_save", profile["id"], "allow", "saved")
    return {"ok": True, "id": profile["id"], "view": _pure.mask_profile(profile),
            "effects": effects}


def _route_profile_list(ctx, payload):
    state = _load_state(ctx)
    items = [_pure.mask_profile(p) for p in (state.get("profiles") or {}).values()]
    return {"items": items, "active": state.get("active") or ""}


def _route_profile_get(ctx, payload):
    state = _load_state(ctx)
    profile = (state.get("profiles") or {}).get(str(payload.get("id") or ""))
    if not profile:
        return _err("not_found", 404, _msg(ctx).get("not_found") or "")
    return {"view": _pure.mask_profile(profile)}


def _route_profile_switch(ctx, payload):
    payload = dict(payload or {})
    caller = _pure.normalize_caller(payload)
    tpl = _msg(ctx)
    verdict = _pure.authorize(caller, "profile_switch")
    if verdict["ok"] is False:
        return _denied(ctx, caller, "profile_switch", verdict["reason"], tpl)
    state = _load_state(ctx)
    pid = str(payload.get("id") or "")
    if pid not in (state.get("profiles") or {}):
        return {**_err("not_found", 404, tpl.get("not_found") or ""),
                "effects": _audit(ctx, caller, "profile_switch", pid, "deny", "not_found")}
    state["active"] = pid
    effects = [_state_effect(state)]
    effects += _audit(ctx, caller, "profile_switch", pid, "allow", "switched")
    return {"ok": True, "id": pid, "effects": effects}


def _route_profile_delete(ctx, payload):
    payload = dict(payload or {})
    caller = _pure.normalize_caller(payload)
    tpl = _msg(ctx)
    verdict = _pure.authorize(caller, "profile_delete")
    if verdict["ok"] is False:
        return _denied(ctx, caller, "profile_delete", verdict["reason"], tpl)
    state = _load_state(ctx)
    pid = str(payload.get("id") or "")
    if pid not in (state.get("profiles") or {}):
        return {**_err("not_found", 404, tpl.get("not_found") or ""),
                "effects": _audit(ctx, caller, "profile_delete", pid, "deny", "not_found")}
    state["profiles"].pop(pid, None)
    state.get("manifests", {}).pop(pid, None)
    state.get("ledger", {}).pop(pid, None)
    if state.get("active") == pid:
        state["active"] = ""
    effects = [_state_effect(state)]
    effects += _audit(ctx, caller, "profile_delete", pid, "allow", "deleted")
    return {"ok": True, "id": pid, "effects": effects}


# ---------------------------------------------------------------- 路由：连通与往返

def _load_profile(ctx, pid):
    state = _load_state(ctx)
    return (state.get("profiles") or {}).get(pid), state


def _provider_for(ctx, profile):
    provider = _providers.build(profile["provider"])
    creds = _seal.open_map(ctx, profile.get("credentials") or {})
    return provider, creds


def _route_connection_test(ctx, payload):
    payload = dict(payload or {})
    caller = _pure.normalize_caller(payload)
    tpl = _msg(ctx)
    verdict = _pure.authorize(caller, "connection_test")
    if verdict["ok"] is False:
        return _denied(ctx, caller, "connection_test", verdict["reason"], tpl)
    profile, _ = _load_profile(ctx, str(payload.get("id") or ""))
    if not profile:
        return {**_err("not_found", 404, tpl.get("not_found") or ""),
                "effects": _audit(ctx, caller, "connection_test", "", "deny", "not_found")}
    try:
        provider, creds = _provider_for(ctx, profile)
        res = provider.test_connection(ctx, {**profile, "credentials": creds})
    except _seal.SealError as exc:
        return {**_err(exc.code, 500, tpl.get(exc.code) or exc.code),
                "effects": _audit(ctx, caller, "connection_test", profile["id"],
                                  "deny", exc.code)}
    except _providers.ProviderError as exc:
        return {**_err(exc.code, 500, tpl.get(exc.code) or exc.code),
                "effects": _audit(ctx, caller, "connection_test", profile["id"],
                                  "deny", exc.code)}
    ok = bool(res.get("ok"))
    effects = _audit(ctx, caller, "connection_test", profile["id"],
                     "allow" if ok else "deny", res.get("code") or "probe")
    return {"ok": ok, "result": res, "effects": effects}


def _route_probe_roundtrip(ctx, payload):
    payload = dict(payload or {})
    caller = _pure.normalize_caller(payload)
    tpl = _msg(ctx)
    verdict = _pure.authorize(caller, "probe_roundtrip")
    if verdict["ok"] is False:
        return _denied(ctx, caller, "probe_roundtrip", verdict["reason"], tpl)
    profile, _ = _load_profile(ctx, str(payload.get("id") or ""))
    if not profile:
        return {**_err("not_found", 404, tpl.get("not_found") or ""),
                "effects": _audit(ctx, caller, "probe_roundtrip", "", "deny", "not_found")}
    nonce = ctx.api.call("codec.nonce", {"length": 16}, caller=None).get("token") or "probe"
    probe_key = "cloud-probe/" + nonce
    try:
        provider, creds = _provider_for(ctx, profile)
        body = ("probe:" + nonce).encode("utf-8")
        put = provider.put(ctx, {**profile, "credentials": creds}, probe_key, body)
        if not put.get("ok"):
            effects = _audit(ctx, caller, "probe_roundtrip", profile["id"], "deny",
                             put.get("code") or "put_failed")
            return {"ok": False, "verified": False, "stage": "put", "result": put,
                    "effects": effects}
        got = provider.get(ctx, {**profile, "credentials": creds}, probe_key)
        provider.delete(ctx, {**profile, "credentials": creds}, probe_key)
        expected = ctx.api.call("codec.digest", {"text": body, "algorithm": "sha256"},
                                caller=None).get("hex")
        verified = bool(got.get("ok")) and got.get("digest") == expected
        effects = _audit(ctx, caller, "probe_roundtrip", profile["id"],
                         "allow" if verified else "deny",
                         "verified" if verified else "digest_mismatch")
        return {"ok": verified, "verified": verified, "probe_key": probe_key,
                "remote_digest": got.get("digest"), "expected_digest": expected,
                "effects": effects}
    except (_seal.SealError, _providers.ProviderError) as exc:
        effects = _audit(ctx, caller, "probe_roundtrip", profile["id"], "deny", exc.code)
        return {**_err(exc.code, 500, tpl.get(exc.code) or exc.code), "effects": effects}


# ---------------------------------------------------------------- 路由：增量同步

def _read_entry_bytes(ctx, entry):
    """按清单条目回读本地字节：原始件读模块路径；压缩件走 archive 只读接缝。"""
    if entry.get("archived"):
        row = ctx.api.call("archive.read_bytes",
                           {"module": entry.get("module"), "path": entry.get("source_path")},
                           caller=None)
        dec = ctx.api.call("codec.base64_decode_bytes", {"text": row.get("value") or ""},
                           caller=None)
        return dec.get("data") or b""
    row = ctx.api.call("store.read_bytes",
                       {"module": entry.get("module"), "path": entry.get("rel")},
                       caller=None)
    dec = ctx.api.call("codec.base64_decode_bytes", {"text": row.get("value") or ""},
                       caller=None)
    return dec.get("data") or b""


def _collect_entries(ctx, profile):
    """扫描策略类别内的本地文件，合并 archive 压缩索引，形成本地清单。"""
    archived = _archive.list_archived(ctx)
    archived_by_path = {}
    for row in archived["rows"]:
        archived_by_path[str(row.get("path") or "")] = row

    entries = []
    for cat in profile.get("categories") or []:
        src = _pure.CATEGORY_SOURCES.get(cat)
        if src is None:
            continue
        listed = ctx.api.call("store.glob", {"module": src["module"],
                                             "pattern": src["glob"]}, caller=None)
        for rel in listed.get("items") or []:
            raw = ctx.api.call("store.read_bytes", {"module": src["module"], "path": rel},
                               caller=None)
            dec = ctx.api.call("codec.base64_decode_bytes",
                               {"text": raw.get("value") or ""}, caller=None)
            data = dec.get("data") or b""
            digest = ctx.api.call("codec.digest", {"text": data, "algorithm": "sha256"},
                                  caller=None).get("hex")
            entry = {
                "rel": cat + "/" + rel,
                "category": cat,
                "module": src["module"],
                "source_path": rel,
                "size": raw.get("size") or len(data),
                "digest": digest,
                "archived": False,
                "algorithm": "",
                "checksum": "",
            }
            match = None
            for path, row in archived_by_path.items():
                if path.endswith(rel) or path.endswith(src["module"] + "/" + rel):
                    match = row
                    break
            if match and match.get("status") == "archived":
                entry.update({
                    "archived": True,
                    "size": match.get("size_comp") or entry["size"],
                    "digest": match.get("checksum") or digest,
                    "algorithm": match.get("algorithm") or "",
                    "checksum": match.get("checksum") or "",
                    "source_path": match.get("path") or rel,
                })
            entries.append(entry)
    return entries, archived["seam"]


def _remote_entries(ctx, profile, provider, creds):
    rows = provider.list_keys(ctx, {**profile, "credentials": creds}, "")
    out = {}
    for row in rows or []:
        out[row.get("key")] = {"digest": row.get("digest"), "size": row.get("size")}
    return out


def _route_sync_plan(ctx, payload):
    payload = dict(payload or {})
    state = _load_state(ctx)
    pid = str(payload.get("id") or state.get("active") or "")
    profiles = state.get("profiles") or {}
    profile = profiles.get(pid)
    if not profile and len(profiles) == 1:
        profile = next(iter(profiles.values()))
    if not profile:
        return _err("not_found", 404, _msg(ctx).get("not_found") or "")
    local, seam = _collect_entries(ctx, profile)
    state = _load_state(ctx)
    pushed = ((state.get("manifests") or {}).get(profile["id"]) or {}).get("entries") or []
    plan = _pure.diff_plan(local, pushed, {})
    plan["archive_seam"] = seam
    return {"profile": profile["id"], "plan": plan, "local_count": len(local)}


def _route_sync_run(ctx, payload):
    payload = dict(payload or {})
    caller = _pure.normalize_caller(payload)
    tpl = _msg(ctx)
    verdict = _pure.authorize(caller, "sync_run")
    if verdict["ok"] is False:
        return _denied(ctx, caller, "sync_run", verdict["reason"], tpl)

    state = _load_state(ctx)
    pid = str(payload.get("id") or state.get("active") or "")
    profiles = state.get("profiles") or {}
    profile = profiles.get(pid)
    # 未显式指定且未设生效 profile 时，兜底取唯一一套 profile；多套仍须先切换。
    if not profile and len(profiles) == 1:
        profile = next(iter(profiles.values()))
    if not profile:
        return {**_err("not_found", 404, tpl.get("not_found") or ""),
                "effects": _audit(ctx, caller, "sync_run", pid, "deny", "not_found")}

    local, seam = _collect_entries(ctx, profile)
    pushed = ((state.get("manifests") or {}).get(pid) or {}).get("entries") or []
    try:
        provider, creds = _provider_for(ctx, profile)
    except _seal.SealError as exc:
        effects = _audit(ctx, caller, "sync_run", pid, "deny", exc.code)
        return {**_err(exc.code, 500, tpl.get(exc.code) or exc.code), "effects": effects}
    remote = _remote_entries(ctx, profile, provider, creds)
    plan = _pure.diff_plan(local, pushed, remote)

    policy = profile.get("policy") or {}
    max_attempts = int(policy.get("max_attempts") or 3)
    base_s = int(policy.get("backoff_base_s") or 1)
    cap_s = int(policy.get("backoff_cap_s") or 30)

    new_entries = {e["rel"]: e for e in plan["unchanged"]}
    pushed_ok, failed = [], []
    for entry in plan["to_push"]:
        data = _read_entry_bytes(ctx, entry)
        attempts, last_err = 0, ""
        while attempts < max_attempts:
            res = provider.put(ctx, {**profile, "credentials": creds},
                              entry["rel"], data)
            if res.get("ok"):
                entry = {**entry, "pushed_at": ctx.api.call("clock.now", {},
                         caller=None).get("ts"), "upload_id": res.get("upload_id") or ""}
                new_entries[entry["rel"]] = entry
                pushed_ok.append(entry)
                break
            attempts += 1
            last_err = res.get("code") or "provider_error"
            if attempts < max_attempts:
                delay = _pure.backoff_delay(attempts, base_s, cap_s)
                if delay > 0:
                    ctx.api.call("clock.sleep", {"seconds": delay}, caller=None)
        else:
            failed.append({"rel": entry["rel"], "attempts": attempts, "reason": last_err})

    now = ctx.api.call("clock.now", {}, caller=None).get("ts")
    conflicts = plan["conflicts"]
    ledger = {
        "at": now,
        "ok": not failed and not conflicts,
        "pushed": len(pushed_ok),
        "unchanged": len(plan["unchanged"]),
        "conflicts": len(conflicts),
        "failures": len(failed),
        "archive_seam": seam,
        "reason": "" if not failed and not conflicts else
                  ("conflict" if conflicts else "retry_exhausted"),
        "failed": failed,
        "conflict_rows": conflicts,
    }
    state.setdefault("manifests", {})[pid] = {"entries": list(new_entries.values()),
                                              "updated": now}
    state.setdefault("ledger", {})[pid] = ledger

    effects = [_state_effect(state)]
    effects += _audit(ctx, caller, "sync_run", pid,
                      "allow" if ledger["ok"] else "partial", ledger["reason"] or "run")
    return {"ok": ledger["ok"], "ledger": ledger, "effects": effects}


# ---------------------------------------------------------------- 路由：只读视图

def _route_status(ctx, payload):
    return _pure.status_view(_load_state(ctx))


def _route_project_status(ctx, payload):
    payload = dict(payload or {})
    return _pure.project_sync_view(_load_state(ctx), str(payload.get("project") or ""))


def _route_audit_list(ctx, payload):
    payload = dict(payload or {})
    limit = int(payload.get("limit") or 50)
    row = ctx.api.call("store.read_text", {"module": _MODULE, "path": _AUDIT_PATH},
                       caller=None)
    rows = []
    for line in str(row.get("value") or "").splitlines():
        if not line.strip():
            continue
        dec = ctx.api.call("codec.json_decode", {"text": line}, caller=None)
        if dec.get("ok"):
            rows.append(dec["value"])
    return {"items": rows[-limit:]}


# ---------------------------------------------------------------- 工具接线

def _register_tools(ctx):
    tools = getattr(ctx, "tools", None)
    if tools is None:
        return
    tpl = _msg(ctx)
    specs = [
        ("cloud_profile_save", "cloud.profile_save", "tool_cloud_profile_save_desc", [
            {"name": "id", "type": "string", "required": True, "desc": "profile 标识"},
            {"name": "provider", "type": "string", "required": True,
             "desc": "s3 / webdav / http_dir / wiki / rsync"},
            {"name": "endpoint", "type": "string", "required": True, "desc": "服务端点"},
            {"name": "root_dir", "type": "string", "desc": "远端根目录/桶前缀"},
            {"name": "credentials", "type": "object", "desc": "凭证键值（密封落盘）"},
            {"name": "categories", "type": "list", "desc": "同步类别"},
        ]),
        ("cloud_profile_switch", "cloud.profile_switch", "tool_cloud_profile_switch_desc", [
            {"name": "id", "type": "string", "required": True, "desc": "profile 标识"}]),
        ("cloud_profile_delete", "cloud.profile_delete", "tool_cloud_profile_delete_desc", [
            {"name": "id", "type": "string", "required": True, "desc": "profile 标识"}]),
        ("cloud_connection_test", "cloud.connection_test", "tool_cloud_connection_test_desc", [
            {"name": "id", "type": "string", "required": True, "desc": "profile 标识"}]),
        ("cloud_probe_roundtrip", "cloud.probe_roundtrip", "tool_cloud_probe_roundtrip_desc", [
            {"name": "id", "type": "string", "required": True, "desc": "profile 标识"}]),
        ("cloud_sync_run", "cloud.sync_run", "tool_cloud_sync_run_desc", []),
        ("cloud_status", "cloud.status", "tool_cloud_status_desc", []),
    ]
    for name, route, desc_key, params in specs:
        if tools.has(name):
            continue
        tools.register(name, tpl.get(desc_key) or "", params, _tool_fn(route),
                       module="cloud", kinds=["role", "admin"], builtin=True)


def _tool_fn(route):
    def fn(ctx, args, session=None):
        caller = _session_caller(session)
        payload = dict(args or {})
        payload["caller"] = caller
        return ctx.api.call(route, payload, caller=None)
    return fn


def _session_caller(session):
    s = session or {}
    ticket = s.get("ticket") or ""
    scope = "ticket" if ticket else "project"
    return {"scope": scope, "project": s.get("project") or "", "ticket": ticket,
            "session": s.get("id") or "", "role": s.get("role") or "",
            "kind": s.get("kind") or ""}
