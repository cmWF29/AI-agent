"""云端资料库纯计算：profile 校验、权限判定、清单差分、退避、视图脱敏。

本层不读时钟、不碰盘、不联网；所有副作用由路由层产出 effect 交需求 runtime 落地。
无默认业务数据：空台账由 ``empty_state`` 给出，种子数据不在代码里写死。
"""
from __future__ import annotations

from . import _guard

# ---------------------------------------------------------------- 类别与提供方

# 同步类别 → 归属模块与扫描面。类别是同步策略单位，新增类别在此登记来源。
CATEGORY_SOURCES = {
    "session": {"module": "agent/sessions", "glob": "sessions/*.yaml"},
    "ticket": {"module": "agent/tickets", "glob": "projects/**/tickets/**/ticket.yaml"},
    "knowledge": {"module": "agent/knowledge", "glob": "**/*.md"},
    "artifact": {"module": "agent/artifacts", "glob": "**/*"},
    "log": {"module": "agent/logs", "glob": "**/*.txt"},
    "trace": {"module": "agent_common/trace", "glob": "trace/**/*.jsonl"},
}

PROVIDER_KINDS = ("s3", "webdav", "http_dir", "wiki", "rsync", "fake", "stub")

# 提供方落地状态：ready 表示适配层已按统一接口接通；pending 表示接缝在位、真实协议
# 未接线（签名/通道/命令包装见报告「真实落地差异」）；fake/stub 为内存测试接缝。
PROVIDER_META = {
    "s3": {"transport": "https-rest-s3v4", "status": "ready",
           "note": "sigv4_multipart_resume"},
    "webdav": {"transport": "http-webdav", "status": "ready",
               "note": "basic_digest_chunked"},
    "http_dir": {"transport": "http-dir", "status": "ready", "note": ""},
    "wiki": {"transport": "http-api", "status": "pending", "note": "wiki_api_adapter_pending"},
    "rsync": {"transport": "ssh-command", "status": "pending", "note": "exec_wrapper_pending"},
    "fake": {"transport": "in-memory", "status": "ready", "note": "test_seam"},
    "stub": {"transport": "in-memory", "status": "ready", "note": "test_seam"},
}

# 默认协议白名单仅 https；http 须由配置 cloud.schemes 显式放开。
SCHEME_WHITELIST = _guard.DEFAULT_SCHEMES

REDACTED = "<redacted>"

# 配置类动作：只有公共级（global）岗位/管理员可执行。
CONFIG_ACTIONS = frozenset({
    "profile_save", "profile_switch", "profile_delete",
    "connection_test", "probe_roundtrip", "sync_run",
})
# 只读动作：各作用域均可查看，但视图不带凭证。
READ_ACTIONS = frozenset({
    "providers", "profile_list", "profile_get", "status",
    "project_status", "audit_list", "sync_plan",
})


def empty_state():
    """空台账：profiles / active / manifests（上次推送清单）/ ledger / resume（断点续传）。"""
    return {"profiles": {}, "active": "", "manifests": {}, "ledger": {}, "resume": {}}


def build_entry(rel, category, module, source_path, size, digest, mtime,
                archived=False, algorithm="", checksum=""):
    """清单条目成形：sha256 + size + mtime 三件套齐备，供增量比对与断点续传。"""
    return {
        "rel": rel,
        "category": category,
        "module": module,
        "source_path": source_path,
        "size": int(size or 0),
        "digest": digest or "",
        "mtime": float(mtime or 0),
        "archived": bool(archived),
        "algorithm": algorithm or "",
        "checksum": checksum or "",
    }


# ---------------------------------------------------------------- 调用方与权限

def normalize_caller(payload):
    """会话/请求上下文 → 权限调用方；角色、项目、工单以传入上下文为准，模型参数不可改写。"""
    raw = payload.get("caller") or {}
    raw = raw if isinstance(raw, dict) else {}
    scope = raw.get("scope") or ("ticket" if raw.get("ticket") else "project")
    return {
        "scope": scope,
        "project": raw.get("project") or "",
        "ticket": raw.get("ticket") or "",
        "session": raw.get("session") or "",
        "role": raw.get("role") or "",
        "kind": raw.get("kind") or "",
    }


