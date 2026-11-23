"""WebDAV 通道：客户端（PROPFIND / PUT / GET / MKCOL / DELETE / HEAD）。

边界与约束：

- 传输面走标准库 http.client；不引 requests / defusedxml 等第三方包；
- 摘要 / base64 / 等待一律走注入的 codec / clock 能力（不自带 hashlib / base64 /
  time）：可传 ``ctx`` 经 ``ctx.api.call`` 委托，也可直接注入 codec / clock 适配对象；
- 远端对象键复用 ``_guard`` 口径拒绝 ``..`` 穿越、绝对路径、UNC、编码穿越；
- XML 解析前拒绝 DOCTYPE / 实体声明，外部实体不展开，XXE 载荷必须失败；
- 上传 / 下载均按块流式，不把整对象一次性读进内存；
- 认证：Basic 预检发送；Digest 按 401 challenge 做 RFC 2617 重试
  （nonce / opaque / qop / nc / cnonce）；
- 幂等：PUT 前 HEAD 比对 ETag / 大小，相同则跳过；传输失败指数退避重试；
  GET 支持 Range 续传（服务端回 206 时续传，回 200 时整体重拉）。

适配面签名（供 ``_providers.py`` 按名接线，本模块不反向依赖 providers）::

    WebDavClient(endpoint, username=None, password=None, *, ctx=None,
                 codec=None, clock=None, cfg=None, timeout=30, auth="auto",
                 chunk_size=65536, max_attempts=3, backoff_base_s=0.2,
                 backoff_cap_s=2.0, max_body_bytes=0)
      -> client

    注入适配面（缺省回落到 ctx.api.call）：
      codec.digest(text: str, algorithm: str) -> hex: str
      codec.base64_encode(data: bytes) -> base64: str
      clock.sleep(seconds: float) -> None

    client.test_connection() -> {"ok": bool, "detail": str}
    client.head(key: str) ->
      {"ok": True, "status": 200, "etag": str|None, "size": int|None}
      | {"ok": False, "code": "not_found"|"unauthorized"|..., "status": int}
    client.propfind(key: str = "", depth: int = 1) ->
      {"ok": True, "entries": [{"key", "size", "etag", "is_dir"}]}
    client.put(key, source, *, size=None, etag=None, skip_identical=True,
               resume=False) ->
      {"ok": True, "size": int, "offset": int, "skipped": bool, "etag": str|None}
      | {"ok": False, "code": str, "offset": int, "status": int}
      source: bytes | 带 ``read(n)`` 的流式对象；bytes 路径仅用于小对象探针。
    client.get(key, sink, *, offset=0, resume=False) ->
      {"ok": True, "size": int, "offset": int, "partial": bool}
      sink: 带 ``write(bytes)`` 的落地对象（文件 / 哈希收集器等）。
    client.mkcol(key) -> {"ok": True} | {"ok": False, "code": "conflict"|..., "status": int}
    client.delete(key) -> {"ok": True} | {"ok": False, "code": "not_found"|..., "status": int}

错误码：``not_found`` / ``unauthorized`` / ``forbidden`` / ``method_not_allowed`` /
``conflict`` / ``precondition_failed`` / ``body_too_large`` / ``locked`` /
``rate_limited`` / ``provider_error`` / ``http_error`` / ``connection_error`` /
``invalid_key`` / ``missing_size`` / ``malformed_xml`` / ``xml_forbidden`` / ``bad_scheme`` /
``blocked_host`` / ``host_not_whitelisted`` / ``codec_error`` / ``capability_missing``。
"""
from __future__ import annotations

import http.client
import io
import re
import urllib.parse
import xml.etree.ElementTree as ElementTree

from . import _guard

_CHUNK_SIZE = 64 * 1024
_DOCTYPE_RE = re.compile(r"<!\s*(DOCTYPE|ENTITY)\b", re.IGNORECASE)
_CHALLENGE_RE = re.compile(r'(\w+)\s*=\s*("([^"]*)"|([^,]+))')

_STATUS_CODE = {
    401: "unauthorized",
    403: "forbidden",
    404: "not_found",
    405: "method_not_allowed",
    409: "conflict",
    412: "precondition_failed",
    413: "body_too_large",
    423: "locked",
    429: "rate_limited",
}


