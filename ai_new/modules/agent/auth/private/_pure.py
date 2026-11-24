"""鉴权纯函数：凭据比对、会话成形与有效性判定。只依赖标准库，不读盘、不取时间。"""
from __future__ import annotations

import hmac
import re


DEFAULT_USERNAME = "admin"
DEFAULT_PASSWORD = "123456"
_TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{1,128}$")


def valid_token(p):
    """会话令牌只允许 URL 安全字符，拒绝路径片段与超长值。

    令牌会拼进 ``sessions/{token}.yaml``；先在这里收口，任何路径分隔符、点段、
    空字节都不可能进入文件路径。
    """
    token = str((p or {}).get("token") or "")
    return {"ok": bool(_TOKEN_RE.fullmatch(token)), "token": token}


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
    """用户名与摘要都相等才通过；空摘要一律拒绝，避免摘要引擎故障时放行。"""
    username = str(p.get("username") or "")
    expect = str(p.get("expect_username") or "")
    digest = str(p.get("digest") or "")
    expect_hash = str(p.get("expect_hash") or "")
    if not username or not expect or not digest or not expect_hash:
        return {"ok": False, "code": "bad_credentials"}
    if not hmac.compare_digest(username.encode("utf-8"), expect.encode("utf-8")):
        return {"ok": False, "code": "bad_credentials"}
    if not hmac.compare_digest(digest.encode("utf-8"), expect_hash.encode("utf-8")):
        return {"ok": False, "code": "bad_credentials"}
    return {"ok": True, "username": username}


def change_password(p):
    """改密校验（纯计算）：旧摘要匹配、新密码非空、两次新密码一致。不碰盘、不发摘要。

    期望摘要为空时也必须拒绝：空哈希意味着账号尚未建立可用凭据，不能把
    “没有旧密码”当成“旧密码正确”，否则匿名请求就能设置新密码。
    """
    old_digest = str(p.get("old_digest") or "")
    new_digest = str(p.get("new_digest") or "")
    confirm_digest = str(p.get("confirm_digest") or "")
    expect_hash = str(p.get("expect_hash") or "")
    tpl = p.get("tpl") or {}
    if not expect_hash or not old_digest:
        return {"ok": False, "code": "bad_old_password", "status": 400,
                "error": tpl.get("bad_old_password") or ""}
    if not hmac.compare_digest(old_digest.encode("utf-8"), expect_hash.encode("utf-8")):
        return {"ok": False, "code": "bad_old_password", "status": 400,
                "error": tpl.get("bad_old_password") or ""}
    if not new_digest:
        return {"ok": False, "code": "weak_password", "status": 400,
                "error": tpl.get("weak_password") or ""}
    if not hmac.compare_digest(new_digest.encode("utf-8"), confirm_digest.encode("utf-8")):
        return {"ok": False, "code": "confirm_mismatch", "status": 400,
                "error": tpl.get("confirm_mismatch") or ""}
    return {"ok": True}


def build_session(p):
    """造会话记录形状：expires = issued + ttl；ttl 缺失/非法按 0 处理，不抛异常。"""
    issued = float(p.get("issued") or 0)
    try:
        ttl = int(p.get("ttl") or 0)
    except (TypeError, ValueError):
        ttl = 0
    return {"token": p.get("token") or "", "username": p.get("username") or "",
            "issued": issued, "expires": issued + ttl, "ttl": ttl}


def session_valid(p):
    """会话是否存在、是否过期。缺少/非法 expires 一律按无效处理（fail-closed）。"""
    rec = p.get("record") or {}
    now = float(p.get("now") or 0)
    if not rec.get("token"):
        return {"valid": False, "expired": False, "reason": "no_record"}
    expires = rec.get("expires")
    if expires is None or isinstance(expires, bool):
        return {"valid": False, "expired": False, "reason": "no_expiry",
                "username": rec.get("username")}
    try:
        expires_at = float(expires)
    except (TypeError, ValueError):
        return {"valid": False, "expired": False, "reason": "bad_expiry",
                "username": rec.get("username")}
    if now >= expires_at:
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
    """注销要删的会话记录相对路径：模板由需求层配置表给出，纯函数只填参。

    模板缺失时返回空路径，由调用方按未登录/不可操作收口；不能把裸令牌
    当成模块根下的相对路径，否则配置缺失会悄悄改写到别的位置。
    """
    paths = p.get("paths") or {}
    t = str(paths.get("session") or "")
    tok = str(p.get("token") or "")
    return {"path": t.format(token=tok) if t else ""}
