"""鉴权模块：凭据比对、会话形状，以及给 HTTP 闸用的系统校验路由。

纯计算在 private/_pure；`verify` 是装配期收 ctx 的系统路由（caller=None 放行），
读自己 data 下的会话记录，判定交纯函数。模块不自己做登录页、不发通知。
"""
from __future__ import annotations

import hmac
import sys

from .private import _pure


def _auth_cfg(ctx):
    row = ctx.api.call("config.get", {"key": "server.auth"}, caller=None)
    return row.get("value") or {}


def _weak_digest(ctx, auth):
    """默认口令 ``salt:123456`` 的摘要；算不出返回空串，纯判定侧按非默认处理。"""
    salt = str(auth.get("salt") or "")
    row = ctx.api.call("codec.digest", {
        "text": salt + ":" + _pure.DEFAULT_PASSWORD, "algorithm": "sha256"}, caller=None)
    return row.get("hex") or ""


def _default_warning(ctx):
    """默认/空口令判定：读配置 → 算默认口令摘要 → 交纯函数判定。"""
    auth = _auth_cfg(ctx)
    return _pure.default_password_state({"auth": auth, "weak_digest": _weak_digest(ctx, auth)})


def _msg_tpl(ctx):
    """消息模板表：auth 模块自己的 data，读不到就退化成空。"""
    row = ctx.api.call("store.read", {
        "module": "agent/auth", "path": "messages.yaml"}, caller=None)
    return row.get("value") or {}


def _cfg_paths(ctx):
    row = ctx.api.call("config.get", {"key": "auth.paths"}, caller=None)
    return row.get("value") or {}


_THROTTLE_PATH = "login-throttle.json"
_GUARD_DEFAULT = {"enabled": True, "max_failures": 5, "window_seconds": 600,
                  "lock_seconds": 900, "max_entries": 2000}


def _guard_cfg(ctx):
    """登录节流配置：缺失走安全默认；非法数字回默认，不让坏配置把登录打 500。"""
    raw = (ctx.cfg.get("server") or {}).get("auth") or {}
    guard = raw.get("login_guard") if isinstance(raw, dict) else None
    guard = guard if isinstance(guard, dict) else {}
    out = dict(_GUARD_DEFAULT)
    out["enabled"] = guard.get("enabled") is not False
    for key in ("max_failures", "window_seconds", "lock_seconds", "max_entries"):
        try:
            value = int(guard.get(key, out[key]))
        except (TypeError, ValueError):
            value = out[key]
        out[key] = max(1, min(value, 86400 if key != "max_entries" else 10000))
    return out


def _throttle_read(ctx):
    row = ctx.api.call("store.read", {
        "module": "agent/auth", "path": _THROTTLE_PATH}, caller=None)
    rec = row.get("value")
    return rec if isinstance(rec, dict) else {}


def _throttle_mutate(ctx, keys, success):
    """CAS 更新节流台账：并发失败重读重算；台账写不进去按 fail-closed 返回错误。"""
    cfg = _guard_cfg(ctx)
    now = float(ctx.api.call("clock.now", {}, caller=None).get("ts") or 0)
    for _attempt in range(8):
        before = _throttle_read(ctx)
        out = _pure.throttle_update({
            "entries": before, "keys": keys, "now": now, "cfg": cfg,
            "success": bool(success)})
        after = out.get("entries") or {}
        if after == before:
            return out
        cas = ctx.api.call("store.cas", {
            "module": "agent/auth", "path": _THROTTLE_PATH,
            "expected": before, "create": True, "value": after}, caller=None)
        if cas.get("ok"):
            return out
        if not cas.get("conflict"):
            return {"error": cas.get("code") or "guard_store_error"}
    return {"error": "guard_conflict_exhausted"}


def _guard_check(ctx, payload):
    """登录前只读检查；配置关闭时直接放行，连台账都不读。"""
    cfg = _guard_cfg(ctx)
    keys = _pure.throttle_keys(payload).get("keys") or []
    if not cfg.get("enabled"):
        return {"blocked": False, "retry_after": 0, "cfg": cfg, "keys": keys}
    now = float(ctx.api.call("clock.now", {}, caller=None).get("ts") or 0)
    out = _pure.throttle_check({"entries": _throttle_read(ctx), "keys": keys, "now": now})
    out["cfg"] = cfg
    out["keys"] = keys
    return out