class WebDavError(Exception):
    """客户端层显式错误：``code`` 为结构化错误码，``status`` 为 HTTP 状态码（可 0）。"""

    def __init__(self, code, message, status=0):
        super().__init__(message)
        self.code = code
        self.status = status


def sanitize_key(key):
    """远端对象键校验：委托 ``_guard``；返回规范化 posix 键或 None。"""
    return _guard.sanitize_key(key)


def validate_endpoint(endpoint, cfg=None):
    """端点协议 / 主机校验：委托 ``_guard.validate_endpoint``，返回其判定结构。"""
    return _guard.validate_endpoint(endpoint, cfg)


# ---------------------------------------------------------------- challenge 解析

def _parse_digest_challenge(header):
    """解析 ``WWW-Authenticate: Digest ...``；非 Digest / 缺 nonce 返回 None。"""
    if not header:
        return None
    head, _, body = header.partition(" ")
    if head.strip().lower() != "digest":
        return None
    params = {}
    for match in _CHALLENGE_RE.finditer(body):
        params[match.group(1)] = match.group(3) if match.group(3) is not None else match.group(4)
    if "nonce" not in params:
        return None
    return params


# ---------------------------------------------------------------- 响应映射

def _map_status(status):
    if status in _STATUS_CODE:
        return _STATUS_CODE[status]
    if 500 <= status < 600:
        return "provider_error"
    return "http_error"


def _http_fail(resp, stage):
    return {
        "ok": False,
        "code": _map_status(resp.status),
        "status": resp.status,
        "detail": "%s failed: HTTP %d" % (stage, resp.status),
    }


# ---------------------------------------------------------------- multistatus 解析

def _href_to_rel(href, base_path):
    """把响应 href 归一到相对远端根的键；根自身返回 None。"""
    if not href:
        return None
    path = urllib.parse.urlsplit(href).path
    path = urllib.parse.unquote(path)
    if base_path and path.startswith(base_path):
        path = path[len(base_path):]
    path = path.lstrip("/")
    return path or None


def _parse_multistatus(raw, base_path):
    """解析 207 multistatus XML；DOCTYPE / 实体声明直接拒绝，防 XXE 展开。"""
    text = raw.decode("utf-8", errors="replace")
    if _DOCTYPE_RE.search(text):
        raise WebDavError("xml_forbidden", "DOCTYPE/ENTITY declaration rejected (XXE guard)")
    try:
        root = ElementTree.fromstring(text)
    except ElementTree.ParseError as exc:
        raise WebDavError("malformed_xml", "multistatus XML unparsable: %s" % exc)

    ns = "{DAV:}"
    entries = []
    for response in root.iter(ns + "response"):
        href_el = response.find(ns + "href")
        href = href_el.text if href_el is not None and href_el.text else ""
        rel = _href_to_rel(href, base_path)
        if rel is None:
            continue
        size, etag, is_dir = None, None, False
        prop = response.find(".//" + ns + "prop")
        if prop is not None:
            length = prop.find(ns + "getcontentlength")
            if length is not None and length.text and length.text.strip().isdigit():
                size = int(length.text.strip())
            tag = prop.find(ns + "getetag")
            if tag is not None and tag.text:
                etag = tag.text
            res_type = prop.find(ns + "resourcetype")
            if res_type is not None and res_type.find(ns + "collection") is not None:
                is_dir = True
        entries.append({"key": rel, "size": size, "etag": etag, "is_dir": is_dir})
    return entries


# ---------------------------------------------------------------- 客户端

