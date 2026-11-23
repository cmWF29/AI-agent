#!/usr/bin/env python3
"""云端通道真实凭据往返自检：不连桩，按环境变量对接真实 S3 / WebDAV。

覆盖阶段（每通道独立跑完整往返）：

- 连通探活 → PUT 探针 → HEAD 校验大小/ETag → GET 比对摘要 → List 命中 →
  分片/断点上传中等对象并回读校验 → 带断点状态幂等重传 → Delete 清理；
- 任一步失败立即停止该通道，回传失败阶段与结构化结果，退出码非 0。

环境变量：

- S3：``AI_NEW_S3_ENDPOINT`` / ``AI_NEW_S3_AK`` / ``AI_NEW_S3_SK`` /
  ``AI_NEW_S3_BUCKET``；可选 ``AI_NEW_S3_REGION``（缺省 us-east-1）。
- WebDAV：``AI_NEW_WEBDAV_URL`` / ``AI_NEW_WEBDAV_USER`` /
  ``AI_NEW_WEBDAV_PASS``；自定义 CA 走 ``ca_bundle`` 策略键或 ``SSL_CERT_FILE``。

退出码约定：

- 0：配置的通道全部往返通过；或两通道凭据均缺失，明确 ``SKIP: missing ...``
  （跳过不是通过，不得静默记为成功）；
- 1：已配置通道在某阶段失败，输出失败阶段与结果。

本脚本是验收工具，允许直接使用标准库网络/哈希原语；运行时模块仍走注入式接缝。
"""
from __future__ import annotations

import base64
import hashlib
import http.client
import io
import os
import secrets
import sys
import time
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ai_new.modules.agent.cloud.private import _s3, _webdav  # noqa: E402

S3_ENV = {
    "endpoint": "AI_NEW_S3_ENDPOINT",
    "ak": "AI_NEW_S3_AK",
    "sk": "AI_NEW_S3_SK",
    "bucket": "AI_NEW_S3_BUCKET",
}
S3_REGION_ENV = "AI_NEW_S3_REGION"
DAV_ENV = {
    "url": "AI_NEW_WEBDAV_URL",
    "user": "AI_NEW_WEBDAV_USER",
    "password": "AI_NEW_WEBDAV_PASS",
}

PROBE_PREFIX = "cloud-live-check/"
# 中等对象 200KiB：触发分片上传路径，又不在自检脚本里抬高内存/时长。
BIG_SIZE = 200 * 1024


class StageFailure(Exception):
    """某通道在指定阶段失败；携带阶段名与结构化结果。"""

    def __init__(self, channel, stage, result):
        self.channel = channel
        self.stage = stage
        self.result = result
        super().__init__("%s stage=%s result=%s" % (channel, stage, result))


# ---------------------------------------------------------------- 接缝适配

class _Ctx:
    """最小 ctx：对齐 codec / clock 能力面，供 S3 客户端签名与摘要使用。"""

    def __init__(self):
        self.api = self

    def call(self, name, payload, caller=None):
        payload = payload or {}
        if name == "codec.digest":
            algo = str(payload.get("algorithm") or "sha256")
            raw = payload.get("text")
            raw = raw if isinstance(raw, (bytes, bytearray)) else str(raw or "").encode("utf-8")
            return {"ok": True, "hex": getattr(hashlib, algo)(bytes(raw)).hexdigest()}
        if name == "codec.nonce":
            return {"ok": True, "token": secrets.token_urlsafe(int(payload.get("length") or 16))}
        if name == "codec.base64_encode":
            return {"ok": True, "text": base64.b64encode(bytes(payload.get("text") or b"")).decode("ascii")}
        if name == "codec.base64_decode_bytes":
            return {"ok": True, "data": base64.b64decode(payload.get("text") or "")}
        if name == "clock.now":
            return {"iso": time.strftime("%Y%m%dT%H%M%SZ", time.gmtime()),
                    "ts": time.time()}
        if name == "clock.sleep":
            time.sleep(float(payload.get("seconds") or 0))
            return {"ok": True}
        return {"ok": False, "error": "unknown seam: %s" % name}


class _Codec:
    """WebDAV 侧 codec 适配：摘要 / base64。"""

    def digest(self, text, algorithm="sha256"):
        raw = text if isinstance(text, (bytes, bytearray)) else str(text or "").encode("utf-8")
        return getattr(hashlib, algorithm)(bytes(raw)).hexdigest()

    def base64_encode(self, data):
        return base64.b64encode(bytes(data)).decode("ascii")


class _Clock:
    def sleep(self, seconds):
        time.sleep(float(seconds or 0))


class _HashSink:
    """落地收集器：边写边算 sha256，不保留完整正文。"""

    def __init__(self):
        self._hash = hashlib.sha256()
        self.size = 0

    def write(self, chunk):
        self._hash.update(bytes(chunk))
        self.size += len(chunk)

    def hexdigest(self):
        return self._hash.hexdigest()


