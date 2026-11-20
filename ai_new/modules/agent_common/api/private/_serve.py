"""通信的服务端：把本进程的路由挂到本机 IPC 上。

三条本机通道，语义都是"消息"，不是"函数调用"：

    unix  本地 socket（AF_UNIX，文件路径，权限 0600）
    tcp   网络 socket（AF_INET，只允许绑 127.0.0.1）
    shm   共享内存信箱（两个 mmap 文件 + flock，请求与应答各一份）

协议统一：4 字节长度前缀 + UTF-8 的 YAML flow 报文；报文是
`{token, route, payload}`，应答是 `{ok, result}` 或 `{ok, error, code}`。
谁提供能力谁起监听：listen 由部署意图编出来，绑定里没出现的通道就不开端口。
"""
from __future__ import annotations

import fcntl
import mmap
import os
import socket
import struct
import threading
import time
from pathlib import Path

from . import _wire

HDR = _wire.HDR               # (length, seq)；与客户端共用一份
SHM_SIZE = 512 * 1024


class Server:
    def __init__(self, ctx):
        self.ctx = ctx
        self._threads = []
        self._stop = threading.Event()
        self._closed = []

    # ---- 对外：按部署意图起监听 ----
    def start(self, listen, kinds):
        """kinds：绑定里实际出现的通道集合，只开用到的那些。"""
        listen = listen or {}
        started = []
        if "unix" in kinds and (listen.get("unix") or {}).get("path"):
            self._start_unix(listen["unix"]["path"])
            started.append({"kind": "unix", "path": listen["unix"]["path"]})
        if "tcp" in kinds and (listen.get("tcp") or {}).get("port"):
            host = listen["tcp"].get("host") or "127.0.0.1"
            port = int(listen["tcp"]["port"])
            self._start_tcp(host, port)
            started.append({"kind": "tcp", "addr": "%s:%d" % (host, port)})
        if "shm" in kinds and (listen.get("shm") or {}).get("dir"):
            self._start_shm(listen["shm"]["dir"])
            started.append({"kind": "shm", "dir": listen["shm"]["dir"]})
        return started

    def stop(self):
        self._stop.set()
        for closer in self._closed:
            try:
                closer()
            except OSError:
                pass
        for path in getattr(self, "_unlink", []):
            try:
                os.unlink(path)
            except OSError:
                pass

    # ---- 报文处理（三种通道共用）----
    def handle(self, text):
        try:
            rec = self.ctx.codec.yaml_decode(text)["value"] or {}
        except Exception as exc:  # noqa: BLE001
            return self._encode({"ok": False, "error": "报文解码失败: %s" % exc,
                                 "code": "decode_failed"})
        token = ((getattr(self.ctx, "cfg", None) or {}).get("server") or {}).get("token") or ""
        if token and rec.get("token") != token:
            return self._encode({"ok": False, "error": "令牌不匹配", "code": "unauthorized"})
        route = str(rec.get("route") or "")
        payload = rec.get("payload") or {}
        tid = str(rec.get("trace") or "")
        if tid:
            try:
                self.ctx.api.call("trace.attach", {"trace": tid},
                                  caller="platform:api-server", direct=True)
            except Exception:
                pass
        if not route:
            return self._encode({"ok": False, "error": "缺 route", "code": "bad_request"})
        try:
            result = self.ctx.api.call(route, payload, caller="platform:api-server", direct=True)
            return self._encode({"ok": True, "result": result})
        except Exception as exc:  # noqa: BLE001 —— 远端错误原样回头
            return self._encode({"ok": False, "error": "%s: %s" % (type(exc).__name__, exc),
                                 "code": getattr(exc, "code", "")})

    def _encode(self, value):
        return self.ctx.codec.yaml_encode_flow(value)["text"]

    # ---- unix socket ----
    def _start_unix(self, path):
        path = str(path)
        try:
            os.unlink(path)
        except OSError:
            pass
        srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.bind(path)
        os.chmod(path, 0o600)
        srv.listen(64)
        self._closed.append(srv.close)
        self._unlink = getattr(self, "_unlink", []) + [path]
        t = threading.Thread(target=self._accept, args=(srv,), daemon=True,
                             name="api-unix")
        t.start()
        self._threads.append(t)

    # ---- tcp socket ----
    def _start_tcp(self, host, port):
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.bind((host, port))
        srv.listen(64)
        self._closed.append(srv.close)
        t = threading.Thread(target=self._accept, args=(srv,), daemon=True,
                             name="api-tcp")
        t.start()
        self._threads.append(t)

    def _accept(self, srv):
        while not self._stop.is_set():
            try:
                conn, _addr = srv.accept()
            except OSError:
                return
            threading.Thread(target=self._serve_one, args=(conn,), daemon=True).start()

    def _serve_one(self, conn):
        try:
            with conn:
                conn.settimeout(30)
                body = _wire.read_frame(conn)
                if body is None:
                    return
                reply = self.handle(body.decode("utf-8", "replace")).encode("utf-8")
                _wire.send_frame(conn, reply)
        except OSError:
            return

    # ---- 共享内存信箱 ----
    def _start_shm(self, directory):
        d = Path(directory)
        d.mkdir(parents=True, exist_ok=True)
        self._shm_req = d / "req.bin"
        self._shm_resp = d / "resp.bin"
        for f in (self._shm_req, self._shm_resp):
            if not f.exists() or f.stat().st_size < SHM_SIZE:
                with open(f, "wb") as fh:
                    fh.write(b"\0" * SHM_SIZE)
        t = threading.Thread(target=self._shm_loop, args=(self._shm_req, self._shm_resp),
                             daemon=True, name="api-shm")
        t.start()
        self._threads.append(t)

    def _shm_loop(self, req, resp):
        seen = 0
        while not self._stop.is_set():
            body, seq = "", 0
            with open(req, "r+b") as fh:
                mm = mmap.mmap(fh.fileno(), SHM_SIZE)
                fcntl.flock(fh, fcntl.LOCK_EX)
                try:
                    ln, sq = HDR.unpack_from(mm, 0)
                    if sq and sq != seen and 0 < ln <= SHM_SIZE - HDR.size:
                        body = mm[HDR.size:HDR.size + ln].decode("utf-8", "replace")
                        seq = sq
                finally:
                    fcntl.flock(fh, fcntl.LOCK_UN)
                    mm.close()
            if not seq:
                time.sleep(0.002)
                continue
            seen = seq
            text = self.handle(body).encode("utf-8")[:SHM_SIZE - HDR.size]
            with open(resp, "r+b") as fh:
                mm = mmap.mmap(fh.fileno(), SHM_SIZE)
                fcntl.flock(fh, fcntl.LOCK_EX)
                try:
                    HDR.pack_into(mm, 0, len(text), seq)
                    mm[HDR.size:HDR.size + len(text)] = text
                finally:
                    fcntl.flock(fh, fcntl.LOCK_UN)
                    mm.close()


def kinds_in(bindings):
    """绑定里实际用到的通道（direct 不需要监听）。"""
    found = set()
    for spec in ((bindings or {}).get("routes") or {}).values():
        kind = (spec or {}).get("kind") or "direct"
        if kind != "direct":
            found.add(kind)
    default_kind = ((bindings or {}).get("default") or {}).get("kind") or "direct"
    if default_kind != "direct":
        found.add(default_kind)
    return found
