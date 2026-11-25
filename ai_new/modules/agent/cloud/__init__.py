"""全局云端资料库：通用存储适配层 + 增量同步 + 公共级配置岗位。

职责边界：
- 适配层：统一连接/上传/下载/列目录/删除/校验接口，多公司多套 profile 切换；
- 增量同步：清单（sha256+size+mtime）+ 摘要幂等比对；失败指数退避+抖动封顶；
  断点续传状态原子落盘，进程重启后从待传清单继续；结果给新增/跳过/失败计数；
- 权限：配置动作仅公共级/管理员；项目角色只看只读状态；
- 凭证：AES-256-GCM 信封密封，AAD 绑定 profile+provider；视图/日志/审计一律脱敏。

落盘：台账变更经 effect 交需求 runtime.apply；断点续传检查点经 store 原子写持久化。
出站只经平台能力（store/clock/codec/host/archive/net）；不 import 其他业务模块。
"""
from __future__ import annotations

import os

from .private import _pure, _providers, _seal, _archive, _guard

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
        "cloud.profile_switch": "切换当前生效 profile（设为默认）",
        "cloud.profile_delete": "删除 profile 及其清单、台账与断点状态",
        "cloud.connection_test": "连通性测试：按 profile 探活",
        "cloud.probe_roundtrip": "往返验证：上传探针→下载→摘要校验→清理",
        "cloud.sync_plan": "增量计划：本地清单 × 上次推送 × 远端现状差分",
        "cloud.sync_run": "执行增量推送：重试退避、断点续传、清单与摘要落盘",
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
            if key in value:
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


# ---------------------------------------------------------------- 断点续传检查点

def _resume_path(pid):
    return "resume/" + str(pid) + ".yaml"


def _load_resume(ctx, pid):
    row = ctx.api.call("store.read", {"module": _MODULE, "path": _resume_path(pid)},
                       caller=None)
    value = row.get("value") if isinstance(row, dict) else None
    if isinstance(value, dict) and value.get("pending") is not None:
        return value
    return {"pending": [], "done": [], "entries": {}, "updated": 0}


def _resume_write_effect(pid, resume):
    # 检查点经 effect 交 runtime 落盘；store 层负责临时文件 + 原子改名。
    return {"kind": "write", "module": _MODULE,
            "path": _resume_path(pid), "value": resume}


def _resume_remove_effect(pid):
    return {"kind": "remove", "module": _MODULE, "path": _resume_path(pid)}


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
    state = _load_state(ctx)
    existing = (state.get("profiles") or {}).get(str(payload.get("id") or ""))
    validated = _pure.validate_profile(payload, cfg, require_credentials=not existing)
    if validated["ok"] is False:
        effects = _audit(ctx, caller, "profile_save", payload.get("id"), "deny",
                         ",".join(validated["errors"]))
        first = validated["errors"][0]
        return {**_err(first, 400, tpl.get(first) or first), "effects": effects}

    profile = validated["profile"]
    # 凭证：入参明文密封落盘；未传凭证则沿用已密封的旧凭证（跨 profile 不可互换）。
    if payload.get("credentials"):
        # 扁平表单会带空字段；空值没有语义，密封层不接受空串，先在这里剔掉。
        creds = {k: v for k, v in payload["credentials"].items()
                 if v is not None and str(v).strip() != ""}
        if not creds:
            effects = _audit(ctx, caller, "profile_save", profile["id"], "deny",
                             "bad_credentials")
            return {**_err("bad_credentials", 400, tpl.get("bad_credentials") or ""),
                    "effects": effects}
        profile["credentials"] = _seal.seal_map(
            ctx, creds, profile["id"], profile["provider"])
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
    # 首套 profile 自动成为默认生效；已有默认则不被新保存顶替。
    if not state.get("active"):
        state["active"] = profile["id"]

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
    state.get("resume", {}).pop(pid, None)
    if state.get("active") == pid:
        state["active"] = ""
    effects = [_resume_remove_effect(pid), _state_effect(state)]
    effects += _audit(ctx, caller, "profile_delete", pid, "allow", "deleted")
    return {"ok": True, "id": pid, "effects": effects}


# ---------------------------------------------------------------- 路由：连通与往返

