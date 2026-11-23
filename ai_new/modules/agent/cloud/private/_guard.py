"""出站与路径安全校验（纯函数，不联网、不碰盘）。

覆盖负向面：

- 协议：默认仅 ``https``；``http`` 须在配置白名单显式允许；
- 主机：回环 / 私网 / 链路本地 / IPv6 唯一本地 / 保留与测试网段一律拒绝；
- DNS：解析结果落在私网的地址拒绝（``ip_is_private`` 供解析接缝回填后判定）；
- 跳转：30x Location 指向被拦主机时拒绝；
- 路径：``..`` 穿越、绝对路径、UNC、Windows 保留名、编码穿越段拒绝；
- 体积：响应体/上传体超过上限拒绝。

本层只做判定；真实 DNS 解析与跟随跳转发生在 net 接缝，接入点在报告中标注边界。
"""
from __future__ import annotations

import ipaddress
import os
import re

# 默认协议白名单：仅 https；http 须经配置 cloud.schemes 显式放开。
DEFAULT_SCHEMES = ("https",)

_WINDOWS_RESERVED = {
    "CON", "PRN", "AUX", "NUL",
    "COM1", "COM2", "COM3", "COM4", "COM5", "COM6", "COM7", "COM8", "COM9",
    "LPT1", "LPT2", "LPT3", "LPT4", "LPT5", "LPT6", "LPT7", "LPT8", "LPT9",
}

_ENCODED_SEP = re.compile(r"%(2e|2f|5c|5e)", re.IGNORECASE)

# IPv4 拦截网段：回环 / 私网 / 链路本地 / 保留 / 测试网段 / 组播 / 未用。
_V4_BLOCKED = [
    ipaddress.ip_network("0.0.0.0/8"),
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("192.0.0.0/24"),
    ipaddress.ip_network("192.0.2.0/24"),
    ipaddress.ip_network("198.18.0.0/15"),
    ipaddress.ip_network("198.51.100.0/24"),
    ipaddress.ip_network("203.0.113.0/24"),
    ipaddress.ip_network("224.0.0.0/4"),
    ipaddress.ip_network("240.0.0.0/4"),
]

_V6_BLOCKED = [
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("::/128"),
    ipaddress.ip_network("fc00::/7"),   # 唯一本地地址 ULA
    ipaddress.ip_network("fe80::/10"),  # 链路本地
    ipaddress.ip_network("ff00::/8"),   # 组播
]


