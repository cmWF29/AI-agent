"""Provider 适配层：统一连接/上传/下载/列目录/删除/校验接口与注册表。

出站只经 ``net.request``；不直连 socket/urllib。真实协议落地状态见
``_pure.PROVIDER_META`` 与报告「云端接入三个方案的真实落地差异」。
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


class S3Provider(_PendingProvider):
    """S3 兼容对象存储：路径风格 REST；AWS V4 签名未接线。"""

    status_code = "s3_signing_pending"


class RsyncProvider(_PendingProvider):
    """rsync/ssh 自建服务器：需 exec 能力包装命令；当前未接线。"""

    status_code = "exec_wrapper_pending"


REGISTRY = {
    "fake": FakeProvider,
    "stub": FakeProvider,
    "http_dir": HttpDirProvider,
    "webdav": HttpDirProvider,
    "wiki": HttpDirProvider,
    "s3": S3Provider,
    "rsync": RsyncProvider,
}


def build(kind):
    """按提供方类型构造实例；未知类型抛 ProviderError。"""
    cls = REGISTRY.get(kind)
    if cls is None:
        raise ProviderError("unknown_provider", "unknown provider kind: %s" % kind)
    return cls()


def provider_meta():
    """提供方清单元数据（只读）：类型、通道、落地状态、备注。"""
    return [{"kind": k, **v} for k, v in _pure.PROVIDER_META.items()]