def _as_handler(fn):
    def handler(ctx, payload):
        payload = dict(payload or {})
        if "paths" not in payload:
            payload["paths"] = _cfg_paths(ctx)
        return fn(payload)
    return handler


def setup(ctx):
    def _verify(payload):
        cfg = ctx.cfg.get("server") or {}
        auth = cfg.get("auth") or {}
        legacy = cfg.get("token") or ""
        token = str((payload or {}).get("token") or "")
        enabled = bool(auth.get("enabled"))

        # 开放态：既没开登录、也没配旧令牌（本机开发）
        if not enabled and not legacy:
            return {"allow": True, "mode": "open"}
        # 旧令牌兼容：过渡期不断既有入口；比较仍走常量时间，不泄露前缀长度。
        if legacy and hmac.compare_digest(token.encode("utf-8"),
                                          str(legacy).encode("utf-8")):
            return {"allow": True, "mode": "legacy"}
        if not enabled:
            return {"allow": False, "mode": "legacy", "reason": "unauthorized"}
        # 会话令牌先过字符集：令牌会拼进 sessions/{token}.yaml，不能把 .. 或 /
        # 交给存储层；这里失败即拒绝，不把路径注入留到下一层兜底。
        if not _pure.valid_token({"token": token}).get("ok"):
            return {"allow": False, "mode": "session", "reason": "unauthorized"}

        sess = _pure.session_path({"paths": _cfg_paths(ctx), "token": token})
        path = sess.get("path") or ""
        if not path:
            return {"allow": False, "mode": "session", "reason": "unauthorized"}
        try:
            row = ctx.api.call("store.read", {
                "module": "agent/auth", "path": path}, caller=None)
        except Exception:  # noqa: BLE001 — 越界/坏记录统一按未登录，不把异常抛到 HTTP 闸
            return {"allow": False, "mode": "session", "reason": "unauthorized"}
        record = row.get("value") if row.get("exists") else None
        if not record or not record.get("token"):
            return {"allow": False, "mode": "session", "reason": "unauthorized"}
        now = ctx.clock.now()["ts"]
        check = _pure.session_valid({"record": record, "now": now})
        if check.get("valid"):
            return {"allow": True, "mode": "session", "username": check.get("username")}
        return {"allow": False, "mode": "session", "reason": "unauthorized"}

    def _status(payload):
        server = ctx.cfg.get("server") or {}
        auth = server.get("auth") or {}
        try:
            warn = _default_warning(ctx)
        except Exception:
            warn = {"default": False, "reason": ""}
        return {"enabled": bool(auth.get("enabled")),
                "legacy": bool(server.get("token")),
                "username": auth.get("username") or "",
                "default_password": bool(warn.get("default")),
                "warning": "默认口令，必须改密后才能对外" if warn.get("default") else ""}

    pairs = [
        ("auth.credentials_ok", _pure.credentials_ok),
        ("auth.password_check", _pure.change_password),
        ("auth.build_session", _pure.build_session),
        ("auth.session_view", _pure.session_view),
        ("auth.session_path", _pure.session_path),
    ]
    for name, fn in pairs:
        ctx.api.register(name, _as_handler(fn), module="auth")
    ctx.api.register("auth.login", _route_login, "登录闭环：配置→摘要比对→发会话→落盘→会话视图",
                     module="auth")
    ctx.api.register("auth.change_password", _route_change_password,
                     "修改密码：验旧密码→摘要校验→写配置新摘要", module="auth")
    ctx.api.register("auth.verify", lambda c, p: _verify(p), module="auth")
    ctx.api.register("auth.status", lambda c, p: _status(p), module="auth")

    # 启动即查默认/空口令：命中就打显著告警，不静默放过；前端横幅由 auth.status 下发。
    try:
        warn = _default_warning(ctx)
    except Exception:
        warn = {"default": False, "reason": ""}
    if warn.get("default"):
        line = "【安全告警】默认/空口令未改（%s）：必须改密后才能对外提供服务。" % warn.get("reason")
        print("=" * 64, file=sys.stderr)
        print(line, file=sys.stderr)
        print("=" * 64, file=sys.stderr)
    return True


