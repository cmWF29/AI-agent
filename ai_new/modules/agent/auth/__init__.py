"""鉴权模块：凭据比对、会话形状，以及给 HTTP 闸用的系统校验路由。

纯计算在 private/_pure；`verify` 是装配期收 ctx 的系统路由（caller=None 放行），
读自己 data 下的会话记录，判定交纯函数。模块不自己做登录页、不发通知。
"""
from __future__ import annotations

from .private import _pure


def _msg_tpl(ctx):
    """消息模板表：auth 模块自己的 data，读不到就退化成空。"""
    row = ctx.api.call("store.read", {
        "module": "agent/auth", "path": "messages.yaml"}, caller=None)
    return row.get("value") or {}


def setup(ctx):
    md = ctx.storage.own(__file__)

    def _verify(payload):
        cfg = ctx.cfg.get("server") or {}
        auth = cfg.get("auth") or {}
        legacy = cfg.get("token") or ""
        token = str((payload or {}).get("token") or "")
        enabled = bool(auth.get("enabled"))

        # 开放态：既没开登录、也没配旧令牌（本机开发）
        if not enabled and not legacy:
            return {"allow": True, "mode": "open"}
        # 旧令牌兼容：过渡期不断既有入口
        if legacy and token == legacy:
            return {"allow": True, "mode": "legacy"}
        if not enabled:
            return {"allow": False, "mode": "legacy", "reason": "unauthorized"}

        record = md.yaml_read("sessions/%s.yaml" % token, None)
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
        return {"enabled": bool(auth.get("enabled")),
                "legacy": bool(server.get("token")),
                "username": auth.get("username") or ""}

    pairs = [
        ("auth.credentials_ok", _pure.credentials_ok),
        ("auth.password_check", _pure.change_password),
        ("auth.build_session", _pure.build_session),
        ("auth.session_view", _pure.session_view),
        ("auth.session_path", _pure.session_path),
    ]
    for name, fn in pairs:
        ctx.api.register(name, lambda payload, fn=fn: fn(payload), module="auth")
    ctx.api.register("auth.login", _route_login, "登录闭环：配置→摘要比对→发会话→落盘→会话视图",
                     module="auth")
    ctx.api.register("auth.change_password", _route_change_password,
                     "修改密码：验旧密码→摘要校验→写配置新摘要", module="auth")
    ctx.api.register("auth.verify", lambda c, p: _verify(p), module="auth")
    ctx.api.register("auth.status", lambda c, p: _status(p), module="auth")
    return True


def _route_login(ctx, payload):
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
        return {"ok": False, "code": "bad_credentials", "status": 401,
                "message": _msg_tpl(ctx).get("login_failed") or ""}
    now = ctx.api.call("clock.now", {}, caller=None)
    nonce = ctx.api.call("codec.nonce", {"length": 32}, caller=None)
    rec = ctx.api.call("auth.build_session", {
        "token": nonce.get("token"), "username": payload.get("username"),
        "issued": now.get("ts"), "ttl": cfgv.get("ttl")}, caller=None)
    view = ctx.api.call("auth.session_view", {"record": rec}, caller=None)
    view["effects"] = [{"kind": "write", "module": "agent/auth",
                        "path": "sessions/%s.yaml" % rec.get("token"), "value": rec}]
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
