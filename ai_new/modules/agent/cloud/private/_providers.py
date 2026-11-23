"""Provider 适配层：统一连接/上传/下载/列目录/删除/校验接口与注册表。

真实通道（``_s3`` / ``_webdav``）按名字惰性装载：首次构造时才 import 对应模块；
模块缺失即回落到 ``_PendingProvider``（unsupported），装配期不因缺模块崩。
出站经各通道自身的注入式传输接缝（默认委托 ``net.request``）；不直连 socket/urllib。
"""
from __future__ import annotations

from . import _pure, _guard


class ProviderError(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


class BaseProvider:
    """提供方接口（鸭子类型）。所有方法收 ``ctx`` 与规范化后的 ``profile``。"""

    def test_connection(self, ctx, profile):
        raise NotImplementedError

    def list_keys(self, ctx, profile, prefix):
        raise NotImplementedError

    def put(self, ctx, profile, key, data, resume_from=0, upload_id=None):
        raise NotImplementedError

    def get(self, ctx, profile, key):
        raise NotImplementedError

    def delete(self, ctx, profile, key):
        raise NotImplementedError


class FakeProvider(BaseProvider):
    """内存桩：不连外网。可注入前 ``fail_times`` 次失败，或按键注入瞬态失败。"""

    def __init__(self):
        self.store = {}
        self.fail_times = 0
        self.fail_keys = {}
        self.attempts = 0
        self.calls = []

    def _transient(self):
        self.attempts += 1
        if self.attempts <= self.fail_times:
            return True
        return False

    def test_connection(self, ctx, profile):
        self.calls.append(("test", profile.get("endpoint")))
        return {"ok": True, "detail": "fake-ok"}

    def list_keys(self, ctx, profile, prefix):
        rows = []
        for key, item in self.store.items():
            if not prefix or key.startswith(prefix):
                rows.append({"key": key, "digest": item["digest"], "size": item["size"]})
        return rows

    def put(self, ctx, profile, key, data, resume_from=0, upload_id=None):
        self.calls.append(("put", key, len(data)))
        if self.fail_keys.get(key, 0) > 0:
            self.fail_keys[key] -= 1
            return {"ok": False, "code": "transient", "offset": resume_from}
        if self._transient():
            return {"ok": False, "code": "transient", "offset": resume_from}
        digest = ctx.api.call("codec.digest", {"text": data, "algorithm": "sha256"},
                              caller=None)
        self.store[key] = {"data": data, "digest": digest.get("hex"), "size": len(data)}
        return {"ok": True, "size": len(data), "offset": len(data), "upload_id": upload_id or ""}

    def get(self, ctx, profile, key):
        item = self.store.get(key)
        if item is None:
            return {"ok": False, "code": "not_found"}
        return {"ok": True, "data": item["data"], "digest": item["digest"],
                "size": item["size"]}

    def delete(self, ctx, profile, key):
        self.store.pop(key, None)
        return {"ok": True}


class HttpDirProvider(BaseProvider):
    """HTTP 目录 / WebDAV / 知识库 HTTP API 的通用 REST 适配。

    路径拼到 ``endpoint/root_dir/key``；读写走 net.request。Wiki 私有 API 的
    字段映射未接线（见 meta note），当前按通用对象语义落地。
    出站前复检协议/主机；跳转目标复检私网；响应体受体积上限约束。
    """

    def _url(self, profile, key=""):
        base = str(profile.get("endpoint") or "").rstrip("/")
        root = str(profile.get("root_dir") or "").strip("/")
        tail = (root + "/" + key) if root else key
        return base + "/" + tail

    def _max_body(self, profile):
        return int((profile.get("policy") or {}).get("max_body_bytes") or 0)

    def _guard_redirect(self, profile, row):
        location = (row or {}).get("location") or (row or {}).get("redirected_to")
        if location:
            check = _guard.validate_redirect(profile.get("endpoint") or "", location)
            if not check["ok"]:
                raise ProviderError(check["errors"][0], "redirect blocked")

    def test_connection(self, ctx, profile):
        row = ctx.api.call("net.request", {
            "method": "GET", "url": self._url(profile), "timeout": 10}, caller=None)
        self._guard_redirect(profile, row)
        ok = bool((row or {}).get("ok", True))
        return {"ok": ok, "detail": "http-probe"}

    def list_keys(self, ctx, profile, prefix):
        row = ctx.api.call("net.request", {
            "method": "GET", "url": self._url(profile, "?list=json"), "timeout": 10},
            caller=None)
        self._guard_redirect(profile, row)
        items = (row or {}).get("items") or []
        return [{"key": i.get("key"), "digest": i.get("digest"), "size": i.get("size", 0)}
                for i in items]

    def put(self, ctx, profile, key, data, resume_from=0, upload_id=None):
        _guard.check_body_size(data, self._max_body(profile))
        row = ctx.api.call("net.request", {
            "method": "PUT", "url": self._url(profile, key),
            "body": data, "timeout": 30}, caller=None)
        self._guard_redirect(profile, row)
        if not (row or {}).get("ok", True):
            return {"ok": False, "code": "provider_error", "offset": resume_from}
        digest = ctx.api.call("codec.digest", {"text": data, "algorithm": "sha256"},
                              caller=None)
        return {"ok": True, "size": len(data), "offset": len(data),
                "digest": digest.get("hex")}

    def get(self, ctx, profile, key):
        row = ctx.api.call("net.request", {
            "method": "GET", "url": self._url(profile, key), "timeout": 30}, caller=None)
        self._guard_redirect(profile, row)
        if not (row or {}).get("ok", True):
            return {"ok": False, "code": "provider_error"}
        data = (row or {}).get("body") or (row or {}).get("data") or b""
        _guard.check_body_size(data, self._max_body(profile))
        digest = ctx.api.call("codec.digest", {"text": data, "algorithm": "sha256"},
                              caller=None)
        return {"ok": True, "data": data, "digest": digest.get("hex"),
                "size": len(data)}

    def delete(self, ctx, profile, key):
        ctx.api.call("net.request", {
            "method": "DELETE", "url": self._url(profile, key), "timeout": 10}, caller=None)
        return {"ok": True}


class _PendingProvider(BaseProvider):
    """未接线提供方占位：接缝在位，真实通道/包装待改（见报告）。"""

    status_code = "adapter_pending"

    def __init__(self, status_code=None):
        if status_code:
            self.status_code = status_code

    def test_connection(self, ctx, profile):
        return {"ok": False, "code": self.status_code, "detail": "not-wired"}

    def list_keys(self, ctx, profile, prefix):
        return []

    def put(self, ctx, profile, key, data, resume_from=0, upload_id=None):
        return {"ok": False, "code": self.status_code, "offset": resume_from}

    def get(self, ctx, profile, key):
        return {"ok": False, "code": self.status_code}

    def delete(self, ctx, profile, key):
        return {"ok": False, "code": self.status_code}


class RsyncProvider(_PendingProvider):
    """rsync/ssh 自建服务器：需 exec 能力包装命令；当前未接线。"""

    status_code = "exec_wrapper_pending"


# ---------------------------------------------------------------- 惰性通道适配器

class _ByteSink:
    """下载收集器：实现 ``write(bytes)`` 接缝，供 WebDAV 客户端落汇总。"""

    def __init__(self):
        self.data = b""

    def write(self, chunk):
        self.data += bytes(chunk)


class _S3Adapter(BaseProvider):
    """S3 通道适配器：统一接口桥到 ``_s3.S3Client``；传输可注入（测试桩替换）。"""

    def __init__(self, transport=None):
        self._transport = transport

    def _client(self, ctx, profile):
        from . import _s3
        return _s3.S3Client(ctx, profile, profile.get("credentials") or {},
                            transport=self._transport)

    def test_connection(self, ctx, profile):
        return self._client(ctx, profile).test_connection()

    def list_keys(self, ctx, profile, prefix):
        return self._client(ctx, profile).list_keys(prefix)

    def put(self, ctx, profile, key, data, resume_from=0, upload_id=None):
        resume = {"upload_id": upload_id, "parts": {}} if upload_id else None
        return self._client(ctx, profile).put(key, data, resume=resume)

    def get(self, ctx, profile, key):
        return self._client(ctx, profile).get(key)

    def delete(self, ctx, profile, key):
        return self._client(ctx, profile).delete(key)

    def head(self, ctx, profile, key):
        return self._client(ctx, profile).head(key)


class _WebDavAdapter(BaseProvider):
    """WebDAV 通道适配器：统一接口桥到 ``_webdav.WebDavClient``。"""

    def _client(self, ctx, profile):
        from . import _webdav
        creds = profile.get("credentials") or {}
        policy = profile.get("policy") or {}
        cfg = {
            "ca_bundle": policy.get("ca_bundle") or creds.get("ca_bundle"),
            "upload_chunk_size": policy.get("upload_chunk_size"),
        }
        return _webdav.WebDavClient(
            profile.get("endpoint"),
            username=creds.get("username") or creds.get("access_key"),
            password=creds.get("password") or creds.get("secret_key"),
            cfg=cfg,
            auth=str(policy.get("auth") or "auto"),
            max_attempts=int(policy.get("max_attempts") or 3),
            max_body_bytes=int(policy.get("max_body_bytes") or 0))

    def test_connection(self, ctx, profile):
        return self._client(ctx, profile).test_connection()

    def list_keys(self, ctx, profile, prefix):
        res = self._client(ctx, profile).propfind("", depth=1)
        if not res.get("ok"):
            return []
        rows = []
        for entry in res.get("entries") or []:
            if entry.get("is_dir"):
                continue
            rows.append({"key": entry["key"], "digest": entry.get("etag") or "",
                         "size": entry.get("size") or 0})
        return rows

    def put(self, ctx, profile, key, data, resume_from=0, upload_id=None):
        res = self._client(ctx, profile).put(key, bytes(data))
        if not res.get("ok"):
            return {"ok": False, "code": res.get("code") or "provider_error",
                    "offset": resume_from}
        return {"ok": True, "size": res.get("size") or len(data),
                "offset": res.get("offset") or len(data), "etag": res.get("etag")}

    def get(self, ctx, profile, key):
        sink = _ByteSink()
        res = self._client(ctx, profile).get(key, sink)
        if not res.get("ok"):
            return {"ok": False, "code": res.get("code") or "provider_error"}
        data = sink.data
        digest = ctx.api.call("codec.digest", {"text": data, "algorithm": "sha256"},
                              caller=None).get("hex")
        return {"ok": True, "data": data, "digest": digest, "size": len(data)}

    def delete(self, ctx, profile, key):
        res = self._client(ctx, profile).delete(key)
        return {"ok": bool(res.get("ok"))}


# ---------------------------------------------------------------- 注册表与元数据

def _build_s3():
    # 模块存在性探测：缺失抛 ImportError，由 build 回落 unsupported 占位。
    from . import _s3  # noqa: F401
    return _S3Adapter()


def _build_webdav():
    from . import _webdav  # noqa: F401
    return _WebDavAdapter()


_LAZY = {"s3": _build_s3, "webdav": _build_webdav}
_UNSUPPORTED_CODE = {"s3": "s3_signing_pending", "webdav": "adapter_pending"}

REGISTRY = {
    "fake": FakeProvider,
    "stub": FakeProvider,
    "http_dir": HttpDirProvider,
    "wiki": HttpDirProvider,
    "rsync": RsyncProvider,
}

# 运行时状态覆盖：_pure 台账为静态基线，真实通道接线状态在此叠加（不改 _pure）。
_META_OVERLAY = {
    "s3": {"transport": "https-rest-s3v4", "status": "ready", "note": "sigv4"},
}


def build(kind):
    """按提供方类型构造实例；惰性通道模块缺失回落占位；未知类型抛 ProviderError。"""
    if kind in _LAZY:
        try:
            return _LAZY[kind]()
        except ImportError:
            return _PendingProvider(
                status_code=_UNSUPPORTED_CODE.get(kind, "adapter_pending"))
    cls = REGISTRY.get(kind)
    if cls is None:
        raise ProviderError("unknown_provider", "unknown provider kind: %s" % kind)
    return cls()


def provider_meta():
    """提供方清单元数据（只读）：类型、通道、落地状态、备注。"""
    items = []
    for kind, meta in _pure.PROVIDER_META.items():
        row = {"kind": kind, **meta}
        row.update(_META_OVERLAY.get(kind, {}))
        items.append(row)
    return items