class GuardError(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


# ---------------------------------------------------------------- 主机与协议

def _parse_url(url):
    """极简 URL 拆分：(scheme, host, path)；不引入 urllib 接缝外的解析库。"""
    text = str(url or "")
    scheme = ""
    if "://" in text:
        scheme, text = text.split("://", 1)
    path = ""
    if "/" in text:
        hostport, path = text.split("/", 1)
        path = "/" + path
    else:
        hostport = text
    if hostport.startswith("["):
        host = hostport[1:].split("]", 1)[0]
    elif hostport.count(":") > 1:
        host = hostport  # IPv6 字面量（未加方括号），整体保留
    elif ":" in hostport:
        host = hostport.rsplit(":", 1)[0]
    else:
        host = hostport
    return scheme.lower(), host.lower().strip("[]"), path


def _unwrap(ip):
    """IPv4-mapped IPv6（::ffff:a.b.c.d）解包成 IPv4 地址对象。"""
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        return ip.ipv4_mapped
    return ip


def ip_is_private(ip_text):
    """字面量 IP 是否落在拦截网段；无法解析返回 None（交域名白名单/解析接缝判定）。"""
    try:
        ip = ipaddress.ip_address(str(ip_text or "").strip())
    except ValueError:
        return None
    ip = _unwrap(ip)
    nets = _V4_BLOCKED if isinstance(ip, ipaddress.IPv4Address) else _V6_BLOCKED
    return any(ip in net for net in nets)


def host_is_blocked(host):
    """主机名/字面量地址拦截：字面量直判；域名不在这里做 DNS（解析接缝回填后判定）。"""
    raw = (host or "").strip().lower()
    if raw.startswith("["):
        h = raw[1:].split("]", 1)[0]
    else:
        h = raw
    if not h:
        return True
    if h in ("localhost", "localhost."):
        return True
    # 先按字面量 IP（IPv4/IPv6）直判；解析不成再剥端口重试 IPv4。
    verdict = ip_is_private(h)
    if verdict is not None:
        return bool(verdict)
    if ":" in h:
        verdict = ip_is_private(h.rsplit(":", 1)[0])
        if verdict is not None:
            return bool(verdict)
    return False


def validate_endpoint(endpoint, cfg=None):
    """校验端点协议与主机。返回 ``{"ok", "errors"}``；错误码见 messages.yaml。"""
    cfg = cfg or {}
    schemes = tuple(cfg.get("schemes") or DEFAULT_SCHEMES)
    allowed_hosts = cfg.get("allowed_hosts") or []
    errors = []
    endpoint = str(endpoint or "").strip()
    scheme, host, _ = _parse_url(endpoint)
    if not scheme:
        errors.append("bad_endpoint")
        return {"ok": False, "errors": errors}
    if scheme not in schemes:
        errors.append("bad_scheme")
    if host and host_is_blocked(host):
        errors.append("blocked_host")
    if allowed_hosts and host and host not in allowed_hosts:
        errors.append("host_not_whitelisted")
    return {"ok": not errors, "errors": errors, "host": host, "scheme": scheme}


def validate_redirect(base_url, location, cfg=None):
    """校验 30x 跳转目标：相对地址拼回 base 后，按端点规则复检目标主机。"""
    if not location:
        return {"ok": False, "errors": ["bad_redirect"]}
    base_scheme, base_host, _ = _parse_url(base_url)
    target_scheme, target_host, _ = _parse_url(location)
    if not target_scheme:
        target_scheme = base_scheme
    if not target_host:
        target_host = base_host
    if host_is_blocked(target_host):
        return {"ok": False, "errors": ["redirect_blocked_host"], "host": target_host}
    schemes = tuple((cfg or {}).get("schemes") or DEFAULT_SCHEMES)
    if target_scheme not in schemes:
        return {"ok": False, "errors": ["bad_scheme"], "host": target_host}
    return {"ok": True, "errors": [], "host": target_host}


# ---------------------------------------------------------------- 对象键路径

def _reserved_name(part):
    stem = part.split(".", 1)[0].upper()
    return stem in _WINDOWS_RESERVED


def sanitize_key(key):
    """远端对象键校验：拒绝绝对路径 / UNC / ``..`` 穿越 / 编码穿越 / Windows 保留名。

    返回规范化 posix 键；不可信返回 None。
    """
    rel = str(key or "").replace("\\", "/")
    lowered = rel.lower()
    if _ENCODED_SEP.search(rel):
        return None
    if lowered.startswith("//"):
        return None  # UNC 路径
    if rel.startswith("/"):
        return None  # 绝对路径
    rel = rel.lstrip("/")
    parts = [p for p in rel.split("/") if p not in ("", ".")]
    for part in parts:
        if part == ".." or _reserved_name(part):
            return None
    return "/".join(parts)


def resolve_within(root, rel_path):
    """本地路径防符号链接逃逸：realpath 后必须仍在 root 之内，否则抛 GuardError。"""
    root_real = os.path.realpath(str(root))
    candidate = os.path.realpath(os.path.join(root_real, str(rel_path or "")))
    if candidate != root_real and not candidate.startswith(root_real + os.sep):
        raise GuardError("path_escape", "path escapes data root")
    return candidate


# ---------------------------------------------------------------- 体积上限

def check_body_size(data, max_bytes):
    """响应/上传体体积校验；超限抛 GuardError。max_bytes 为 0/缺省表示不限制。"""
    size = len(data or b"")
    limit = int(max_bytes or 0)
    if limit > 0 and size > limit:
        raise GuardError("body_too_large", "body exceeds %d bytes" % limit)
    return size
