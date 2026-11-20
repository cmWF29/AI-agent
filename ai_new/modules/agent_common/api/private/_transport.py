"""通信是抽象：同一份模板代码，换部署只重编绑定。

模块里写的永远是 `ctx.api.call(route, payload, caller)`（或 `notify` 单向投递）。这条调用
走哪条通道，不由代码决定，由 `data/deploy.yaml` 编译出的 `data/gen/bindings.yaml` 决定：

    direct  同进程直连（单机默认，唯一零拷贝）
    unix    本地 socket（AF_UNIX，同机跨进程）
    tcp     网络 socket（AF_INET，本机 127.0.0.1；跨机不在本轮范围）
    shm     共享内存信箱（mmap + flock，同机跨进程，大块报文不复制）

四条通道都是"消息"：统一 4 字节长度前缀 + UTF-8 YAML flow 报文。
没有绑定文件时默认全直连——单进程里跑，和以前完全一样。
"""
from __future__ import annotations

import fcntl
import mmap
import socket
import struct
import time
from pathlib import Path

from . import _wire

HDR = _wire.HDR


class Transport:
    def __init__(self, ctx):
        self.ctx = ctx
        self._bindings = None
        self._seq = 0

    # ---- 绑定（懒加载：装配早期还没有 storage）----
    def bindings(self):
        if self._bindings is None:
            md = self.ctx.storage.own(__file__)
            raw = md.read_text("gen/bindings.yaml") if md.exists("gen/bindings.yaml") else "{}"
            self._bindings = (self.ctx.codec.yaml_decode(raw or "{}")["value"] or {})
        return self._bindings

    def reload(self):
        self._bindings = None

    def listen(self):
        return self.bindings().get("listen") or {}

    def kind_for(self, route):
        """返回 (通道, 地址)。地址从 listen 段取：同机通道只有一个入口，换端口改部署意图。"""
        routes = self.bindings().get("routes") or {}
        item = routes.get(route) or routes.get(route.split(".")[0] + ".*")
        spec = item or (self.bindings().get("default") or {})
        kind = spec.get("kind") or "direct"
        listen = self.listen()
        if kind == "direct":
            return kind, None
        if kind == "unix":
            return kind, (listen.get("unix") or {}).get("path")
        if kind == "tcp":
            row = listen.get("tcp") or {}
            if not row.get("port"):
                return kind, None
            return kind, "%s:%s" % (row.get("host") or "127.0.0.1", row["port"])
        if kind == "shm":
            return kind, (listen.get("shm") or {}).get("dir")
        raise self.ctx.ApiError("未知通信通道: %s (route %s)" % (kind, route),
                                code="bad_transport", status=500)

    def describe(self):
        return {"default": (self.bindings().get("default") or {}).get("kind") or "direct",
                "routes": self.bindings().get("routes") or {},
                "listen": self.listen(),
                "source": "data/gen/bindings.yaml" if self.bindings() else "未生成，全直连"}

    def _timeout(self):
        api = (getattr(self.ctx, "cfg", None) or {}).get("api") or {}
        try:
            return float(api.get("transport_timeout") or 10)
        except (TypeError, ValueError):
            return 10.0

    # ---- 派发 ----
    def send(self, route, payload, handler, caller=None):
        kind, addr = self.kind_for(route)
        if kind == "direct":
            return handler(self.ctx, payload or {})
        body = self._pack(route, payload)
        if kind == "unix":
            return self._unix(addr, route, body, expect=True)
        if kind == "tcp":
            return self._tcp(addr, route, body, expect=True)
        if kind == "shm":
            return self._shm(addr, route, body, expect=True)
        raise self.ctx.ApiError("未知通信通道: %s" % kind, code="bad_transport", status=500)

    def notify(self, route, payload, handler, caller=None):
        """单向投递：不解析应答，只承诺"已发出"。"""
        kind, addr = self.kind_for(route)
        if kind == "direct":
            handler(self.ctx, payload or {})
            return {"transport": "direct", "sent": route}
        body = self._pack(route, payload)
        if kind == "unix":
            self._unix(addr, route, body, expect=False)
        elif kind == "tcp":
            self._tcp(addr, route, body, expect=False)
        elif kind == "shm":
            self._shm(addr, route, body, expect=False)
        else:
            raise self.ctx.ApiError("未知通信通道: %s" % kind, code="bad_transport", status=500)
        return {"transport": kind, "sent": route}

    # ---- 报文 ----
    def _pack(self, route, payload):
        token = ((getattr(self.ctx, "cfg", None) or {}).get("server") or {}).get("token") or ""
        return _wire.pack(self.ctx.codec, route, payload, token)

    def _unpack(self, route, text):
        rec = self.ctx.codec.yaml_decode(text)["value"] or {}
        if not rec.get("ok"):
            raise self.ctx.ApiError("远端调用被拒: %s %s" % (route, rec.get("error")),
                                    code=rec.get("code") or "remote_error", status=502)
        return rec.get("result")

    # ---- unix socket ----
    def _unix(self, addr, route, body, expect=True):
        if not addr:
            raise self.ctx.ApiError("通道 unix 缺少 listen.unix.path: %s" % route,
                                    code="bad_transport", status=500)
        conn = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        conn.settimeout(self._timeout())
        try:
            conn.connect(str(addr))
            return self._roundtrip(conn, route, body, expect)
        except OSError as exc:
            raise self.ctx.ApiError("本地 socket 调用失败: %s (%s)" % (route, exc),
                                    code="remote_error", status=502)
        finally:
            conn.close()

    # ---- tcp socket ----
    def _tcp(self, addr, route, body, expect=True):
        if not addr:
            raise self.ctx.ApiError("通道 tcp 缺少 listen.tcp: %s" % route,
                                    code="bad_transport", status=500)
        host, _, port = str(addr).partition(":")
        conn = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        conn.settimeout(self._timeout())
        try:
            conn.connect((host, int(port)))
            return self._roundtrip(conn, route, body, expect)
        except OSError as exc:
            raise self.ctx.ApiError("网络 socket 调用失败: %s (%s)" % (route, exc),
                                    code="remote_error", status=502)
        finally:
            conn.close()

    def _roundtrip(self, conn, route, body, expect):
        _wire.send_frame(conn, body)
        if not expect:
            return None
        data = _wire.read_frame(conn)
        if data is None:
            raise self.ctx.ApiError("远端提前断开: %s" % route, code="remote_error", status=502)
        return self._unpack(route, data.decode("utf-8", "replace"))

    # ---- 共享内存信箱 ----
    def _next_seq(self):
        self._seq = (self._seq + 1) % 0x7FFFFFFF
        return self._seq or 1

    def _shm(self, addr, route, body, expect=True):
        if not addr:
            raise self.ctx.ApiError("通道 shm 缺少 listen.shm.dir: %s" % route,
                                    code="bad_transport", status=500)
        req = Path(addr) / "req.bin"
        resp = Path(addr) / "resp.bin"
        seq = self._next_seq()
        try:
            with open(req, "r+b") as fh:
                mm = mmap.mmap(fh.fileno(), 0)
                fcntl.flock(fh, fcntl.LOCK_EX)
                try:
                    HDR.pack_into(mm, 0, len(body), seq)
                    mm[8:8 + len(body)] = body
                finally:
                    fcntl.flock(fh, fcntl.LOCK_UN)
                    mm.close()
        except OSError as exc:
            raise self.ctx.ApiError("共享内存写失败: %s (%s)" % (route, exc),
                                    code="remote_error", status=502)
        if not expect:
            return None
        deadline = time.time() + self._timeout()
        while time.time() < deadline:
            try:
                with open(resp, "r+b") as fh:
                    mm = mmap.mmap(fh.fileno(), 0)
                    fcntl.flock(fh, fcntl.LOCK_EX)
                    try:
                        ln, rseq = HDR.unpack_from(mm, 0)
                        text = mm[8:8 + ln].decode("utf-8", "replace") if rseq == seq and ln > 0 else None
                    finally:
                        fcntl.flock(fh, fcntl.LOCK_UN)
                        mm.close()
            except OSError as exc:
                raise self.ctx.ApiError("共享内存读失败: %s (%s)" % (route, exc),
                                        code="remote_error", status=502)
            if text is not None:
                return self._unpack(route, text)
            time.sleep(0.002)
        raise self.ctx.ApiError("共享内存应答超时: %s" % route,
                                code="remote_timeout", status=504)
