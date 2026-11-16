"""鉴权纯函数：凭据比对、会话成形与有效性判定。不读盘、不取时间、不碰 stdlib。"""
from __future__ import annotations


def credentials_ok(p):
    """用户名与摘要都相等才通过；不泄露出是哪一项错。"""
    username = str(p.get("username") or "")
    expect = str(p.get("expect_username") or "")
    digest = str(p.get("digest") or "")
    expect_hash = str(p.get("expect_hash") or "")
    if not username or username != expect or digest != expect_hash:
        return {"ok": False, "code": "bad_credentials"}
    return {"ok": True, "username": username}


def build_session(p):
    """造会话记录形状：expires = issued + ttl。"""
    issued = float(p.get("issued") or 0)
    ttl = int(p.get("ttl") or 86400)
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