def _load_profile(ctx, pid):
    state = _load_state(ctx)
    return (state.get("profiles") or {}).get(pid), state


def _provider_for(ctx, profile):
    provider = _providers.build(profile["provider"])
    creds = _seal.open_map(ctx, profile.get("credentials") or {},
                           profile["id"], profile["provider"])
    return provider, creds


def _revalidate_endpoint(ctx, profile):
    """运行时复检端点：保存后配置/白名单可能变化；非法交回校验错误码。"""
    cfg = _cfg(ctx)
    guard = _guard.validate_endpoint(profile.get("endpoint") or "", cfg)
    return guard["errors"]


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
    bad = _revalidate_endpoint(ctx, profile)
    if bad:
        effects = _audit(ctx, caller, "connection_test", profile["id"], "deny", bad[0])
        return {**_err(bad[0], 400, tpl.get(bad[0]) or bad[0]), "effects": effects}
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
    bad = _revalidate_endpoint(ctx, profile)
    if bad:
        effects = _audit(ctx, caller, "probe_roundtrip", profile["id"], "deny", bad[0])
        return {**_err(bad[0], 400, tpl.get(bad[0]) or bad[0]), "effects": effects}
    nonce = ctx.api.call("codec.nonce", {"length": 16}, caller=None).get("token") or "probe"
    probe_key = "cloud-probe/" + nonce
    try:
        provider, creds = _provider_for(ctx, profile)
        body = ("probe:" + nonce).encode("utf-8")
        _guard.check_body_size(body, (profile.get("policy") or {}).get("max_body_bytes") or 0)
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
    except (_seal.SealError, _providers.ProviderError, _guard.GuardError) as exc:
        effects = _audit(ctx, caller, "probe_roundtrip", profile["id"], "deny",
                         getattr(exc, "code", "provider_error"))
        return {**_err(getattr(exc, "code", "provider_error"), 500,
                       tpl.get(getattr(exc, "code", "")) or str(exc)), "effects": effects}


# ---------------------------------------------------------------- 路由：增量同步

def _jitter_fraction(ctx):
    """[0,1) 抖动系数：随机令牌经摘要映射；随机数能力归 codec，本层不自持 RNG。"""
    tok = ctx.api.call("codec.nonce", {"length": 8}, caller=None).get("token") or ""
    dig = ctx.api.call("codec.digest", {"text": "jitter:" + tok},
                       caller=None).get("hex") or "0"
    try:
        return int(dig[:8], 16) / float(0xFFFFFFFF)
    except ValueError:
        return 0.0


def _mtime(ctx, module, rel):
    """best-effort 取本地文件 mtime（epoch 秒）；解析/stat 失败记 0。"""
    try:
        row = ctx.api.call("store.resolve_doc", {"module": module, "path": rel},
                           caller=None)
        if row.get("ok"):
            return float(os.stat(row["real"]).st_mtime)
    except (OSError, ValueError, TypeError):
        pass
    return 0.0


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
                       {"module": entry.get("module"), "path": entry.get("source_path")},
                       caller=None)
    dec = ctx.api.call("codec.base64_decode_bytes", {"text": row.get("value") or ""},
                       caller=None)
    return dec.get("data") or b""


def _collect_entries(ctx, profile):
    """扫描策略类别内的本地文件，合并 archive 压缩索引，形成本地清单（含 mtime）。"""
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
            entry = _pure.build_entry(
                rel=cat + "/" + rel, category=cat, module=src["module"], source_path=rel,
                size=raw.get("size") or len(data), digest=digest,
                mtime=_mtime(ctx, src["module"], rel))
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


_MANIFEST_KEY = "_hive/manifest.json"
_MANIFEST_VERSION = 1


def _manifest_doc(profile, local_entries, now):
    """远端权威清单：对象键 → 摘要/大小/类别/修改时间；只含本地受管对象。"""
    entries = {}
    for e in local_entries:
        entries[e["rel"]] = {
            "digest": e.get("digest") or "",
            "size": int(e.get("size") or 0),
            "category": e.get("category") or "",
            "mtime": float(e.get("mtime") or 0),
        }
    return {"version": _MANIFEST_VERSION, "profile": profile.get("id") or "",
            "updated": now, "entries": entries}