def _too_many(retry_after):
    minutes = max(1, int((retry_after + 59) // 60))
    return {"ok": False, "code": "too_many_attempts", "status": 429,
            "retry_after": retry_after,
            "message": "登录失败次数过多，请 %d 分钟后再试" % minutes}


def _route_login(ctx, payload):
    # 先看节流台账：锁定期内连正确口令也不再做摘要比对，避免把 CPU 和
    # 账号信息当侧信道反复探测。台账写失败按 fail-closed 处理，不静默放行。
    guard = _guard_check(ctx, payload)
    if guard.get("blocked"):
        return _too_many(guard.get("retry_after") or 1)
    guard_on = bool((guard.get("cfg") or {}).get("enabled"))
    cfg = ctx.api.call("config.get", {"key": "server.auth"}, caller=None) or {}
    cfgv = cfg.get("value") or {}
    dg = ctx.api.call("codec.digest", {
        "text": str(cfgv.get("salt") or "") + ":" + str(payload.get("password") or ""),
        "algorithm": "sha256"}, caller=None)
    ok = ctx.api.call("auth.credentials_ok", {
        "username": payload.get("username"),
        "expect_username": cfgv.get("username"),
        "digest": dg.get("hex"),
        "expect_hash": cfgv.get("password_hash")}, caller=None)
    if not ok.get("ok"):
        rec = _throttle_mutate(ctx, guard.get("keys") or [], success=False) if guard_on else {}
        if rec.get("error"):
            return {"ok": False, "code": "login_guard_unavailable", "status": 503,
                    "message": "登录保护暂不可用，请稍后再试"}
        body = {"ok": False, "code": "bad_credentials", "status": 401,
                "message": _msg_tpl(ctx).get("login_failed") or ""}
        if rec.get("blocked"):
            body["retry_after"] = rec.get("retry_after")
        return body
    rec = _throttle_mutate(ctx, guard.get("keys") or [], success=True) if guard_on else {}
    if rec.get("error"):
        return {"ok": False, "code": "login_guard_unavailable", "status": 503,
                "message": "登录保护暂不可用，请稍后再试"}
    now = ctx.api.call("clock.now", {}, caller=None)
    nonce = ctx.api.call("codec.nonce", {"length": 32}, caller=None)
    try:
        ttl = int(cfgv.get("ttl") or 0)
    except (TypeError, ValueError):
        ttl = 0
    if ttl <= 0:
        ttl = 86400
    rec = ctx.api.call("auth.build_session", {
        "token": nonce.get("token"), "username": payload.get("username"),
        "issued": now.get("ts"), "ttl": ttl}, caller=None)
    view = ctx.api.call("auth.session_view", {"record": rec}, caller=None)
    pt = _cfg_paths(ctx).get("session") or ""
    tok = rec.get("token") or ""
    view["effects"] = [{"kind": "write", "module": "agent/auth",
                        "path": pt.format(token=tok) if pt else tok, "value": rec}]
    return view


def _route_change_password(ctx, payload):
    """改密闭环：读配置 → 摘要旧/新/确认 → 纯函数校验 → 写配置新摘要。不落会话。"""
    cfg = ctx.api.call("config.get", {"key": "server.auth"}, caller=None) or {}
    cfgv = cfg.get("value") or {}
    salt = str(cfgv.get("salt") or "")

    def _digest(text):
        return ctx.api.call("codec.digest", {
            "text": salt + ":" + str(text or ""), "algorithm": "sha256"}, caller=None).get("hex")

    check = ctx.api.call("auth.password_check", {
        "old_digest": _digest(payload.get("old_password")),
        "new_digest": _digest(payload.get("new_password")),
        "confirm_digest": _digest(payload.get("confirm")),
        "expect_hash": cfgv.get("password_hash"),
        "tpl": _msg_tpl(ctx)}, caller=None)
    if not check.get("ok"):
        return {"ok": False, "code": check.get("code"), "status": check.get("status") or 400,
                "message": check.get("error")}
    ctx.api.call("config.set_value", {
        "key": "server.auth.password_hash", "value": _digest(payload.get("new_password"))},
        caller=None)
    return {"ok": True, "username": cfgv.get("username") or ""}