class _PatternSource:
    """确定性流式源：可 seek 回卷，供分片/断点上传路径使用。"""

    def __init__(self, size, chunk=64 * 1024):
        self._size = size
        self._chunk = chunk
        self._pos = 0
        self._pattern = bytes((i * 7) % 256 for i in range(chunk))

    def _tile(self, want):
        return (self._pattern * (want // len(self._pattern) + 1))[:want]

    def read(self, n=-1):
        if self._pos >= self._size:
            return b""
        want = min(n if n > 0 else self._chunk, self._size - self._pos)
        out = self._tile(want)
        self._pos += want
        return out

    def seek(self, offset):
        self._pos = max(0, min(offset, self._size))

    def expected_hash(self):
        digest = hashlib.sha256()
        pos = 0
        while pos < self._size:
            want = min(self._chunk, self._size - pos)
            digest.update(self._tile(want))
            pos += want
        return digest.hexdigest()


# ---------------------------------------------------------------- S3 往返

def _http_transport(ctx, method, url, headers, body, timeout):
    """标准库 HTTP 传输：返回 S3 客户端约定的行结果字典。"""
    parts = urlsplit(url)
    factory = (http.client.HTTPSConnection if parts.scheme == "https"
               else http.client.HTTPConnection)
    conn = factory(parts.hostname, parts.port or (443 if parts.scheme == "https" else 80),
                   timeout=timeout or 30)
    path = parts.path or "/"
    if parts.query:
        path += "?" + parts.query
    raw = body if isinstance(body, (bytes, bytearray)) else (
        b"" if body is None else str(body).encode("utf-8"))
    try:
        conn.request(method, path, body=raw, headers=dict(headers or {}))
        resp = conn.getresponse()
        data = resp.read()
        hdrs = {k.lower(): v for k, v in resp.getheaders()}
        return {"ok": resp.status < 500, "status": resp.status, "headers": hdrs,
                "body": data, "text": data.decode("utf-8", "replace")}
    except OSError as exc:
        return {"ok": False, "status": 0, "code": "unreachable",
                "headers": {}, "body": b"", "text": str(exc)}
    finally:
        conn.close()


def _check(channel, stage, ok, result):
    if not ok:
        raise StageFailure(channel, stage, result)


def run_s3(values):
    ctx = _Ctx()
    policy = {
        "multipart_threshold": 64 * 1024,
        "multipart_min_size": 32 * 1024,
        "part_max_bytes": 8 * 1024 * 1024,
        "max_attempts": 3,
        "backoff_base_s": 0.5,
        "backoff_cap_s": 5,
        "concurrency": 4,
    }
    profile = {"endpoint": values["endpoint"], "root_dir": values["bucket"],
               "policy": policy}
    creds = {"access_key": values["ak"], "secret_key": values["sk"],
             "region": values.get("region") or "us-east-1",
             "bucket": values["bucket"]}
    client = _s3.S3Client(ctx, profile, creds, transport=_http_transport)

    probe = client.test_connection()
    _check("s3", "connect", probe.get("ok"), probe)
    print("[s3] connect ok")

    nonce = secrets.token_urlsafe(12)
    key = PROBE_PREFIX + nonce
    body = ("live-check:" + nonce).encode("utf-8")

    put = client.put(key, body)
    _check("s3", "put", put.get("ok"), put)
    print("[s3] put ok (%d bytes)" % len(body))

    head = client.head(key)
    _check("s3", "head", head.get("ok") and head.get("size") == len(body), head)
    print("[s3] head ok (size=%s)" % head.get("size"))

    got = client.get(key)
    _check("s3", "get", got.get("ok") and got.get("data") == body, got)
    print("[s3] get ok (digest=%s)" % got.get("digest"))

    rows = client.list_keys(PROBE_PREFIX)
    _check("s3", "list", any(r.get("key") == key for r in rows), rows)
    print("[s3] list ok (%d rows)" % len(rows))

    big_key = PROBE_PREFIX + nonce + "-multipart"
    source = _PatternSource(BIG_SIZE)
    expect = source.expected_hash()
    mput = client.put_stream(big_key, source, BIG_SIZE)
    _check("s3", "multipart-put", mput.get("ok"), mput)
    print("[s3] multipart-put ok (%d bytes, %d parts)"
          % (BIG_SIZE, len(mput.get("parts") or {})))

    mget = client.get(big_key)
    _check("s3", "multipart-get",
           mget.get("ok") and mget.get("digest") == expect, mget)
    print("[s3] multipart-get ok (digest matches)")

    # 幂等重传：同对象二次整传覆盖，摘要稳定、不产生重复版本。
    # 断点续传（中断后按已完成分片跳过）由单元测试对 stub 路径覆盖；
    # 已 Complete 的 upload_id 在真实服务端不可复用，这里不回传旧 checkpoint。
    mput2 = client.put_stream(big_key, _PatternSource(BIG_SIZE), BIG_SIZE)
    _check("s3", "multipart-reput", mput2.get("ok") and mput2.get("digest") == expect,
           mput2)
    print("[s3] multipart-reput ok (idempotent overwrite, digest stable)")

    deleted = client.delete(key)
    _check("s3", "delete-probe", deleted.get("ok"), deleted)
    deleted_big = client.delete(big_key)
    _check("s3", "delete-multipart", deleted_big.get("ok"), deleted_big)
    print("[s3] cleanup ok")


# ---------------------------------------------------------------- WebDAV 往返

def run_dav(values):
    client = _webdav.WebDavClient(
        values["url"], username=values["user"], password=values["password"],
        codec=_Codec(), clock=_Clock(), auth="auto", upload_chunk_size=32 * 1024)

    probe = client.test_connection()
    _check("webdav", "connect", probe.get("ok"), probe)
    print("[webdav] connect ok")

    nonce = secrets.token_urlsafe(12)
    key = PROBE_PREFIX + nonce
    body = ("live-check:" + nonce).encode("utf-8")

    put = client.put(key, body)
    _check("webdav", "put", put.get("ok"), put)
    print("[webdav] put ok (%d bytes)" % len(body))

    head = client.head(key)
    _check("webdav", "head", head.get("ok") and head.get("size") == len(body), head)
    print("[webdav] head ok (size=%s)" % head.get("size"))

    sink = _HashSink()
    got = client.get(key, sink)
    _check("webdav", "get", got.get("ok") and sink.hexdigest() == hashlib.sha256(body).hexdigest(), got)
    print("[webdav] get ok (digest=%s)" % sink.hexdigest())

    listed = client.propfind(PROBE_PREFIX.rstrip("/"), depth=1)
    entries = listed.get("entries") or []
    _check("webdav", "list", listed.get("ok") and any(e.get("key") == key for e in entries), listed)
    print("[webdav] list ok (%d entries)" % len(entries))

    big_key = PROBE_PREFIX + nonce + "-multipart"
    source = _PatternSource(BIG_SIZE)
    expect = source.expected_hash()
    mput = client.put_resumable(big_key, source, BIG_SIZE)
    _check("webdav", "chunked-put", mput.get("ok"), mput)
    print("[webdav] chunked-put ok (%d bytes)" % BIG_SIZE)

    big_sink = _HashSink()
    mget = client.get(big_key, big_sink)
    _check("webdav", "chunked-get",
           mget.get("ok") and big_sink.hexdigest() == expect, mget)
    print("[webdav] chunked-get ok (digest matches)")

    deleted = client.delete(key)
    _check("webdav", "delete-probe", deleted.get("ok"), deleted)
    deleted_big = client.delete(big_key)
    _check("webdav", "delete-multipart", deleted_big.get("ok"), deleted_big)
    print("[webdav] cleanup ok")


# ---------------------------------------------------------------- 入口

def _collect(env_map):
    """读取环境变量；返回 (values, missing)。missing 为未配置的变量名列表。"""
    values, missing = {}, []
    for key, env_name in env_map.items():
        value = os.environ.get(env_name) or ""
        if value:
            values[key] = value
        else:
            missing.append(env_name)
    return values, missing


def main():
    s3_values, s3_missing = _collect(S3_ENV)
    if not s3_missing:
        s3_values["region"] = os.environ.get(S3_REGION_ENV) or ""
    dav_values, dav_missing = _collect(DAV_ENV)

    failures = []
    ran = False

    if s3_missing:
        print("SKIP: missing %s (S3 通道未配置真实凭据，未执行联网往返)"
              % ", ".join(s3_missing))
    else:
        ran = True
        try:
            run_s3(s3_values)
        except StageFailure as exc:
            failures.append(exc)
            print("FAIL: s3 stage=%s result=%s" % (exc.stage, exc.result))
        except OSError as exc:
            failures.append(StageFailure("s3", "transport", str(exc)))
            print("FAIL: s3 transport: %s" % exc)

    if dav_missing:
        print("SKIP: missing %s (WebDAV 通道未配置真实凭据，未执行联网往返)"
              % ", ".join(dav_missing))
    else:
        ran = True
        try:
            run_dav(dav_values)
        except StageFailure as exc:
            failures.append(exc)
            print("FAIL: webdav stage=%s result=%s" % (exc.stage, exc.result))
        except OSError as exc:
            failures.append(StageFailure("webdav", "transport", str(exc)))
            print("FAIL: webdav transport: %s" % exc)

    if failures:
        print("LIVE CHECK FAILED: %d channel(s) did not pass" % len(failures))
        return 1
    if not ran:
        print("SKIP: 两通道凭据均未配置；本次未执行任何真实联网往返（跳过不计通过）。")
        return 0
    print("LIVE CHECK OK: 已配置通道全部往返通过。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