def authorize(caller, action):
    """权限判定：配置动作仅 global 作用域或管理员角色；只读动作放行。

    返回 ``{"ok": True}`` 或 ``{"ok": False, "code": ..., "reason": ...}``。
    """
    if action in READ_ACTIONS:
        return {"ok": True}
    if action not in CONFIG_ACTIONS:
        return {"ok": False, "code": "unknown_action", "reason": "action_not_recognized"}
    if caller.get("scope") == "global" or caller.get("role") == "admin":
        return {"ok": True}
    return {"ok": False, "code": "forbidden_scope",
            "reason": "project_or_ticket_scope_cannot_configure_provider"}


# ---------------------------------------------------------------- 端点与路径校验

def validate_profile(payload, cfg, require_credentials=True):
    """校验并规范化 profile。返回 ``{"ok", "errors", "profile"}``；errors 为代码列表。

    更新已存在 profile 时允许不带凭证：``require_credentials=False`` 跳过此项，
    由路由沿用旧密封凭证，避免“改端点必须重填密钥”。
    """
    errors = []
    provider = str(payload.get("provider") or "")
    if provider not in PROVIDER_KINDS:
        errors.append("bad_provider")

    company = str(payload.get("company") or "").strip()
    if not company:
        errors.append("bad_company")

    endpoint = str(payload.get("endpoint") or "")
    root_dir = str(payload.get("root_dir") or "").strip("/")
    guard = _guard.validate_endpoint(endpoint, cfg)
    errors.extend(guard["errors"])

    if root_dir:
        if sanitize_key(root_dir) is None:
            errors.append("bad_root_dir")
    else:
        root_dir = ""

    credentials = payload.get("credentials") or {}
    if require_credentials and (not isinstance(credentials, dict) or not credentials):
        errors.append("bad_credentials")

    categories = payload.get("categories") or []
    if not isinstance(categories, list) or not categories:
        errors.append("bad_categories")
    else:
        for cat in categories:
            if cat not in CATEGORY_SOURCES:
                errors.append("unknown_category")

    policy_in = payload.get("policy") or {}
    policy = {
        "interval_s": int(policy_in.get("interval_s") or 3600),
        "max_attempts": int(policy_in.get("max_attempts") or 3),
        "backoff_base_s": int(policy_in.get("backoff_base_s") or 1),
        "backoff_cap_s": int(policy_in.get("backoff_cap_s") or 30),
        "conflict_policy": str(policy_in.get("conflict_policy") or "record"),
        "max_body_bytes": int(policy_in.get("max_body_bytes") or 0),
    }
    if policy["conflict_policy"] not in ("record", "skip", "overwrite"):
        errors.append("bad_conflict_policy")

    profile_id = str(payload.get("id") or "")
    profile = {
        "id": profile_id,
        "company": company,
        "provider": provider,
        "endpoint": endpoint,
        "root_dir": root_dir,
        "credential_ref": str(payload.get("credential_ref") or ""),
        "credentials": credentials,
        "categories": categories if isinstance(categories, list) else [],
        "policy": policy,
        "exclude_projects": payload.get("exclude_projects") or [],
        # 状态目录：按 profile 隔离清单/台账/断点续传状态，不跨公司混用。
        "state_dir": "cloud/profiles/" + profile_id,
    }
    return {"ok": not errors, "errors": errors, "profile": profile}


def sanitize_key(key):
    """远端对象键校验：委托给 _guard；返回规范化 posix 键或 None。"""
    return _guard.sanitize_key(key)


# ---------------------------------------------------------------- 清单差分