class WebDavClient:
    """WebDAV 客户端：端点 / 凭证在构造时绑定，方法均为同步阻塞调用。"""

    def __init__(self, endpoint, username=None, password=None, *, ctx=None,
                 codec=None, clock=None, cfg=None, timeout=30, auth="auto",
                 chunk_size=_CHUNK_SIZE, max_attempts=3, backoff_base_s=0.2,
                 backoff_cap_s=2.0, max_body_bytes=0):
        parts = urllib.parse.urlsplit(str(endpoint or ""))
        if parts.scheme not in ("http", "https"):
            raise WebDavError("bad_scheme", "endpoint scheme must be http/https")
        if not parts.hostname:
            raise WebDavError("bad_endpoint", "endpoint missing host")
        # 端点 SSRF 口径由路由层按配置复检；显式传入 cfg 时在客户端再复检一次。
        if cfg is not None:
            guard = _guard.validate_endpoint(endpoint, cfg)
            if not guard["ok"]:
                raise WebDavError(guard["errors"][0], "endpoint rejected by guard")
        self._ctx = ctx
        self._codec = codec
        self._clock = clock
        self._scheme = parts.scheme
        self._host = parts.hostname
        self._port = parts.port or (443 if parts.scheme == "https" else 80)
        self._base_path = parts.path.rstrip("/")
        self._username = username
        self._password = password or ""
        self._auth = auth if auth in ("basic", "digest", "auto") else "auto"
        self._timeout = float(timeout)
        self._chunk_size = int(chunk_size)
        self._max_attempts = max(1, int(max_attempts))
        self._backoff_base = float(backoff_base_s)
        self._backoff_cap = float(backoff_cap_s)
        self._max_body = int(max_body_bytes or 0)

    # ------------------------------------------------------------ 传输接缝

    def _connect(self):
        if self._scheme == "https":
            return http.client.HTTPSConnection(self._host, self._port,
                                              timeout=self._timeout)
        return http.client.HTTPConnection(self._host, self._port,
                                         timeout=self._timeout)

    @staticmethod
    def _rewind(source):
        if source is not None and hasattr(source, "seek"):
            try:
                source.seek(0)
            except (OSError, ValueError, io.UnsupportedOperation):
                pass

    # ------------------------------------------------------------ 能力接缝

    def _digest_hex(self, text, algorithm="md5"):
        """摘要经 codec 能力；适配对象优先，其次 ctx.api.call。"""
        if self._codec is not None:
            return self._codec.digest(text, algorithm)
        if self._ctx is not None:
            row = self._ctx.api.call(
                "codec.digest", {"text": text, "algorithm": algorithm}, caller=None)
            if not row.get("ok"):
                raise WebDavError("codec_error", "digest capability failed")
            return row["hex"]
        raise WebDavError("capability_missing", "codec digest capability not injected")

    def _b64_encode(self, data):
        """base64 编码经 codec 能力；适配对象优先，其次 ctx.api.call。"""
        if self._codec is not None:
            return self._codec.base64_encode(data)
        if self._ctx is not None:
            row = self._ctx.api.call("codec.base64_encode", {"text": data}, caller=None)
            if not row.get("ok"):
                raise WebDavError("codec_error", "base64 encode capability failed")
            return row["text"]
        raise WebDavError("capability_missing", "codec base64 capability not injected")

    def _sleep(self, seconds):
        """等待经 clock 能力；适配对象优先，其次 ctx.api.call。"""
        if self._clock is not None:
            self._clock.sleep(seconds)
            return
        if self._ctx is not None:
            self._ctx.api.call("clock.sleep", {"seconds": seconds}, caller=None)
            return
        raise WebDavError("capability_missing", "clock sleep capability not injected")

    def _basic_header(self):
        raw = ("%s:%s" % (self._username, self._password or "")).encode("utf-8")
        return "Basic " + self._b64_encode(raw)

    def _digest_header(self, challenge, method, uri):
        """按 RFC 2617 计算 Digest 响应头；支持 qop=auth（缺 qop 回落 RFC 2069）。"""
        realm = challenge.get("realm", "")
        nonce = challenge["nonce"]
        opaque = challenge.get("opaque")
        qop_raw = challenge.get("qop") or ""
        qop = "auth" if "auth" in qop_raw.split(",") else ""
        user = self._username
        password = self._password or ""
        ha1 = self._digest_hex("%s:%s:%s" % (user, realm, password), "md5")
        ha2 = self._digest_hex("%s:%s" % (method, uri), "md5")
        nc = 1
        cnonce = self._digest_hex(nonce + ":" + str(nc), "md5")[:8]
        if qop:
            response = self._digest_hex(
                "%s:%s:%08x:%s:%s:%s" % (ha1, nonce, nc, cnonce, qop, ha2), "md5")
            header = (
                'Digest username="%s", realm="%s", nonce="%s", uri="%s", '
                'qop=%s, nc=%08x, cnonce="%s", response="%s"'
                % (user, realm, nonce, uri, qop, nc, cnonce, response)
            )
        else:
            response = self._digest_hex("%s:%s:%s" % (ha1, nonce, ha2), "md5")
            header = (
                'Digest username="%s", realm="%s", nonce="%s", uri="%s", response="%s"'
                % (user, realm, nonce, uri, response)
            )
        if opaque:
            header += ', opaque="%s"' % opaque
        return header

    def _send(self, conn, method, path, headers, body_source, content_length):
        conn.putrequest(method, path)
        for key, value in headers.items():
            conn.putheader(key, str(value))
        if body_source is not None:
            conn.putheader("Content-Length", str(content_length))
        conn.endheaders()
        if body_source is not None:
            while True:
                chunk = body_source.read(self._chunk_size)
                if not chunk:
                    break
                conn.send(chunk)
        return conn.getresponse()

    def _request(self, method, path, *, headers=None, body_source=None,
                 content_length=None):
        """发起请求；401 且支持 Digest 时按 challenge 重试一次。

        body_source 可重读（实现 ``seek(0)``）时，Digest 重试前自动回卷。
        """
        headers = dict(headers or {})
        if self._username and self._auth in ("basic", "auto"):
            headers["Authorization"] = self._basic_header()
        conn = self._connect()
        resp = self._send(conn, method, path, headers, body_source, content_length)
        if (resp.status == 401 and self._username
                and self._auth in ("digest", "auto")):
            challenge = _parse_digest_challenge(resp.getheader("WWW-Authenticate"))
            if challenge:
                resp.read()
                conn.close()
                self._rewind(body_source)
                conn = self._connect()
                headers["Authorization"] = self._digest_header(challenge, method, path)
                resp = self._send(conn, method, path, headers, body_source,
                                  content_length)
        return resp

    @staticmethod
    def _drain(resp):
        try:
            resp.read()
        except (OSError, http.client.HTTPException):
            pass

    # ------------------------------------------------------------ 路径拼接

    def _require_key(self, key):
        safe = _guard.sanitize_key(key)
        if safe is None:
            raise WebDavError("invalid_key",
                              "key rejects traversal/absolute/UNC/encoded escape")
        return safe

    def _path(self, safe):
        tail = (self._base_path + "/" + safe) if safe else self._base_path
        return urllib.parse.quote(tail, safe="/:")

    # ------------------------------------------------------------ 公共方法

    def test_connection(self):
        """探活：HEAD 根路径；返回结构化结果，不抛掀翻路由层。"""
        try:
            resp = self._request("HEAD", self._path(""))
            self._drain(resp)
            if resp.status in (200, 204, 401, 403, 404):
                return {"ok": resp.status not in (401, 403), "detail": "http-%d" % resp.status}
            return {"ok": False, "detail": "http-%d" % resp.status}
        except (OSError, http.client.HTTPException) as exc:
            return {"ok": False, "detail": "connection_error: %s" % exc}

    def head(self, key):
        safe = self._require_key(key)
        resp = self._request("HEAD", self._path(safe))
        if resp.status == 200:
            length = resp.getheader("Content-Length")
            size = int(length) if length and length.strip().isdigit() else None
            return {"ok": True, "status": 200,
                    "etag": resp.getheader("ETag"), "size": size}
        if resp.status == 404:
            return {"ok": False, "code": "not_found", "status": 404}
        return _http_fail(resp, "head")

    def propfind(self, key="", depth=1):
        safe = self._require_key(key)
        depth = 1 if int(depth) > 1 else int(depth)
        resp = self._request(
            "PROPFIND", self._path(safe),
            headers={"Depth": str(depth), "Accept": "application/xml"})
        if resp.status not in (200, 207):
            return _http_fail(resp, "propfind")
        raw = resp.read()
        entries = _parse_multistatus(raw, self._base_path)
        return {"ok": True, "entries": entries}

    def put(self, key, source, *, size=None, etag=None, skip_identical=True,
            resume=False):
        safe = self._require_key(key)
        path = self._path(safe)

        if isinstance(source, (bytes, bytearray)):
            data = bytes(source)
            size = len(data)
            body = io.BytesIO(data)
        else:
            body = source
            if size is None:
                raise WebDavError("missing_size",
                                  "streaming put requires explicit object size")
            size = int(size)
        if self._max_body > 0 and size > self._max_body:
            return {"ok": False, "code": "body_too_large", "offset": 0,
                    "detail": "body exceeds %d bytes" % self._max_body}

        if skip_identical:
            probe = self.head(safe)
            if probe.get("ok"):
                same_etag = etag is not None and probe.get("etag") == etag
                same_size = probe.get("size") == size and (etag is None or same_etag)
                if same_etag or same_size:
                    return {"ok": True, "size": size, "offset": size,
                            "skipped": True, "etag": probe.get("etag")}

        last = {"ok": False, "code": "transient", "offset": 0}
        for attempt in range(self._max_attempts):
            self._rewind(body)
            try:
                resp = self._request(
                    "PUT", path,
                    headers={"Content-Type": "application/octet-stream"},
                    body_source=body, content_length=size)
                status = resp.status
                if status in (200, 201, 204):
                    return {"ok": True, "size": size, "offset": size,
                            "skipped": False, "etag": resp.getheader("ETag")}
                if status in (409, 412, 423):
                    return {"ok": False, "code": _map_status(status),
                            "status": status, "offset": 0}
                if status == 413:
                    return {"ok": False, "code": "body_too_large",
                            "status": status, "offset": 0}
                last = {"ok": False, "code": _map_status(status),
                        "status": status, "offset": 0}
                if status != 429 and not (500 <= status < 600):
                    return last
            except (OSError, http.client.HTTPException) as exc:
                last = {"ok": False, "code": "connection_error",
                        "offset": 0, "detail": str(exc)}
            if attempt + 1 < self._max_attempts:
                self._sleep(self._backoff_delay(attempt))
        return last

    def get(self, key, sink, *, offset=0, resume=False):
        safe = self._require_key(key)
        path = self._path(safe)
        headers = {"Accept": "application/octet-stream"}
        start = int(offset or 0)
        if resume and start > 0:
            headers["Range"] = "bytes=%d-" % start
        resp = self._request("GET", path, headers=headers)
        if resp.status == 404:
            return {"ok": False, "code": "not_found", "status": 404, "offset": 0}
        if resp.status not in (200, 206):
            return _http_fail(resp, "get")

        partial = resp.status == 206
        if not partial and start > 0:
            # 服务端忽略 Range：整体重拉，落地方自行截断。
            start = 0
        written = 0
        while True:
            chunk = resp.read(self._chunk_size)
            if not chunk:
                break
            sink.write(chunk)
            written += len(chunk)
        length = resp.getheader("Content-Length")
        total = int(length) if length and length.strip().isdigit() else written
        return {"ok": True, "size": total, "offset": written, "partial": partial}

    def mkcol(self, key):
        safe = self._require_key(key)
        resp = self._request("MKCOL", self._path(safe))
        if resp.status in (200, 201):
            return {"ok": True, "status": resp.status}
        return {"ok": False, "code": _map_status(resp.status),
                "status": resp.status, "detail": "MKCOL HTTP %d" % resp.status}

    def delete(self, key):
        safe = self._require_key(key)
        resp = self._request("DELETE", self._path(safe))
        if resp.status in (200, 204):
            return {"ok": True, "status": resp.status}
        if resp.status == 404:
            return {"ok": False, "code": "not_found", "status": 404}
        return _http_fail(resp, "delete")

    # ------------------------------------------------------------ 退避

    def _backoff_delay(self, attempt):
        """指数退避：base * 2^attempt，封顶 cap；与 _pure 口径一致。"""
        base = max(0.0, self._backoff_base)
        cap = max(base, self._backoff_cap)
        return min(cap, base * (2 ** max(0, attempt)))
