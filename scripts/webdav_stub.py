#!/usr/bin/env python3
"""本地 WebDAV stub：PROPFIND / PUT / GET / MKCOL / DELETE / HEAD，供离线测试与验收复用。

按 HTTP/WebDAV 语义响应：

- PROPFIND 返回 207 multistatus XML，Depth 0/1；
- PUT 落盘（流式写临时文件再改名）；GET 流式回包，支持 Range 206 续传；
- MKCOL 已存在回 409；DELETE 缺失回 404；HEAD 只回头不回体；
- 认证模式：none / basic / digest。digest 仅发 challenge 并在带 Authorization 后放行，
  不做完整摘要校验，覆盖客户端 401 重试链路即可。

作为模块调用::

    from webdav_stub import start_stub
    server, thread, base_url = start_stub(auth={"mode": "basic", "user": "u",
                                                "password": "p"})

作为进程调用::

    python3 webdav_stub.py --port 0 --dir /tmp/dav-root --auth-mode basic \\
        --auth-user u --auth-password p
    # 标准输出首行：BASE_URL=http://127.0.0.1:<port>/
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import os
import re
import shutil
import tempfile
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

_RANGE_RE = re.compile(r"bytes=(\d+)-(\d*)")
_DIGEST_RE = re.compile(r'(\w+)\s*=\s*("([^"]*)"|([^,]+))')


def _md5_hex(text):
    if isinstance(text, str):
        text = text.encode("utf-8")
    return hashlib.md5(bytes(text)).hexdigest()


def _parse_digest_header(header):
    params = {}
    for match in _DIGEST_RE.finditer(header.partition(" ")[2]):
        params[match.group(1)] = match.group(3) if match.group(3) is not None else match.group(4)
    return params


def _xml_escape(text):
    return (str(text).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


class _Store:
    """桩存储：本地目录 + 计数器（PUT/GET/认证挑战次数等）。"""

    def __init__(self, root):
        self.root = root
        self.puts = 0
        self.chunk_puts = 0
        self.moves = 0
        self.gets = 0
        self.propfinds = 0
        self.deletes = 0
        self.mkcols = 0
        self.challenges = 0
        self.authenticated = 0
        # 测试钩子：路径 → 自定义 multistatus 响应体（XXE 载荷用例注入）。
        self.custom_propfind = {}

    def resolve(self, url_path):
        """URL 路径 → 本地绝对路径；穿越 / 越出根目录返回 None。"""
        rel = urllib.parse.unquote(url_path).lstrip("/")
        parts = [p for p in rel.split("/") if p not in ("", ".")]
        if any(p == ".." for p in parts):
            return None
        target = os.path.realpath(os.path.join(self.root, *parts))
        root_real = os.path.realpath(self.root)
        if target != root_real and not target.startswith(root_real + os.sep):
            return None
        return target


def _etag(path):
    digest = hashlib.md5()  # noqa: S324 - 桩侧 ETag，非安全用途
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            digest.update(chunk)
    return '"%s"' % digest.hexdigest()


class _Handler(BaseHTTPRequestHandler):
    server_version = "webdav-stub/1.0"

    # ------------------------------------------------------------ 基础设施

    def log_message(self, fmt, *args):  # noqa: D401 - 静音访问日志
        return

    def _send(self, status, body=b"", headers=None):
        self.send_response(status)
        for key, value in (headers or {}).items():
            self.send_header(key, str(value))
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if body:
            self.wfile.write(body)

    def _read_body(self):
        length = int(self.headers.get("Content-Length") or 0)
        return self.rfile.read(length) if length else b""

    def _digest_valid(self, auth, params, body):
        """独立复算 RFC 2617 Digest（auth / auth-int），与客户端实现互验。"""
        user, password = auth["user"], auth["password"]
        if params.get("username") != user:
            return False
        realm = params.get("realm") or "stub"
        nonce = params.get("nonce") or ""
        uri = params.get("uri") or self.path
        qop = params.get("qop") or ""
        nc = params.get("nc") or "00000001"
        cnonce = params.get("cnonce") or ""
        ha1 = _md5_hex("%s:%s:%s" % (user, realm, password))
        if qop == "auth-int":
            ha2 = _md5_hex("%s:%s:%s" % (self.command, uri, _md5_hex(body)))
            expected = _md5_hex(
                "%s:%s:%s:%s:%s:%s" % (ha1, nonce, nc, cnonce, qop, ha2))
        elif qop == "auth":
            ha2 = _md5_hex("%s:%s" % (self.command, uri))
            expected = _md5_hex(
                "%s:%s:%s:%s:%s:%s" % (ha1, nonce, nc, cnonce, qop, ha2))
        else:
            ha2 = _md5_hex("%s:%s" % (self.command, uri))
            expected = _md5_hex("%s:%s:%s" % (ha1, nonce, ha2))
        return hmac.compare_digest(expected, params.get("response") or "")

    def _authorized(self):
        auth = getattr(self.server, "auth", None)
        self._pending_body = None
        if not auth:
            return True
        header = self.headers.get("Authorization")
        if not header:
            self.server.store.challenges += 1
            if auth["mode"] == "digest":
                qop = auth.get("qop") or "auth"
                self.send_response(401)
                self.send_header(
                    "WWW-Authenticate",
                    'Digest realm="stub", nonce="stub-nonce-1", '
                    'qop="%s", opaque="stub-opaque"' % qop)
            else:
                self.send_response(401)
                self.send_header("WWW-Authenticate", 'Basic realm="stub"')
            self.send_header("Content-Length", "0")
            self.end_headers()
            return False
        scheme, _, cred = header.partition(" ")
        if scheme.lower() == "basic":
            decoded = base64.b64decode(cred).decode("utf-8", "replace")
            user, _, password = decoded.partition(":")
            ok = user == auth["user"] and password == auth["password"]
            body = b""
        else:
            body = self._read_body()
            self._pending_body = body
            ok = self._digest_valid(auth, _parse_digest_header(header), body)
        if ok:
            self.server.store.authenticated += 1
        else:
            # 凭证无效：回 401 challenge，不静默断连（避免掩盖鉴权失败）。
            self.server.store.challenges += 1
            if auth["mode"] == "digest":
                qop = auth.get("qop") or "auth"
                self.send_response(401)
                self.send_header(
                    "WWW-Authenticate",
                    'Digest realm="stub", nonce="stub-nonce-1", '
                    'qop="%s", opaque="stub-opaque"' % qop)
            else:
                self.send_response(401)
                self.send_header("WWW-Authenticate", 'Basic realm="stub"')
            self.send_header("Content-Length", "0")
            self.end_headers()
        return ok

    # ------------------------------------------------------------ 路由

    def do_PROPFIND(self):
        if not self._authorized():
            return
        store = self.server.store
        store.propfinds += 1
        target = store.resolve(self.path)
        if target is None:
            self._send(404, "not found")
            return
        custom = store.custom_propfind.get(urllib.parse.urlsplit(self.path).path)
        if custom is not None:
            self._send(207, custom, {"Content-Type": "application/xml"})
            return
        depth = int(self.headers.get("Depth") or 1)
        body = self._propfind_body(target, urllib.parse.urlsplit(self.path).path, depth)
        self._send(207, body, {"Content-Type": "application/xml"})

    def do_PUT(self):
        if not self._authorized():
            return
        store = self.server.store
        target = store.resolve(self.path)
        if target is None:
            self._send(404, "not found")
            return
        body = self._pending_body
        if body is None:
            body = self._read_body()
        parent = os.path.dirname(target)
        os.makedirs(parent, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=parent)
        try:
            with os.fdopen(fd, "wb") as fh:
                fh.write(body)
            os.replace(tmp, target)
        except OSError:
            os.unlink(tmp)
            self._send(500, "write failed")
            return
        if "/.upload/" in self.path:
            store.chunk_puts += 1
        else:
            store.puts += 1
        self._send(201, "", {"ETag": _etag(target)})

    def do_OPTIONS(self):
        range_put = getattr(self.server, "range_put", False)
        self.send_response(200)
        self.send_header("DAV", "1,2")
        allow = "OPTIONS, HEAD, GET, PUT, MKCOL, DELETE, PROPFIND, MOVE"
        self.send_header("Allow", allow)
        if range_put:
            self.send_header("X-WebDAV-Range-PUT", "1")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_MOVE(self):
        if not self._authorized():
            return
        store = self.server.store
        source = store.resolve(self.path)
        if source is None or not os.path.exists(source):
            self._send(404, "not found")
            return
        dest_header = self.headers.get("Destination") or ""
        dest_path = urllib.parse.urlsplit(dest_header).path
        target = store.resolve(dest_path)
        if target is None:
            self._send(404, "bad destination")
            return
        parent = os.path.dirname(target)
        os.makedirs(parent, exist_ok=True)
        try:
            if os.path.isdir(source) and not os.path.isdir(target):
                # 块集合组装：按块号排序拼接为最终对象。
                names = sorted(n for n in os.listdir(source)
                               if os.path.isfile(os.path.join(source, n)))
                with open(target, "wb") as out:
                    for name in names:
                        with open(os.path.join(source, name), "rb") as fh:
                            shutil.copyfileobj(fh, out)
                shutil.rmtree(source)
            else:
                shutil.move(source, target)
        except OSError:
            self._send(500, "move failed")
            return
        store.moves += 1
        self._send(201, "", {"ETag": _etag(target)})

    def do_GET(self):
        if not self._authorized():
            return
        store = self.server.store
        target = store.resolve(self.path)
        if target is None or not os.path.isfile(target):
            self._send(404, "not found")
            return
        size = os.path.getsize(target)
        match = _RANGE_RE.match(self.headers.get("Range") or "")
        start = int(match.group(1)) if match else 0
        if start > size:
            self._send(416, "range not satisfiable")
            return
        partial = bool(match)
        self.send_response(206 if partial else 200)
        if partial:
            self.send_header("Content-Range", "bytes %d-%d/%d" % (start, size - 1, size))
            self.send_header("Content-Length", str(size - start))
        else:
            self.send_header("Content-Length", str(size))
        self.send_header("ETag", _etag(target))
        self.end_headers()
        with open(target, "rb") as fh:
            fh.seek(start)
            remaining = size - start
            while remaining > 0:
                chunk = fh.read(min(65536, remaining))
                if not chunk:
                    break
                self.wfile.write(chunk)
                remaining -= len(chunk)
        store.gets += 1

    def do_HEAD(self):
        if not self._authorized():
            return
        store = self.server.store
        target = store.resolve(self.path)
        if target is None or not os.path.isfile(target):
            self._send(404, "")
            return
        self.send_response(200)
        self.send_header("Content-Length", str(os.path.getsize(target)))
        self.send_header("ETag", _etag(target))
        self.send_header("Content-Type", "application/octet-stream")
        self.end_headers()

    def do_MKCOL(self):
        if not self._authorized():
            return
        store = self.server.store
        target = store.resolve(self.path)
        if target is None:
            self._send(404, "not found")
            return
        if os.path.exists(target):
            self._send(409, "collection already exists")
            return
        os.makedirs(target)
        store.mkcols += 1
        self._send(201, "")

    def do_DELETE(self):
        if not self._authorized():
            return
        store = self.server.store
        target = store.resolve(self.path)
        if target is None or not os.path.exists(target):
            self._send(404, "not found")
            return
        if os.path.isdir(target):
            shutil.rmtree(target)
        else:
            os.unlink(target)
        store.deletes += 1
        self._send(204, "")

    # ------------------------------------------------------------ PROPFIND 成形

    def _propfind_body(self, target, url_path, depth):
        entries = []
        if os.path.isdir(target):
            entries.append((url_path, True, 0, None))
            if depth >= 1:
                for name in sorted(os.listdir(target)):
                    child = os.path.join(target, name)
                    child_url = url_path.rstrip("/") + "/" + name
                    if os.path.isdir(child):
                        entries.append((child_url, True, 0, None))
                    else:
                        entries.append((child_url, False, os.path.getsize(child),
                                        _etag(child)))
        elif os.path.isfile(target):
            entries.append((url_path, False, os.path.getsize(target), _etag(target)))

        out = ['<?xml version="1.0" encoding="utf-8"?>',
               '<d:multistatus xmlns:d="DAV:">']
        for href, is_dir, size, etag in entries:
            out.append("<d:response><d:href>%s</d:href>" % _xml_escape(href))
            out.append("<d:propstat><d:prop>")
            if is_dir:
                out.append("<d:resourcetype><d:collection/></d:resourcetype>")
            else:
                out.append("<d:getcontentlength>%d</d:getcontentlength>" % size)
                if etag:
                    out.append("<d:getetag>%s</d:getetag>" % _xml_escape(etag))
            out.append("</d:prop><d:status>HTTP/1.1 200 OK</d:status></d:propstat>")
            out.append("</d:response>")
        out.append("</d:multistatus>")
        return "".join(out).encode("utf-8")


def start_stub(auth=None, directory=None, port=0, range_put=False):
    """起桩服务（守护线程），返回 ``(server, thread, base_url)``。"""
    root = directory or tempfile.mkdtemp(prefix="webdav-stub-")
    server = ThreadingHTTPServer(("127.0.0.1", port), _Handler)
    server.store = _Store(root)
    server.auth = auth
    server.range_put = range_put
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    bound = server.server_address[1]
    return server, thread, "http://127.0.0.1:%d/" % bound


def main(argv=None):
    parser = argparse.ArgumentParser(description="local WebDAV stub")
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--dir", default=None)
    parser.add_argument("--auth-mode", choices=("none", "basic", "digest"),
                        default="none")
    parser.add_argument("--auth-user", default="u")
    parser.add_argument("--auth-password", default="p")
    args = parser.parse_args(argv)

    auth = None
    if args.auth_mode != "none":
        auth = {"mode": args.auth_mode, "user": args.auth_user,
                "password": args.auth_password}
    server, _thread, base_url = start_stub(auth=auth, directory=args.dir,
                                          port=args.port)
    print("BASE_URL=%s" % base_url)
    threading.Event().wait()
    server.shutdown()


if __name__ == "__main__":
    main()