def diff_plan(local_entries, pushed_entries, remote_entries):
    """本地清单 × 上次推送清单 × 远端现状 → 推送计划。

    - ``to_push``：本地新增，或本地内容相对上次推送发生变化；
    - ``unchanged``：摘要与上次推送一致；
    - ``conflicts``：远端自上次推送后被改动（远端摘要 ≠ 上次推送摘要），不静默覆盖；
    - ``missing_remote``：上次推送的对象远端已不存在。
    """
    local = {e["rel"]: e for e in local_entries}
    pushed = {e["rel"]: e for e in pushed_entries}
    remote = {k: v for k, v in (remote_entries or {}).items()}

    to_push, unchanged, conflicts, missing_remote, to_delete = [], [], [], [], []
    for rel, entry in local.items():
        last = pushed.get(rel)
        rem = remote.get(rel)
        if last is None:
            # 本地清单无记录：远端已存在相同内容则幂等跳过，不重复推送。
            if rem and rem.get("digest") == entry["digest"]:
                unchanged.append({**entry, "remote_identical": True})
            else:
                to_push.append(entry)
            continue
        # 远端自上次推送后被外部改动：无论本地是否变化都记冲突，不静默覆盖。
        if rem and rem.get("digest") != last.get("digest"):
            conflicts.append({**entry, "remote_digest": rem.get("digest"),
                              "kind": "remote_modified"})
            continue
        if entry["digest"] == last["digest"]:
            unchanged.append(entry)
            continue
        to_push.append(entry)
    for rel in pushed:
        if rel not in local:
            if rel in remote:
                # 本地已删除、远端仍存在：删除传播到远端（需显式 prune 开关执行）。
                to_delete.append({"rel": rel,
                                  "remote_digest": remote[rel].get("digest")})
            else:
                missing_remote.append({"rel": rel})
    return {"to_push": to_push, "unchanged": unchanged,
            "conflicts": conflicts, "missing_remote": missing_remote,
            "to_delete": to_delete}


def backoff_delay(attempt, base_s, cap_s):
    """指数退避：第 attempt 次失败后的等待秒数；attempt 从 0 起。"""
    base = max(0, float(base_s or 0))
    cap = max(base, float(cap_s or base))
    return min(cap, base * (2 ** max(0, attempt)))


def backoff_jittered(attempt, base_s, cap_s, ratio=0.0, fraction=0.0):
    """指数退避 + 抖动：在指数值上叠加 ``ratio`` 比例内抖动，封顶 cap_s。

    ``fraction`` ∈ [0,1] 由调用方经 codec 随机接缝取入；本层不自持随机数。
    """
    base = backoff_delay(attempt, base_s, cap_s)
    cap = max(base, float(cap_s or base))
    if base <= 0:
        return 0.0
    fraction = min(1.0, max(0.0, float(fraction or 0.0)))
    delay = base + base * max(0.0, float(ratio or 0.0)) * fraction
    return min(cap, delay)


# ---------------------------------------------------------------- 视图成形

def mask_profile(profile):
    """脱敏视图：凭证值一律替换，密封串与明文都不进前端/日志。"""
    view = {k: v for k, v in profile.items() if k != "credentials"}
    view["credentials"] = {k: REDACTED for k in (profile.get("credentials") or {})}
    return view


def status_view(state):
    """全局同步状态：当前 profile 脱敏视图 + 最近一次运行摘要 + 计数。"""
    active_id = state.get("active") or ""
    profile = (state.get("profiles") or {}).get(active_id)
    ledger = (state.get("ledger") or {}).get(active_id) or {}
    resume = (state.get("resume") or {}).get(active_id) or {}
    return {
        "active": active_id,
        "configured": bool(profile),
        "profile": mask_profile(profile) if profile else None,
        "last_run": ledger,
        "counts": {
            "profiles": len(state.get("profiles") or {}),
            "entries": len((state.get("manifests") or {}).get(active_id, {}).get("entries") or {}),
            "pending": len(resume.get("pending") or []),
        },
    }


def project_sync_view(state, project):
    """项目只读视图：是否已纳入全局同步；不返回端点与凭证。"""
    active_id = state.get("active") or ""
    profile = (state.get("profiles") or {}).get(active_id)
    if not profile:
        return {"project": project, "included": False, "reason": "no_active_profile"}
    excluded = set(profile.get("exclude_projects") or [])
    included = project not in excluded
    return {"project": project, "included": included,
            "reason": "" if included else "excluded_by_profile"}
