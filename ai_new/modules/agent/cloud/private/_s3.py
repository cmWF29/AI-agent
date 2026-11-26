"""S3 兼容对象存储通道：SigV4 签名 + 对象操作（纯标准库，注入式 HTTP 传输）。

覆盖 AWS S3 / MinIO / 阿里云 OSS S3 模式共同的 Signature Version 4 协议面：

- 签名：hmac-sha256 规范请求串、``Authorization`` 头、``x-amz-content-sha256``、
  ``x-amz-date``；路径 URI 编码（``/`` 不编码、空格 ``%20``）、查询串按名/值排序；
- 对象：``PUT`` / ``GET`` / ``HEAD``（ETag / Content-Length / SHA256 校验和）/
  ``ListObjectsV2``（``list-type=2`` + continuation token 分页）/ ``DELETE``；
- 分片：``CreateMultipartUpload`` / ``UploadPart`` / ``CompleteMultipartUpload``，
  按阈值自动切分（最小分片可配）；断点续传记录已完成分片，重跑跳过；
- 校验：本地 SHA256 与远端 ``x-amz-checksum-sha256``（ETag 兜底）比对；
- 重试：429 / 5xx 指数退避 + 抖动，尊重 ``Retry-After``；并发上限与速率上限可配。

边界约束：

- 出站只经注入式 ``transport``（默认委托 ``net.request`` 能力接缝）；模块内不直连
  socket / urllib；写盘由路由层经 effect 交 runtime，本层只回传断点状态；
- 凭证由路由层经 ``_seal`` 解封后注入；本层不落日志、不回写视图、不进响应；
- 摘要 / 随机数 / 时钟一律走 ctx 接缝（codec / clock），不自持哈希与时钟实现。
"""
from __future__ import annotations

import hashlib
import hmac
import io
import threading
import xml.etree.ElementTree as ElementTree

from . import _guard, _pure

_SERVICE = "s3"
_DEFAULT_REGION = "us-east-1"
_DEFAULT_PART_MIN = 5 * 1024 * 1024
_DEFAULT_THRESHOLD = 5 * 1024 * 1024
# 单分片驻留内存硬上限：任何策略下分片不得超过 8MiB，100MB 级对象不整文件进内存。
_PART_MAX_DEFAULT = 8 * 1024 * 1024
_LIST_PAGE = "1000"

