#!/usr/bin/env python3
"""本地 S3 兼容 stub：真校验 SigV4 签名，供 cloud S3 通道验收（不连真实云）。

用途与边界：

- 独立实现一套 Signature Version 4 校验（与模块内 ``_s3`` 互为独立实现）：
  两边规范请求串 / 签名链一致才能通过；任一侧编码、排序、签名链出错即回 403；
- 对象面：``PUT`` / ``GET`` / ``HEAD`` / ``DELETE``；``ListObjectsV2`` 分页
  （``list-type=2`` + continuation token，页大小可配，便于翻页用例）；
- 分片面：``?uploads`` 初始化、``UploadPart``、``CompleteMultipartUpload``；
  已完成分片留存，重跑跳过；
- 校验和：记录 ``x-amz-checksum-sha256``，``HEAD`` / ``GET`` / List 回传；
- 故障注入：``fail_429`` 次 429（可带 ``Retry-After``），之后恢复 2xx，供退避重试用例。

本文件是验收脚本，不进运行时模块树；允许直接使用标准库网络/哈希原语。
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import re
import threading
import xml.etree.ElementTree as ElementTree
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

DEFAULT_AK = "stub-access-key"
DEFAULT_SK = "example-secret-key-0123456789abcdef"

_UNRESERVED = frozenset(
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz01234567-_.~")
_AUTH_RE = {
    "cred": re.compile(r"Credential=([^,]+)"),
    "signed": re.compile(r"SignedHeaders=([^,]+)"),
    "sig": re.compile(r"Signature=([a-f0-9]+)"),
}


def _pct_encode(text):
    out = []
    for ch in str(text):
        if ch in _UNRESERVED:
            out.append(ch)
        else:
            for byte in ch.encode("utf-8"):
                out.append("%%%02X" % byte)
    return "".join(out)


def _canonical_query(pairs):
    encoded = sorted((_pct_encode(n), _pct_encode(v)) for n, v in pairs)
    return "&".join("%s=%s" % (n, v) for n, v in encoded)


def _sha256_hex(raw):
    if isinstance(raw, str):
        raw = raw.encode("utf-8")
    return hashlib.sha256(bytes(raw)).hexdigest()


def verify_signature(handler, body, ak, sk, region, service="s3"):
    """独立校验 SigV4；返回 ``(ok, reason)``。对不上签名/规范串即 ``ok=False``。"""
    headers = {k.lower(): v for k, v in handler.headers.items()}
    auth = headers.get("authorization", "")
    cred = _AUTH_RE["cred"].search(auth)
    signed = _AUTH_RE["signed"].search(auth)
    sig = _AUTH_RE["sig"].search(auth)
    if not (cred and signed and sig):
        return False, "malformed_authorization"

    credential = cred.group(1)
    scope_parts = credential.split("/")
    if len(scope_parts) != 5:
        return False, "bad_scope"
    ak_id, date_stamp, scope_region, scope_service, request = scope_parts
    if ak_id != ak or scope_region != region or scope_service != service:
        return False, "scope_mismatch"
    if request != "aws4_request":
        return False, "bad_request_tag"

    amz_date = headers.get("x-amz-date", "")
    if amz_date[:8] != date_stamp:
        return False, "date_mismatch"

    payload_hash = headers.get("x-amz-content-sha256", "")
    if _sha256_hex(body) != payload_hash:
        return False, "payload_hash_mismatch"

    signed_headers = [n.lower() for n in signed.group(1).split(";")]
    missing = [n for n in signed_headers if n not in headers]
    if missing:
        return False, "missing_signed_header"
    canonical_headers = "".join(
        "%s:%s\n" % (n, headers[n].strip()) for n in sorted(signed_headers))
    signed_list = ";".join(sorted(signed_headers))

    parsed = urlparse(handler.path)
    canonical_uri = "/" + "/".join(_pct_encode(seg) for seg in parsed.path.split("/") if seg)
    pairs = [(k, v[0]) for k, v in
             parse_qs(parsed.query, keep_blank_values=True).items()]
    canonical_query = _canonical_query(pairs)

    canonical_request = "\n".join([
        handler.command, canonical_uri, canonical_query,
        canonical_headers, signed_list, payload_hash])
    scope = "%s/%s/%s/%s" % (date_stamp, region, service, "aws4_request")
    string_to_sign = "\n".join([
        "AWS4-HMAC-SHA256", amz_date, scope, _sha256_hex(canonical_request)])

    def _hmac(key, msg):
        return hmac.new(key, msg.encode("utf-8"), hashlib.sha256).digest()

    k = _hmac(("AWS4" + sk).encode("utf-8"), date_stamp)
    k = _hmac(k, region)
    k = _hmac(k, service)
    k = _hmac(k, "aws4_request")
    expected = hmac.new(k, string_to_sign.encode("utf-8"), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, sig.group(1)):
        return False, "signature_mismatch"
    return True, "ok"


class StubStore:
    """内存对象表 + 分片上传表 + 故障计数；线程安全。"""

    def __init__(self, region="us-east-1", page_size=3):
        self.region = region
        self.page_size = int(page_size)
        self.lock = threading.Lock()
        self.objects = {}
        self.uploads = {}
        self.fail_429 = 0
        self.retry_after = "0"
        self.requests = []

    def record(self, method, path, status):
        with self.lock:
            self.requests.append({"method": method, "path": path, "status": status})


class _Handler(BaseHTTPRequestHandler):
    server_version = "s3-stub/1.0"

    def log_message(self, *args):
        pass

    # ------------------------------------------------------------ 基础响应

    def _store(self):
        return self.server.s3_store

    def _read_body(self):
        length = int(self.headers.get("Content-Length") or 0)
        return self.rfile.read(length) if length else b""

    def _send_xml(self, status, xml):
        data = xml.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/xml")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _send_object(self, status, obj, with_body):
        self.send_response(status)
        self.send_header("ETag", '"%s"' % obj["etag"])
        self.send_header("Content-Length", str(obj["size"]))
        checksum_b64 = base64.b64encode(bytes.fromhex(obj["checksum"])).decode("ascii")
        self.send_header("x-amz-checksum-sha256", checksum_b64)
        self.send_header("Content-Type", "application/octet-stream")
        if with_body:
            self.send_header("Content-Length", str(obj["size"]))
            self.end_headers()
            self.wfile.write(obj["data"])
        else:
            self.end_headers()

    def _fault_or_verify(self, body):
        """先故障注入（429），再签名校验；返回 True 表示已应答。"""
        store = self._store()
        if store.fail_429 > 0:
            store.fail_429 -= 1
            self.send_response(429)
            self.send_header("Retry-After", str(store.retry_after))
            self.send_header("Content-Length", "0")
            self.end_headers()
            store.record(self.command, self.path, 429)
            return True
        ok, reason = verify_signature(self, body, DEFAULT_AK, DEFAULT_SK, store.region)
        if not ok:
            self._send_xml(403, "<Error><Code>SignatureDoesNotMatch</Code>"
                                "<Message>%s</Message></Error>" % reason)
            store.record(self.command, self.path, 403)
            return True
        return False

    # ------------------------------------------------------------ 路由

    def _route(self):
        parsed = urlparse(self.path)
        segs = [s for s in parsed.path.split("/") if s]
        query = {k: v[0] for k, v in
                 parse_qs(parsed.query, keep_blank_values=True).items()}
        return segs, query

    def do_GET(self):
        body = self._read_body()
        if self._fault_or_verify(body):
            return
        segs, query = self._route()
        store = self._store()
        if "list-type" in query:
            self._handle_list(store, query)
            return
        obj = self._object(store, segs)
        if obj is None:
            store.record("GET", self.path, 404)
            self._send_xml(404, "<Error><Code>NoSuchKey</Code></Error>")
            return
        store.record("GET", self.path, 200)
        self._send_object(200, obj, with_body=True)

    def do_HEAD(self):
        body = self._read_body()
        if self._fault_or_verify(body):
            return
        segs, _ = self._route()
        store = self._store()
        obj = self._object(store, segs)
        if obj is None:
            store.record("HEAD", self.path, 404)
            self.send_response(404)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        store.record("HEAD", self.path, 200)
        self._send_object(200, obj, with_body=False)

    def do_PUT(self):
        body = self._read_body()
        if self._fault_or_verify(body):
            return
        segs, query = self._route()
        store = self._store()
        upload_id = query.get("uploadId")
        if "partNumber" in query and upload_id:
            self._handle_upload_part(store, segs, query, body)
        else:
            self._handle_put(store, segs, body)

    def do_DELETE(self):
        body = self._read_body()
        if self._fault_or_verify(body):
            return
        segs, _ = self._route()
        store = self._store()
        key = "/".join(segs[1:]) if len(segs) >= 2 else ""
        if key:
            store.objects.pop(key, None)
        store.record("DELETE", self.path, 204)
        self.send_response(204)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_POST(self):
        body = self._read_body()
        if self._fault_or_verify(body):
            return
        segs, query = self._route()
        store = self._store()
        if "uploads" in query:
            self._handle_init(store, segs)
        elif "uploadId" in query:
            self._handle_complete(store, segs, query, body)
        else:
            self._send_xml(400, "<Error><Code>BadRequest</Code></Error>")

    # ------------------------------------------------------------ 对象操作

    @staticmethod
    def _object(store, segs):
        if len(segs) < 2:
            return None
        key = "/".join(segs[1:])
        return store.objects.get(key)

    def _handle_put(self, store, segs, body):
        if len(segs) < 2:
            self._send_xml(400, "<Error><Code>BadRequest</Code></Error>")
            return
        key = "/".join(segs[1:])
        checksum = _sha256_hex(body)
        provided = self.headers.get("x-amz-checksum-sha256")
        if provided:
            try:
                checksum = base64.b64decode(provided).hex()
            except ValueError:
                pass
        etag = _sha256_hex(body)[:32]
        store.objects[key] = {"data": body, "checksum": checksum, "etag": etag,
                              "size": len(body)}
        store.record("PUT", self.path, 200)
        self.send_response(200)
        self.send_header("ETag", '"%s"' % etag)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _handle_list(self, store, query):
        prefix = query.get("prefix", "")
        token = query.get("continuation-token", "")
        with store.lock:
            keys = sorted(k for k in store.objects if k.startswith(prefix))
            offset = int(token or 0)
            page = keys[offset:offset + store.page_size]
            truncated = offset + store.page_size < len(keys)
            next_token = str(offset + store.page_size) if truncated else ""
            lines = ["<ListBucketResult xmlns=\"http://s3.amazonaws.com/doc/2006-03-01/\">"]
            for key in page:
                obj = store.objects[key]
                checksum_b64 = base64.b64encode(
                    bytes.fromhex(obj["checksum"])).decode("ascii")
                lines.append(
                    "<Contents><Key>%s</Key><Size>%d</Size><ETag>\"%s\"</ETag>"
                    "<ChecksumSHA256>%s</ChecksumSHA256></Contents>"
                    % (key, obj["size"], obj["etag"], checksum_b64))
            lines.append("<IsTruncated>%s</IsTruncated>" %
                         ("true" if truncated else "false"))
            if next_token:
                lines.append("<NextContinuationToken>%s</NextContinuationToken>" % next_token)
            lines.append("</ListBucketResult>")
        store.record("GET", self.path, 200)
        self._send_xml(200, "".join(lines))

    # ------------------------------------------------------------ 分片上传

    def _handle_init(self, store, segs):
        key = "/".join(segs[1:]) if len(segs) >= 2 else "probe"
        upload_id = hashlib.sha256(
            (key + ":" + str(len(store.uploads))).encode("utf-8")).hexdigest()[:24]
        store.uploads[upload_id] = {"key": key, "parts": {}}
        store.record("POST", self.path, 200)
        self._send_xml(200, "<InitiateMultipartUploadResult "
                            "xmlns=\"http://s3.amazonaws.com/doc/2006-03-01/\">"
                            "<Bucket>%s</Bucket><Key>%s</Key><UploadId>%s</UploadId>"
                            "</InitiateMultipartUploadResult>"
                            % (segs[0] if segs else "bucket", key, upload_id))

    def _handle_upload_part(self, store, segs, query, body):
        upload_id = query["uploadId"]
        upload = store.uploads.get(upload_id)
        if upload is None:
            self._send_xml(404, "<Error><Code>NoSuchUpload</Code></Error>")
            store.record("PUT", self.path, 404)
            return
        number = int(query["partNumber"])
        etag = _sha256_hex(body)[:32]
        upload["parts"][number] = {"data": body, "etag": etag}
        store.record("PUT", self.path, 200)
        self.send_response(200)
        self.send_header("ETag", '"%s"' % etag)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _handle_complete(self, store, segs, query, body):
        upload_id = query["uploadId"]
        upload = store.uploads.get(upload_id)
        if upload is None:
            store.record("POST", self.path, 404)
            self._send_xml(404, "<Error><Code>NoSuchUpload</Code></Error>")
            return
        part_numbers = sorted(upload["parts"])
        try:
            root = ElementTree.fromstring(body.decode("utf-8", "replace"))
            declared = []
            for part in root.iter():
                if part.tag.split("}", 1)[-1] == "PartNumber":
                    declared.append(int(part.text.strip()))
            if declared:
                part_numbers = sorted(set(declared))
        except ElementTree.ParseError:
            pass
        missing = [n for n in part_numbers if n not in upload["parts"]]
        if missing:
            store.record("POST", self.path, 400)
            self._send_xml(400, "<Error><Code>InvalidPart</Code></Error>")
            return
        assembled = b"".join(upload["parts"][n]["data"] for n in part_numbers)
        checksum = _sha256_hex(assembled)
        etag = checksum[:32]
        store.objects[upload["key"]] = {
            "data": assembled, "checksum": checksum, "etag": etag,
            "size": len(assembled)}
        store.uploads.pop(upload_id, None)
        store.record("POST", self.path, 200)
        self._send_xml(200, "<CompleteMultipartUploadResult "
                            "xmlns=\"http://s3.amazonaws.com/doc/2006-03-01/\">"
                            "<ETag>\"%s\"</ETag></CompleteMultipartUploadResult>" % etag)


def make_server(host="127.0.0.1", port=0, ak=DEFAULT_AK, sk=DEFAULT_SK,
                region="us-east-1", page_size=3):
    """构造 stub HTTP 服务（未启动）；测试在后台线程 ``serve_forever``。"""
    store = StubStore(region=region, page_size=page_size)
    httpd = ThreadingHTTPServer((host, port), _Handler)
    httpd.s3_store = store
    return httpd


def main():
    ap = argparse.ArgumentParser(description="local S3-compatible stub for acceptance")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=0)
    ap.add_argument("--region", default="us-east-1")
    ap.add_argument("--page-size", type=int, default=3)
    args = ap.parse_args()
    httpd = make_server(host=args.host, port=args.port, region=args.region,
                        page_size=args.page_size)
    print("LISTEN %d" % httpd.server_address[1], flush=True)
    httpd.serve_forever()


if __name__ == "__main__":
    main()
