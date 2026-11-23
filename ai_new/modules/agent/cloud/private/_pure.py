"""云端资料库纯计算：profile 校验、权限判定、清单差分、退避、视图脱敏。

本层不读时钟、不碰盘、不联网；所有副作用由路由层产出 effect 交需求 runtime 落地。
无默认业务数据：空台账由 ``empty_state`` 给出，种子数据不在代码里写死。
"""
from __future__ import annotations

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

PROVIDER_KINDS = ("s3", "webdav", "http_dir", "wiki", "rsync")

# 提供方落地状态：ready 表示适配层已按统一接口接通；pending 表示接缝在位、真实协议
# 未接线（签名/通道/命令包装见报告「真实落地差异」）。
PROVIDER_META = {
    "s3": {"transport": "https-rest", "status": "pending", "note": "s3_v4_signing_pending"},
    "webdav": {"transport": "http-webdav", "status": "ready", "note": ""},
    "http_dir": {"transport": "http-dir", "status": "ready", "note": ""},
    "wiki": {"transport": "http-api", "status": "pending", "note": "wiki_api_adapter_pending"},
    "rsync": {"transport": "ssh-command", "status": "pending", "note": "exec_wrapper_pending"},
}

SCHEME_WHITELIST = ("http", "https")

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
    """空台账：profiles / active / manifests（上次推送清单）/ ledger（最近一次运行摘要）。"""
    return {"profiles": {}, "active": "", "manifests": {}, "ledger": {}}


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

def _host_is_blocked(host):
    """回环 / 私网 / 链路本地地址拦截（防 SSRF 内网回连）。"""
    h = (host or "").strip().lower()
    if h in ("localhost", "::1", "0.0.0.0"):
        return True
    if h.startswith("127.") or h.startswith("10.") or h.startswith("169.254."):
        return True
    if h.startswith("192.168."):
        return True
    if h.startswith("172."):
        tail = h.split(".")[1] if h.count(".") >= 1 else ""
        if tail.isdigit() and 16 <= int(tail) <= 31:
            return True
    return False


def validate_profile(payload, cfg):
    """校验并规范化 profile。返回 ``{"ok", "errors", "profile"}``；errors 为代码列表。"""
    errors = []
    provider = str(payload.get("provider") or "")
    if provider not in PROVIDER_KINDS:
        errors.append("bad_provider")

    endpoint = str(payload.get("endpoint") or "")
    root_dir = str(payload.get("root_dir") or "").strip("/")
    scheme, host = "", ""
    if "://" in endpoint:
        scheme, rest = endpoint.split("://", 1)
        host = rest.split("/", 1)[0]
    else:
        errors.append("bad_endpoint")
    if scheme and scheme not in SCHEME_WHITELIST:
        errors.append("bad_scheme")
    if host and _host_is_blocked(host):
        errors.append("blocked_host")
    allowed_hosts = ((cfg or {}).get("allowed_hosts") or [])
    if allowed_hosts and host and host not in allowed_hosts:
        errors.append("host_not_whitelisted")

    if root_dir:
        parts = root_dir.split("/")
        if any(p in ("", "..") for p in parts) or root_dir.startswith("/"):
            errors.append("bad_root_dir")
    else:
        root_dir = ""

    credentials = payload.get("credentials") or {}
    if not isinstance(credentials, dict) or not credentials:
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
    }
    if policy["conflict_policy"] not in ("record", "skip", "overwrite"):
        errors.append("bad_conflict_policy")

    profile = {
        "id": str(payload.get("id") or ""),
        "provider": provider,
        "endpoint": endpoint,
        "root_dir": root_dir,
        "credentials": credentials,
        "categories": categories if isinstance(categories, list) else [],
        "policy": policy,
        "exclude_projects": payload.get("exclude_projects") or [],
    }
    return {"ok": not errors, "errors": errors, "profile": profile}


def sanitize_key(key):
    """远端对象键校验：拒绝绝对路径、``..`` 穿越与编码穿越；返回规范化 posix 键。"""
    rel = str(key or "").replace("\\", "/").lstrip("/")
    lowered = rel.lower()
    if "%2e" in lowered or "%2f" in lowered:
        return None
    parts = [p for p in rel.split("/") if p not in ("", ".")]
    if any(p == ".." for p in parts):
        return None
    return "/".join(parts)


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

    to_push, unchanged, conflicts, missing_remote = [], [], [], []
    for rel, entry in local.items():
        last = pushed.get(rel)
        if last is None:
            to_push.append(entry)
            continue
        if entry["digest"] == last["digest"]:
            unchanged.append(entry)
            continue
        rem = remote.get(rel)
        if rem and rem.get("digest") != last["digest"]:
            conflicts.append({**entry, "remote_digest": rem.get("digest"),
                              "kind": "remote_modified"})
        else:
            to_push.append(entry)
    for rel in pushed:
        if rel not in local and rel not in remote:
            missing_remote.append({"rel": rel})
    return {"to_push": to_push, "unchanged": unchanged,
            "conflicts": conflicts, "missing_remote": missing_remote}


def backoff_delay(attempt, base_s, cap_s):
    """指数退避：第 attempt 次失败后的等待秒数；attempt 从 0 起。"""
    base = max(0, float(base_s or 0))
    cap = max(base, float(cap_s or base))
    return min(cap, base * (2 ** max(0, attempt)))


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
    return {
        "active": active_id,
        "configured": bool(profile),
        "profile": mask_profile(profile) if profile else None,
        "last_run": ledger,
        "counts": {
            "profiles": len(state.get("profiles") or {}),
            "entries": len((state.get("manifests") or {}).get(active_id, {}).get("entries") or {}),
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
