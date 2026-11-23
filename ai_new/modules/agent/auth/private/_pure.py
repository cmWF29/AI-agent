"""鉴权纯函数：凭据比对、会话成形与有效性判定。不读盘、不取时间、不碰 stdlib。"""
from __future__ import annotations


DEFAULT_USERNAME = "admin"
DEFAULT_PASSWORD = "123456"


def default_password_state(p):
    """判定是否仍是默认/空口令（纯计算，不读盘不计时钟）。

    入参 ``p``：``auth`` 配置段（enabled/username/password_hash），``weak_digest``
    为默认口令 ``salt:123456`` 的摘要（调用方经 codec 算好传入）。

    规则：登录校验未开启不算告警；哈希为空，或用户名仍是默认账号且摘要命中默认口令，
    判为默认弱口令。返回 ``{default, reason}``，reason 供日志区分，不回显给前端。
    """
    auth = p.get("auth") or {}
    if not bool(auth.get("enabled")):
        return {"default": False, "reason": ""}
    username = str(auth.get("username") or "")
    password_hash = str(auth.get("password_hash") or "").strip()
    weak_digest = str(p.get("weak_digest") or "")
    if not password_hash:
        return {"default": True, "reason": "password_hash_empty"}
    if username == DEFAULT_USERNAME and weak_digest and password_hash == weak_digest:
        return {"default": True, "reason": "default_credentials"}
    return {"default": False, "reason": ""}


def credentials_ok(p):
    """用户名与摘要都相等才通过；不泄露出是哪一项错。"""
    username = str(p.get("username") or "")
    expect = str(p.get("expect_username") or "")
    digest = str(p.get("digest") or "")
    expect_hash = str(p.get("expect_hash") or "")
    if not username or username != expect or digest != expect_hash:
        return {"ok": False, "code": "bad_credentials"}
    return {"ok": True, "username": username}


def change_password(p):
    """改密校验（纯计算）：旧摘要匹配、新密码非空、两次新密码一致。不碰盘、不发摘要。"""
    old_digest = str(p.get("old_digest") or "")
    new_digest = str(p.get("new_digest") or "")
    confirm_digest = str(p.get("confirm_digest") or "")
    expect_hash = str(p.get("expect_hash") or "")
    tpl = p.get("tpl") or {}
    if expect_hash and old_digest != expect_hash:
        return {"ok": False, "code": "bad_old_password", "status": 400,
                "error": tpl.get("bad_old_password") or ""}
    if not new_digest:
        return {"ok": False, "code": "weak_password", "status": 400,
                "error": tpl.get("weak_password") or ""}
    if new_digest != confirm_digest:
        return {"ok": False, "code": "confirm_mismatch", "status": 400,
                "error": tpl.get("confirm_mismatch") or ""}
    return {"ok": True}


def build_session(p):
    """造会话记录形状：expires = issued + ttl。"""
    issued = float(p.get("issued") or 0)
    ttl = int(p.get("ttl"))
    return {"token": p.get("token") or "", "username": p.get("username") or "",
            "issued": issued, "expires": issued + ttl, "ttl": ttl}


def session_valid(p):
    """会话是否存在、是否过期。纯判定，时间由调用方给。"""
    rec = p.get("record") or {}
    now = float(p.get("now") or 0)
    if not rec.get("token"):
        return {"valid": False, "expired": False, "reason": "no_record"}
    expires = rec.get("expires")
    if expires is not None and now >= float(expires):
        return {"valid": False, "expired": True,
                "username": rec.get("username"), "expires": expires}
    return {"valid": True, "expired": False,
            "username": rec.get("username"), "expires": expires}


def session_view(p):
    """对外露出的会话视图：不带内部字段。"""
    rec = p.get("record") or {}
    return {"token": rec.get("token"), "username": rec.get("username"),
            "expires": rec.get("expires")}


def session_path(p):
    """注销要删的会话记录相对路径：模板由需求层配置表给出，纯函数只填参。"""
    paths = p.get("paths") or {}
    t = paths.get("session") or ""
    tok = p.get("token") or ""
    return {"path": t.format(token=tok) if t else tok}