def _remote_manifest(ctx, profile, provider, creds):
    """读远端权威清单；缺失/损坏/不可达都显式返回，调用方回退本地缓存并标注来源。"""
    try:
        got = provider.get(ctx, {**profile, "credentials": creds}, _MANIFEST_KEY)
    except _providers.ProviderError as exc:
        return {"ok": False, "code": exc.code, "entries": {}}
    if not got.get("ok"):
        return {"ok": False, "code": got.get("code") or "not_found", "entries": {}}
    data = got.get("data") or b""
    dec = ctx.api.call("codec.json_decode", {"text": data.decode("utf-8", "replace")},
                       caller=None)
    if not dec.get("ok") or not isinstance(dec.get("value"), dict):
        return {"ok": False, "code": "manifest_corrupt", "entries": {}}
    doc = dec["value"]
    if int(doc.get("version") or 0) != _MANIFEST_VERSION:
        return {"ok": False, "code": "manifest_version", "entries": {}}
    raw = doc.get("entries")
    if not isinstance(raw, dict):
        return {"ok": False, "code": "manifest_corrupt", "entries": {}}
    entries = {}
    for rel, row in raw.items():
        if not isinstance(row, dict) or not _pure.sanitize_key(rel):
            continue
        entries[rel] = {"digest": row.get("digest") or "",
                        "size": int(row.get("size") or 0)}
    return {"ok": True, "entries": entries, "digest": got.get("digest") or "",
            "doc": doc}