_UNRESERVED = frozenset(
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz01234567-_.~")
_HEX = "0123456789ABCDEF"


# ---------------------------------------------------------------- 编码与规范串

def _pct_encode(text, encode_slash=False):
    """SigV4 URI 编码：未保留字符原样保留；``/`` 默认保留，查询串编码时转 ``%2F``。"""
    out = []
    for ch in str(text):
        if ch in _UNRESERVED or (ch == "/" and not encode_slash):
            out.append(ch)
            continue
        for byte in ch.encode("utf-8"):
            out.append("%" + _HEX[byte >> 4] + _HEX[byte & 15])
    return "".join(out)


def _parse_url(url):
    """极简 URL 拆分：(scheme, hostport, path, query)；不引入 urllib 接缝外解析库。"""
    text = str(url or "")
    scheme = ""
    if "://" in text:
        scheme, text = text.split("://", 1)
    query = ""
    if "?" in text:
        text, query = text.split("?", 1)
    hostport, _, path = text.partition("/")
    return {"scheme": scheme.lower(), "host": hostport, "path": "/" + path,
            "query": query}


def _unquote(text):
    """百分号解码（SigV4 规范查询：先解码再重新编码，避免二次编码）。"""
    out = bytearray()
    i = 0
    text = str(text or "")
    while i < len(text):
        ch = text[i]
        if ch == "%" and i + 2 < len(text):
            try:
                out.append(int(text[i + 1:i + 3], 16))
                i += 3
                continue
            except ValueError:
                pass
        out.extend(ch.encode("utf-8"))
        i += 1
    return out.decode("utf-8")


def _parse_query(query):
    pairs = []
    for item in str(query or "").split("&"):
        if not item:
            continue
        name, _, value = item.partition("=")
        pairs.append((_unquote(name), _unquote(value)))
    return pairs


def _canonical_query(pairs):
    encoded = sorted((_pct_encode(n, True), _pct_encode(v, True)) for n, v in pairs)
    return "&".join("%s=%s" % (n, v) for n, v in encoded)


def _canonical_headers(headers):
    """规范头部：名小写、值去首尾空白；返回 (规范头串, 签名头列表)。"""
    normalized = {}
    for name, value in (headers or {}).items():
        normalized[str(name).lower()] = str(value).strip()
    names = sorted(normalized)
    canonical = "".join("%s:%s\n" % (n, normalized[n]) for n in names)
    return canonical, ";".join(names)


def _xml_escape(text):
    return (str(text).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


# ---------------------------------------------------------------- 签名原语

def _sha256_hex(ctx, raw):
    row = ctx.api.call("codec.digest", {"text": raw, "algorithm": "sha256"},
                       caller=None)
    return str(row.get("hex") or "")


def _hmac(key, msg):
    if isinstance(msg, str):
        msg = msg.encode("utf-8")
    return hmac.new(key, bytes(msg), "sha256").digest()


def _signing_key(secret, date_stamp, region, service):
    k = _hmac(("AWS4" + secret).encode("utf-8"), date_stamp)
    k = _hmac(k, region)
    k = _hmac(k, service)
    k = _hmac(k, "aws4_request")
    return k


def _amz_now(ctx):
    now = ctx.api.call("clock.now", {}, caller=None)
    iso = str(now.get("iso") or "")
    compact = iso.replace("-", "").replace(":", "")
    return {"amz_date": compact, "date_stamp": compact[:8]}


def sign_request(ctx, method, url, headers, body, region, access_key, secret_key,
                 service=_SERVICE):
    """计算 SigV4 签名，返回带 ``Authorization`` / 签名头的完整头字典（纯函数）。

    ``headers`` 为待签名的业务头（Host / x-amz-date / x-amz-content-sha256 /
    Content-Type 等）；返回字典在其基础上追加 ``Authorization``。
    """
    parsed = _parse_url(url)
    body = bytes(body or b"")
    now = _amz_now(ctx)
    payload_hash = _sha256_hex(ctx, body)

    base = {
        "Host": parsed["host"],
        "x-amz-date": now["amz_date"],
        "x-amz-content-sha256": payload_hash,
    }
    for name, value in (headers or {}).items():
        base[name] = value
    canonical_headers, signed_header_list = _canonical_headers(base)

    path_segments = [_pct_encode(seg) for seg in parsed["path"].split("/") if seg]
    canonical_uri = "/" + "/".join(path_segments)
    canonical_query = _canonical_query(_parse_query(parsed["query"]))

    canonical_request = "\n".join([
        str(method).upper(), canonical_uri, canonical_query,
        canonical_headers, signed_header_list, payload_hash,
    ])
    scope = "%s/%s/%s/%s" % (now["date_stamp"], region, service, "aws4_request")
    string_to_sign = "\n".join([
        "AWS4-HMAC-SHA256", now["amz_date"], scope,
        _sha256_hex(ctx, canonical_request),
    ])
    signing_key = _signing_key(secret_key, now["date_stamp"], region, service)
    signature = hmac.new(signing_key, string_to_sign.encode("utf-8"),
                         "sha256").hexdigest()

    authorization = (
        "AWS4-HMAC-SHA256 Credential=%s/%s, SignedHeaders=%s, Signature=%s"
        % (access_key, scope, signed_header_list, signature))
    signed = dict(base)
    signed["Authorization"] = authorization
    return signed


# ---------------------------------------------------------------- 速率闸门

class _RateGate:
    """并发上限 + 速率上限闸门；等待走 clock 接缝，不自持时钟与随机数。"""

    def __init__(self, concurrency, rate_per_s):
        self._cond = threading.Condition()
        self._inflight = 0
        self._concurrency = max(1, int(concurrency or 1))
        self._min_interval = (1.0 / float(rate_per_s)) if float(rate_per_s or 0) > 0 else 0.0
        self._last_ts = 0.0

    @staticmethod
    def _monotonic(ctx):
        row = ctx.api.call("clock.now", {}, caller=None)
        return float(row.get("ts") or 0.0)

    def run(self, ctx, fn):
        with self._cond:
            while self._inflight >= self._concurrency:
                self._cond.wait()
            self._inflight += 1
            now = self._monotonic(ctx)
            wait = 0.0
            if self._min_interval > 0:
                wait = max(0.0, self._last_ts + self._min_interval - now)
                self._last_ts = now + wait
            else:
                self._last_ts = now
        if wait > 0:
            ctx.api.call("clock.sleep", {"seconds": wait}, caller=None)
        try:
            return fn()
        finally:
            with self._cond:
                self._inflight -= 1
                self._cond.notify()


# ---------------------------------------------------------------- 结果分类

def _classify(status, row):
    status = int(status or 0)
    if status == 403:
        body = str((row or {}).get("text") or "")
        if "SignatureDoesNotMatch" in body or "signature" in body.lower():
            return "signature_mismatch"
        return "access_denied"
    if status == 404:
        return "not_found"
    if status == 429:
        return "rate_limited"
    if status in (400, 401, 409, 410, 413):
        return "access_denied" if status == 401 else "provider_error"
    if 500 <= status < 600:
        return "transient"
    if not (row or {}).get("ok"):
        return "connection_error"
    return "provider_error"


def _retryable(status, row):
    status = int(status or 0)
    if status == 429 or 500 <= status < 600:
        return True
    if not (row or {}).get("ok"):
        return (row or {}).get("code") in ("unreachable", "net_error")
    return False


# ---------------------------------------------------------------- 客户端

def _default_transport(ctx, method, url, headers, body, timeout):
    """默认传输：委托 ``net.request`` 能力接缝；不直连 socket / urllib。"""
    return ctx.api.call("net.request", {
        "method": method, "url": url, "headers": headers,
        "body": body, "timeout": timeout}, caller=None)


class S3Client:
    """S3 兼容对象客户端：端点 / 凭证在构造时绑定，方法均为同步调用。"""

    def __init__(self, ctx, profile, credentials, transport=None, policy=None):
        self.ctx = ctx
        self.endpoint = str(profile.get("endpoint") or "").rstrip("/")
        creds = dict(credentials or {})
        self.bucket = str(creds.get("bucket") or profile.get("root_dir") or "")
        self.region = str(creds.get("region") or _DEFAULT_REGION)
        self.access_key = str(creds.get("access_key") or creds.get("username") or "")
        self.secret_key = str(creds.get("secret_key") or creds.get("password") or "")
        self.transport = transport or _default_transport

        policy = dict(policy or profile.get("policy") or {})
        self.max_attempts = max(1, int(policy.get("max_attempts") or 3))
        self.backoff_base_s = float(policy.get("backoff_base_s") or 1)
        self.backoff_cap_s = float(policy.get("backoff_cap_s") or 30)
        self.max_body = int(policy.get("max_body_bytes") or 0)
        self.multipart_threshold = int(policy.get("multipart_threshold")
                                       or _DEFAULT_THRESHOLD)
        self.part_min_size = int(policy.get("multipart_min_size")
                                 or _DEFAULT_PART_MIN)
        self.part_max_bytes = int(policy.get("part_max_bytes")
                                  or _PART_MAX_DEFAULT)
        self._gate = _RateGate(int(policy.get("concurrency") or 4),
                               int(policy.get("rate_per_s") or 0))

    # ------------------------------------------------------------ 传输与退避

    def _jitter_fraction(self):
        tok = self.ctx.api.call("codec.nonce", {"length": 8}, caller=None).get("token") or ""
        dig = self.ctx.api.call("codec.digest", {"text": "s3-jitter:" + tok},
                                caller=None).get("hex") or "0"
        try:
            return int(dig[:8], 16) / float(0xFFFFFFFF)
        except ValueError:
            return 0.0

    def _backoff(self, attempt, row):
        headers = (row or {}).get("headers") or {}
        retry_after = headers.get("retry-after")
        if retry_after:
            try:
                return min(self.backoff_cap_s, max(0.0, float(retry_after)))
            except ValueError:
                pass
        return _pure.backoff_jittered(attempt, self.backoff_base_s, self.backoff_cap_s,
                                      ratio=0.25, fraction=self._jitter_fraction())

    def _send_with_retry(self, method, url, headers, body):
        last_row = {"ok": False, "status": 0, "headers": {}}
        for attempt in range(self.max_attempts):
            row = self.transport(self.ctx, method, url, headers, body, 30) or {}
            status = int(row.get("status") or 0)
            # 传输层 ``ok`` 只表示链路可达；业务成功须为 2xx，403/404/400 走分类。
            success = bool(row.get("ok")) and 200 <= status < 300
            if success and not _retryable(status, row):
                return row
            last_row = row
            if not _retryable(status, row):
                break
            delay = self._backoff(attempt, row)
            if delay > 0:
                self.ctx.api.call("clock.sleep", {"seconds": delay}, caller=None)
        code = _classify(last_row.get("status"), last_row)
        return {"ok": False, "status": last_row.get("status") or 0,
                "code": code, "headers": last_row.get("headers") or {},
                "body": last_row.get("body") or b"", "text": last_row.get("text") or ""}

    def _request(self, method, key="", query=None, body=b"", headers=None,
                 sign=True):
        safe = _guard.sanitize_key(key) if key else ""
        if key and safe is None:
            return {"ok": False, "code": "invalid_key", "status": 0}
        url = self._url(safe, query or {})
        body = bytes(body or b"")
        base_headers = {}
        if body:
            base_headers["Content-Type"] = "application/octet-stream"
        base_headers.update(headers or {})
        if sign:
            base_headers = sign_request(self.ctx, method, url, base_headers, body,
                                        self.region, self.access_key, self.secret_key)
        return self._gate.run(self.ctx, lambda: self._send_with_retry(method, url,
                                                                      base_headers, body))

    def _url(self, safe_key, query):
        parts = [self.bucket]
        if safe_key:
            parts.append(safe_key)
        url = self.endpoint + "/" + "/".join(p for p in parts if p)
        if query:
            url += "?" + _canonical_query(list(query.items()))
        return url

    # ------------------------------------------------------------ 校验和工具

    def _checksum_header(self, headers):
        raw = (headers or {}).get("x-amz-checksum-sha256")
        if not raw:
            return ""
        row = self.ctx.api.call("codec.base64_decode_bytes", {"text": raw},
                                caller=None)
        data = row.get("data") or b""
        return bytes(data).hex()

    @staticmethod
    def _digest_of(ctx, data):
        return _sha256_hex(ctx, data)

    # ------------------------------------------------------------ 对象操作

    def test_connection(self):
        row = self._request("GET", "", query={"list-type": "2", "max-keys": "1"})
        if row.get("ok"):
            return {"ok": True, "detail": "s3-list-ok"}
        return {"ok": False, "code": row.get("code") or "provider_error",
                "detail": "s3-probe-failed"}

    def head(self, key):
        row = self._request("HEAD", key)
        if not row.get("ok"):
            return {"ok": False, "code": row.get("code"), "status": row.get("status")}
        headers = row.get("headers") or {}
        length = headers.get("content-length") or ""
        size = int(length) if str(length).isdigit() else None
        return {"ok": True, "etag": headers.get("etag"), "size": size,
                "checksum": self._checksum_header(headers),
                "content_type": headers.get("content-type")}

    def get(self, key):
        row = self._request("GET", key)
        if not row.get("ok"):
            return {"ok": False, "code": row.get("code"), "status": row.get("status")}
        data = row.get("body")
        if data is None:
            data = (row.get("text") or "").encode("utf-8")
        data = bytes(data)
        digest = self._digest_of(self.ctx, data)
        remote_checksum = self._checksum_header(row.get("headers") or {})
        if remote_checksum and remote_checksum != digest:
            return {"ok": False, "code": "checksum_mismatch", "status": 200,
                    "digest": digest, "remote_checksum": remote_checksum}
        return {"ok": True, "data": data, "digest": digest, "size": len(data)}

    def delete(self, key):
        row = self._request("DELETE", key)
        if row.get("ok") or row.get("code") == "not_found":
            return {"ok": True}
        return {"ok": False, "code": row.get("code"), "status": row.get("status")}

    def list_keys(self, prefix=""):
        rows = []
        token = ""
        seen = set()
        for _ in range(100):
            query = {"list-type": "2", "prefix": prefix or "", "max-keys": _LIST_PAGE}
            if token:
                query["continuation-token"] = token
            row = self._request("GET", "", query=query)
            if not row.get("ok"):
                break
            parsed = _parse_list_xml(row.get("body") or row.get("text") or "")
            for item in parsed["items"]:
                if item["key"] not in seen:
                    seen.add(item["key"])
                    rows.append(item)
            if parsed["is_truncated"] and parsed["next_token"]:
                token = parsed["next_token"]
            else:
                break
        return rows

    # ------------------------------------------------------------ 分片上传

    def _plan_parts(self, size):
        """按固定边界切分 ``(offset, length)`` 分片；返回分片规划，不读入正文。"""
        if size <= self.multipart_threshold:
            return [(0, size)]
        part_size = min(max(self.part_min_size, self.multipart_threshold),
                        self.part_max_bytes)
        parts = []
        offset = 0
        while offset < size:
            end = min(offset + part_size, size)
            parts.append((offset, end - offset))
            offset = end
        # 末片小于最小分片阈值时并入前一片（S3 除末片外分片不得小于下限）。
        if len(parts) > 1 and parts[-1][1] < self.part_min_size:
            prev = parts[-2]
            parts[-2] = (prev[0], prev[1] + parts[-1][1])
            parts.pop()
        return parts

    def _read_part(self, source, offset, length):
        """从可回卷源流读一个分片；单分片驻留 ≤ part_max_bytes。"""
        source.seek(offset)
        chunks = []
        remaining = length
        while remaining > 0:
            chunk = source.read(min(remaining, self.part_max_bytes))
            if not chunk:
                break
            chunks.append(bytes(chunk))
            remaining -= len(chunk)
        return b"".join(chunks)

    def _stream_digest(self, source, size):
        """整对象 sha256：分块流过本地增量哈希，不保留整对象。"""
        source.seek(0)
        hasher = hashlib.sha256()
        remaining = size
        while remaining > 0:
            chunk = source.read(min(remaining, self.part_max_bytes))
            if not chunk:
                break
            hasher.update(bytes(chunk))
            remaining -= len(chunk)
        return hasher.hexdigest()

    def put(self, key, data, resume=None):
        """字节对象上传；兼容既有签名。大对象请走 :meth:`put_stream`。"""
        data = bytes(data or b"")
        _guard.check_body_size(data, self.max_body)
        return self.put_stream(key, io.BytesIO(data), len(data), resume=resume)

    def put_stream(self, key, source, size, resume=None):
        """流式上传：分片按固定边界切分，单分片驻留 ≤ ``part_max_bytes``（默认 8MiB）。

        ``source`` 须支持 ``seek(offset)`` 与 ``read(n)``；``size`` 为对象总字节数。
        整对象摘要在分片流过时增量计算，续跑跳过已完成分片后补一轮分块全量哈希。
        """
        size = int(size or 0)
        if self.max_body > 0 and size > self.max_body:
            raise _guard.GuardError("body_too_large",
                                    "body exceeds %d bytes" % self.max_body)
        parts = self._plan_parts(size)
        if len(parts) == 1:
            return self._put_single_stream(key, source, size)
        return self._put_multipart(key, source, size, parts, resume or {})

    def _put_single_stream(self, key, source, size):
        source.seek(0)
        data = source.read(size)
        digest = self._digest_of(self.ctx, data)
        checksum = self.ctx.api.call(
            "codec.base64_encode", {"text": bytes.fromhex(digest)},
            caller=None).get("text")
        row = self._request("PUT", key, body=data,
                            headers={"x-amz-checksum-sha256": checksum})
        if not row.get("ok"):
            return {"ok": False, "code": row.get("code"), "offset": 0,
                    "status": row.get("status")}
        return {"ok": True, "size": len(data), "offset": len(data),
                "digest": digest, "upload_id": "", "parts": {}}

    def _init_multipart(self, key):
        body = (
            "<InitiateMultipartUpload xmlns=\"http://s3.amazonaws.com/doc/2006-03-01/\">"
            "<Bucket>%s</Bucket><Key>%s</Key></InitiateMultipartUpload>"
            % (_xml_escape(self.bucket), _xml_escape(key)))
        row = self._request("POST", key, query={"uploads": ""}, body=body.encode("utf-8"))
        if not row.get("ok"):
            return None, row
        upload_id = _parse_upload_id(row.get("body") or row.get("text") or "")
        if not upload_id:
            return None, {"ok": False, "code": "multipart_error", "status": row.get("status")}
        return upload_id, row

    def _put_multipart(self, key, source, size, parts, resume):
        upload_id = str(resume.get("upload_id") or "")
        done = {str(n): etag for n, etag in (resume.get("parts") or {}).items()}
        if not upload_id:
            upload_id, row = self._init_multipart(key)
            if not upload_id:
                return {"ok": False, "code": row.get("code") or "multipart_error",
                        "offset": 0}

        etags = dict(done)
        running = hashlib.sha256()
        skipped = False
        for index, (offset, length) in enumerate(parts, start=1):
            number = str(index)
            if number in etags:
                # 续跑跳过已完成分片；其字节不在增量哈希内，收尾补一轮分块全量哈希。
                skipped = True
                continue
            part = self._read_part(source, offset, length)
            row = self._request(
                "PUT", key,
                query={"partNumber": number, "uploadId": upload_id}, body=part)
            if not row.get("ok"):
                return {"ok": False, "code": row.get("code"),
                        "offset": offset, "upload_id": upload_id, "parts": etags}
            etag = (row.get("headers") or {}).get("etag") or ("etag-%d" % index)
            etags[number] = etag
            running.update(part)

        complete_body = self._complete_xml(etags)
        row = self._request("POST", key, query={"uploadId": upload_id},
                            body=complete_body.encode("utf-8"))
        if not row.get("ok"):
            return {"ok": False, "code": row.get("code") or "multipart_error",
                    "offset": size, "upload_id": upload_id, "parts": etags}

        digest = self._stream_digest(source, size) if skipped else running.hexdigest()
        return {"ok": True, "size": size, "offset": size, "digest": digest,
                "upload_id": upload_id, "parts": etags}

    @staticmethod
    def _complete_xml(etags):
        parts = []
        for number in sorted(etags, key=lambda n: int(n)):
            parts.append(
                "<Part><PartNumber>%s</PartNumber><ETag>%s</ETag></Part>"
                % (number, _xml_escape(etags[number])))
        return ("<CompleteMultipartUpload xmlns=\"http://s3.amazonaws.com/doc/2006-03-01/\">"
                + "".join(parts) + "</CompleteMultipartUpload>")


# ---------------------------------------------------------------- XML 解析

def _local_tag(tag):
    return tag.split("}", 1)[-1]


def _child_text(element, name):
    for child in element:
        if _local_tag(child.tag) == name:
            return (child.text or "").strip()
    return ""


def _parse_upload_id(raw):
    text = raw.decode("utf-8", "replace") if isinstance(raw, (bytes, bytearray)) else str(raw or "")
    try:
        root = ElementTree.fromstring(text)
    except ElementTree.ParseError:
        return ""
    return _child_text(root, "UploadId")


def _parse_list_xml(raw):
    """解析 ListObjectsV2 XML；返回 ``{items, is_truncated, next_token}``。"""
    text = raw.decode("utf-8", "replace") if isinstance(raw, (bytes, bytearray)) else str(raw or "")
    items, is_truncated, next_token = [], False, ""
    try:
        root = ElementTree.fromstring(text)
    except ElementTree.ParseError:
        return {"items": items, "is_truncated": is_truncated, "next_token": next_token}

    contents = [c for c in root if _local_tag(c.tag) == "Contents"]
    if not contents:
        # 兜底：扁平结构（Key/Size 直接挂在根下）。
        contents = [root]
    for node in contents:
        key = _child_text(node, "Key")
        if not key:
            continue
        size_text = _child_text(node, "Size")
        size = int(size_text) if size_text.isdigit() else 0
        etag = _child_text(node, "ETag").strip('"')
        checksum_b64 = _child_text(node, "ChecksumSHA256")
        digest = etag
        if checksum_b64:
            digest = "checksum:" + checksum_b64
        items.append({"key": key, "digest": digest, "size": size, "etag": etag})
    truncated = _child_text(root, "IsTruncated").lower() == "true"
    token = _child_text(root, "NextContinuationToken")
    return {"items": items, "is_truncated": truncated, "next_token": token}
