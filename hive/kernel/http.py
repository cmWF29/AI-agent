"""HTTP 传输层：静态页 + JSON API + 鉴权。

它是模块 API 的唯一入口，本身不含业务逻辑：
所有 /api/* 都路由到 ctx.router 里注册的模块路由上。
"""
from __future__ import annotations

import json
import mimetypes
import os
import re
import secrets
import socket
import ssl
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .api import ApiError

WEB_DIR_DEFAULT = "web"
_PUBLIC_PATHS = {"/", "/index.html", "/app.js", "/style.css", "/favicon.ico", "/api/health", "/api/auth/login", "/api/auth/status"}


class HttpService:
    def __init__(self, cfg, router, log, web_dir=None):
        self.cfg = cfg
        self.router = router
        self.log = log
        self.host = cfg["server"]["host"]
        self.port = int(cfg["server"]["port"])
        self.token = cfg["server"].get("token") or ""
        self.web_password = cfg["server"].get("web_password") or ""
        self.cookie_name = cfg["server"].get("cookie_name") or "hive_auth"
        self.max_bytes = int(cfg["server"].get("request_max_bytes", 4 * 1024 * 1024))
        self.web_dir = web_dir or os.path.join(cfg["root"], WEB_DIR_DEFAULT)
        self._httpd = None
        self._thread = None
        self.started_at = None
        self.counters = {"requests": 0, "errors": 0, "auth_fail": 0}
        self.tls_context = None
        self.scheme = "http"

    def _tls_config(self):
        tls = self.cfg["server"].get("tls") if isinstance(self.cfg["server"].get("tls"), dict) else {}
        if not tls.get("enabled"):
            return None
        from .config import path_of
        cert = path_of(self.cfg, "server.tls.cert", "config/tls/server.crt")
        key = path_of(self.cfg, "server.tls.key", "config/tls/server.key")
        if not (os.path.isfile(cert) and os.path.isfile(key)):
            if self.log:
                self.log.warn("http.tls.skip", reason="证书不存在，退回 HTTP", cert=cert)
            return None
        try:
            ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            ctx.load_cert_chain(cert, key)
            return ctx
        except (ssl.SSLError, OSError) as exc:
            if self.log:
                self.log.error("http.tls.load_failed", error=repr(exc))
            return None

    def ensure_token(self):
        """token 为空时生成一个并写回配置文件，保证 CLI 与网页用的是同一个。"""
        if self.token:
            return self.token
        self.token = secrets.token_urlsafe(24)
        self.cfg["server"]["token"] = self.token
        try:
            from .config import save_config
            save_config(self.cfg)
        except Exception:
            pass
        return self.token

    def serve_forever(self):
        service = self

        class Handler(BaseHTTPRequestHandler):
            server_version = "HiveHTTP/1.0"
            protocol_version = "HTTP/1.1"

            def log_message(self, fmt, *args):
                if service.log:
                    service.log.debug("http.access", line=fmt % args)

            # ---- verbs ----
            def do_GET(self):
                self._handle("GET")

            def do_POST(self):
                self._handle("POST")

            def do_PUT(self):
                self._handle("PUT")

            def do_DELETE(self):
                self._handle("DELETE")

            def do_OPTIONS(self):
                self._send(204, b"", {})

            # ---- core ----
            def _handle(self, method):
                service.counters["requests"] += 1
                parsed = urllib.parse.urlsplit(self.path)
                path = urllib.parse.unquote(parsed.path) or "/"
                query = urllib.parse.parse_qs(parsed.query, keep_blank_values=True)

                if method == "GET" and not path.startswith("/api/"):
                    return self._serve_static(path)

                if path == "/api/auth/login" and method == "POST":
                    return self._login()

                if path == "/api/auth/status" and method == "GET":
                    return self._json(200, {"ok": True, "authed": self._authed(), "login_required": True,
                                            "scheme": service.scheme,
                                            "https": service.scheme == "https"})

                route, params = service.router.match(method, path)
                if route is None:
                    return self._json(404, {"ok": False, "error": "no such api: %s %s" % (method, path), "code": "not_found"})

                if route.auth and not self._authed():
                    service.counters["auth_fail"] += 1
                    return self._json(401, {"ok": False, "error": "未登录或 token 无效", "code": "unauthorized"})

                try:
                    body = self._read_body()
                except ValueError as e:
                    return self._json(400, {"ok": False, "error": str(e), "code": "bad_body"})

                payload = {}
                for k, v in query.items():
                    payload[k] = v[0] if len(v) == 1 else v
                if isinstance(body, dict):
                    payload.update(body)
                payload.update(params)

                try:
                    result = route.func(payload)
                    if result is None:
                        result = {}
                    if not isinstance(result, dict):
                        result = {"result": result}
                    out = {"ok": True}
                    out.update(result)
                    return self._json(200, out)
                except ApiError as e:
                    service.counters["errors"] += 1
                    if service.log:
                        service.log.warn("api.error", route=route.route_id, error=e.message)
                    return self._json(e.status, e.as_dict())
                except Exception as exc:
                    service.counters["errors"] += 1
                    if service.log:
                        service.log.exc("api.exception", route=route.route_id, error=repr(exc))
                    return self._json(500, {"ok": False, "error": "服务端异常: %r" % exc, "code": "server_error"})

            # ---- helpers ----
            def _read_body(self):
                length = int(self.headers.get("Content-Length") or 0)
                if length <= 0:
                    return {}
                if length > service.max_bytes:
                    raise ValueError("请求体过大（>%d bytes）" % service.max_bytes)
                raw = self.rfile.read(length)
                ctype = (self.headers.get("Content-Type") or "").lower()
                if "application/json" in ctype or raw.strip().startswith(b"{"):
                    try:
                        return json.loads(raw.decode("utf-8"))
                    except ValueError as e:
                        raise ValueError("非法 JSON: %s" % e)
                if "application/x-www-form-urlencoded" in ctype:
                    data = urllib.parse.parse_qs(raw.decode("utf-8"), keep_blank_values=True)
                    return {k: (v[0] if len(v) == 1 else v) for k, v in data.items()}
                return {"_raw": raw.decode("utf-8", "ignore")}

            def _authed(self):
                token = service.token
                if not token:
                    return True
                supplied = (
                    self.headers.get("X-Auth-Token")
                    or (self.headers.get("Authorization") or "").replace("Bearer ", "").strip()
                    or self._cookie_token()
                    or urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query).get("token", [""])[0]
                )
                return bool(supplied) and secrets.compare_digest(supplied, token)

            def _cookie_token(self):
                raw = self.headers.get("Cookie") or ""
                for part in raw.split(";"):
                    if "=" in part:
                        k, v = part.split("=", 1)
                        if k.strip() == service.cookie_name:
                            return urllib.parse.unquote(v.strip())
                return ""

            def _login(self):
                try:
                    body = self._read_body()
                except ValueError as e:
                    return self._json(400, {"ok": False, "error": str(e)})
                pw = str(body.get("password") or "")
                if service.web_password and not secrets.compare_digest(pw, service.web_password):
                    service.counters["auth_fail"] += 1
                    return self._json(401, {"ok": False, "error": "密码错误"})
                token = service.ensure_token()
                cookie = "%s=%s; Path=/; HttpOnly; SameSite=Lax; Max-Age=%d" % (
                    service.cookie_name, urllib.parse.quote(token), 60 * 60 * 24 * 30,
                )
                return self._json(200, {"ok": True, "token": token}, {"Set-Cookie": cookie})

            def _serve_static(self, path):
                rel = "index.html" if path in ("/", "/index.html") else path.lstrip("/")
                if rel.startswith("static/"):
                    rel = rel[len("static/"):]
                full = os.path.normpath(os.path.join(service.web_dir, rel))
                if not full.startswith(os.path.normpath(service.web_dir)) or not os.path.isfile(full):
                    return self._json(404, {"ok": False, "error": "not found"})
                ctype = mimetypes.guess_type(full)[0] or "application/octet-stream"
                if ctype.startswith("text/") or ctype in ("application/javascript",):
                    ctype += "; charset=utf-8"
                with open(full, "rb") as f:
                    data = f.read()
                return self._send(200, data, {"Content-Type": ctype, "Cache-Control": "no-store"})

            def _json(self, status, obj, headers=None):
                data = json.dumps(obj, ensure_ascii=False, default=str).encode("utf-8")
                h = {"Content-Type": "application/json; charset=utf-8", "Cache-Control": "no-store"}
                h.update(headers or {})
                return self._send(status, data, h)

            def _send(self, status, data, headers):
                self.send_response(status)
                for k, v in headers.items():
                    self.send_header(k, v)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                if data:
                    try:
                        self.wfile.write(data)
                    except (BrokenPipeError, ConnectionResetError):
                        pass

        ThreadingHTTPServer.allow_reuse_address = True
        ThreadingHTTPServer.daemon_threads = True
        self.tls_context = self._tls_config()

        class TLSHTTPServer(ThreadingHTTPServer):
            """在 accept 之后包一层 TLS —— 比包 listening socket 稳，握手失败只影响那一条连接。"""
            tls = None

            def get_request(self):
                sock, addr = super().get_request()
                if self.tls is not None:
                    try:
                        return self.tls.wrap_socket(sock, server_side=True), addr
                    except (ssl.SSLError, OSError):
                        try:
                            sock.close()
                        except OSError:
                            pass
                        raise
                return sock, addr

        server_cls = TLSHTTPServer if self.tls_context is not None else ThreadingHTTPServer
        self._httpd = server_cls((self.host, self.port), Handler)
        if self.tls_context is not None:
            self._httpd.tls = self.tls_context
            self.scheme = "https"
        self.started_at = time.time()
        if self.log:
            self.log.info("http.listen", host=self.host, port=self.port, scheme=self.scheme, web_dir=self.web_dir)
        self._httpd.serve_forever(poll_interval=0.2)

    def start_background(self):
        self.ensure_token()
        self._thread = threading.Thread(target=self.serve_forever, name="http", daemon=True)
        self._thread.start()
        # 等端口起来，避免调用方立刻请求失败
        for _ in range(50):
            if self._httpd is not None:
                break
            time.sleep(0.05)
        return self._thread

    def stop(self):
        if self._httpd:
            self._httpd.shutdown()
            self._httpd.server_close()
            self._httpd = None

    def url(self):
        host = "127.0.0.1" if self.host in ("0.0.0.0", "::") else self.host
        return "%s://%s:%d" % (self.scheme, host, self.port)