def _remote_entries(ctx, profile, provider, creds):
    rows = provider.list_keys(ctx, {**profile, "credentials": creds}, "")
    out = {}
    for row in rows or []:
        key = row.get("key")
        if key == _MANIFEST_KEY or str(key or "").startswith("_hive/"):
            continue
        out[key] = {"digest": row.get("digest"), "size": row.get("size")}
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
    # 只读计划也要先看远端权威清单：否则第二台机器/第二次进程看到的仍是本机缓存，
    # 远端被别人改过也发现不了，和业界对象存储的远端 manifest 口径不一致。
    manifest_source, remote_error, baseline = "local", "", pushed
    try:
        provider, creds = _provider_for(ctx, profile)
        remote = _remote_entries(ctx, profile, provider, creds)
        mf = _remote_manifest(ctx, profile, provider, creds)
        if mf.get("ok"):
            baseline = [{"rel": k, **v} for k, v in mf["entries"].items()]
            manifest_source = "remote"
        elif mf.get("code") not in ("not_found", None):
            remote_error = mf.get("code") or "manifest_error"
    except (_seal.SealError, _providers.ProviderError) as exc:
        remote = {}
        remote_error = getattr(exc, "code", "provider_error")
    plan = _pure.diff_plan(local, baseline, remote)
    plan["archive_seam"] = seam
    plan["manifest_source"] = manifest_source
    plan["prune_required"] = bool(plan["to_delete"])
    if remote_error:
        plan["remote_error"] = remote_error
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
    pid = profile["id"]

    bad = _revalidate_endpoint(ctx, profile)
    if bad:
        effects = _audit(ctx, caller, "sync_run", pid, "deny", bad[0])
        return {**_err(bad[0], 400, tpl.get(bad[0]) or bad[0]), "effects": effects}

    local, seam = _collect_entries(ctx, profile)
    pushed = ((state.get("manifests") or {}).get(pid) or {}).get("entries") or []
    try:
        provider, creds = _provider_for(ctx, profile)
    except _seal.SealError as exc:
        effects = _audit(ctx, caller, "sync_run", pid, "deny", exc.code)
        return {**_err(exc.code, 500, tpl.get(exc.code) or exc.code), "effects": effects}
    remote = _remote_entries(ctx, profile, provider, creds)
    manifest_meta = _remote_manifest(ctx, profile, provider, creds)
    manifest_source = "remote" if manifest_meta.get("ok") else "local"
    baseline = ([{"rel": k, **v} for k, v in manifest_meta["entries"].items()]
                if manifest_meta.get("ok") else pushed)
    plan = _pure.diff_plan(local, baseline, remote)

    # 断点续传：恢复上次未完成的待传清单；已传条目不重传。
    resume = _load_resume(ctx, pid)
    prior_pending = set(resume.get("pending") or [])
    prior_done = set(resume.get("done") or [])
    if prior_pending:
        snap = resume.get("entries") or {}
        recovered = [snap[rel] for rel in resume.get("pending") or [] if rel in snap]
        planned = {e["rel"]: e for e in plan["to_push"]}
        for entry in recovered:
            planned.setdefault(entry["rel"], entry)
        plan["to_push"] = list(planned.values())

    policy = profile.get("policy") or {}
    max_attempts = int(policy.get("max_attempts") or 3)
    base_s = int(policy.get("backoff_base_s") or 1)
    cap_s = int(policy.get("backoff_cap_s") or 30)
    max_body = int(policy.get("max_body_bytes") or 0)

    new_entries = {e["rel"]: e for e in plan["unchanged"]}
    resume["entries"] = {e["rel"]: e for e in plan["to_push"]}
    resume["done"] = [rel for rel in prior_done if rel not in prior_pending]
    resume["pending"] = [e["rel"] for e in plan["to_push"]]
    added, skipped, failed = [], list(plan["unchanged"]), []
    effects = []

    for entry in plan["to_push"]:
        rel = entry["rel"]
        data = _read_entry_bytes(ctx, entry)
        attempts, last_err = 0, ""
        done = False
        while attempts < max_attempts:
            try:
                _guard.check_body_size(data, max_body)
                res = provider.put(ctx, {**profile, "credentials": creds}, rel, data)
            except _guard.GuardError as exc:
                res = {"ok": False, "code": exc.code}
            if res.get("ok"):
                entry = {**entry, "pushed_at": ctx.api.call("clock.now", {},
                         caller=None).get("ts"), "upload_id": res.get("upload_id") or ""}
                new_entries[rel] = entry
                added.append(entry)
                resume["done"].append(rel)
                resume["pending"].remove(rel)
                resume["entries"][rel] = entry
                effects.append(_resume_write_effect(pid, resume))
                done = True
                break
            attempts += 1
            last_err = res.get("code") or "provider_error"
            if attempts < max_attempts:
                delay = _pure.backoff_jittered(
                    attempts - 1, base_s, cap_s, ratio=0.25,
                    fraction=_jitter_fraction(ctx))
                if delay > 0:
                    ctx.api.call("clock.sleep", {"seconds": delay}, caller=None)
        if not done:
            failed.append({"rel": rel, "attempts": attempts, "reason": last_err})

    # 删除传播：本地删掉、远端仍存在的对象，只在本轮显式开启 prune 时删除；
    # 默认不删远端共享对象，计划里先暴露 to_delete，避免误删别处数据。
    prune = bool(payload.get("prune") or (policy or {}).get("prune"))
    deleted, delete_failed, deletions = [], [], []
    if prune:
        for entry in plan.get("to_delete") or []:
            rel = entry["rel"]
            attempts, last_err = 0, ""
            ok_delete = False
            while attempts < max_attempts:
                try:
                    res = provider.delete(ctx, {**profile, "credentials": creds}, rel)
                except _providers.ProviderError as exc:
                    res = {"ok": False, "code": exc.code}
                if res.get("ok"):
                    deleted.append({"rel": rel})
                    deletions.append({"rel": rel, "remote_digest": entry.get("remote_digest")})
                    ok_delete = True
                    break
                attempts += 1
                last_err = res.get("code") or "delete_failed"
                if attempts < max_attempts:
                    delay = _pure.backoff_jittered(
                        attempts - 1, base_s, cap_s, ratio=0.25,
                        fraction=_jitter_fraction(ctx))
                    if delay > 0:
                        ctx.api.call("clock.sleep", {"seconds": delay}, caller=None)
            if not ok_delete:
                delete_failed.append({"rel": rel, "attempts": attempts,
                                      "reason": last_err})
                failed.append({"rel": rel, "attempts": attempts,
                               "reason": "delete:" + last_err})

    now = ctx.api.call("clock.now", {}, caller=None).get("ts")
    conflicts = plan["conflicts"]
    prune_blocked = bool(plan.get("to_delete")) and not prune
    manifest_updated, manifest_error = False, ""
    if not failed and not conflicts and not prune_blocked:
        # 远端权威清单是同步提交点：对象都成功后再写 manifest；写失败不更新本机缓存，
        # 下一轮会重试 manifest，而不会把未提交的清单当成已同步。
        doc = _manifest_doc(profile, list(new_entries.values()), now)
        enc = ctx.api.call("codec.json_encode", {"value": doc}, caller=None)
        body = (enc.get("text") or "").encode("utf-8")
        try:
            mf_put = provider.put(ctx, {**profile, "credentials": creds}, _MANIFEST_KEY, body)
        except _guard.GuardError as exc:
            mf_put = {"ok": False, "code": exc.code}
        except _providers.ProviderError as exc:
            mf_put = {"ok": False, "code": exc.code}
        manifest_updated = bool(mf_put.get("ok"))
        if not manifest_updated:
            manifest_error = mf_put.get("code") or "manifest_put_failed"
    ok_run = (not failed and not conflicts and not prune_blocked
              and not manifest_error)
    if ok_run:
        effects.append(_resume_remove_effect(pid))
        resume_out = {"pending": [], "done": [], "entries": {}, "updated": 0}
    else:
        resume_out = resume
        effects.append(_resume_write_effect(pid, resume_out))
    ledger = {
        "at": now,
        "ok": ok_run,
        "added": len(added),
        "skipped": len(skipped),
        "failed_count": len(failed),
        "conflicts": len(conflicts),
        # 兼容旧字段名：pushed=added，unchanged=skipped，failures=failed。
        "pushed": len(added),
        "unchanged": len(skipped),
        "failures": len(failed),
        "archive_seam": seam,
        "manifest_source": manifest_source,
        "manifest_updated": manifest_updated,
        "manifest_error": manifest_error,
        "reason": ("" if ok_run else
                   ("manifest_failed" if manifest_error else
                    ("prune_required" if prune_blocked else
                     ("conflict" if conflicts else "retry_exhausted")))),        "failed": failed,
        "conflict_rows": conflicts,
        "deleted": len(deleted),
        "deleted_rows": deletions,
        "delete_failed": delete_failed,
        "prune": prune,
        "prune_required": bool(plan.get("to_delete")),
        "prune_blocked": prune_blocked,
    }
    if manifest_updated:
        state.setdefault("manifests", {})[pid] = {
            "entries": list(new_entries.values()), "updated": now}
    else:
        state.setdefault("manifests", {})[pid] = {
            "entries": list(new_entries.values()), "updated": now,
            "pending_manifest": True}
    state.setdefault("ledger", {})[pid] = ledger
    state["resume"][pid] = resume_out

    effects.append(_state_effect(state))
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
            {"name": "company", "type": "string", "required": True, "desc": "公司标识"},
            {"name": "provider", "type": "string", "required": True,
             "desc": "s3 / webdav / http_dir / wiki / rsync"},
            {"name": "endpoint", "type": "string", "required": True, "desc": "服务端点"},
            {"name": "root_dir", "type": "string", "desc": "远端根目录/桶前缀"},
            {"name": "credentials", "type": "object",
             "desc": "凭证键值（密封落盘）；s3：access_key/secret_key/region/bucket；"
             "webdav：username/password/ca_bundle"},
            {"name": "categories", "type": "list", "desc": "同步类别"},
            {"name": "policy", "type": "object",
             "desc": "重试/体积/分片策略；s3：multipart_threshold/multipart_min_size/"
             "part_max_bytes/concurrency/rate_per_s；webdav：auth/upload_chunk_size/ca_bundle"},
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
    # 系统配置岗位在工单里工作，但配置动作按公共级口径执行；只认这两个内置岗位，
    # 普通项目/工单角色即使伪造同名参数也拿不到全局权限。
    scope = "global" if s.get("role") in ("cloud-configurer", "node-configurer") else (
        "ticket" if ticket else "project")
    return {"scope": scope, "project": s.get("project") or "", "ticket": ticket,
            "session": s.get("id") or "", "role": s.get("role") or "",
            "kind": s.get("kind") or ""}
