"""HTTP 服务实现：stdlib ThreadingHTTPServer。"""
from __future__ import annotations

import ssl
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


def setup(ctx):
    """只建服务、绑端口，不接请求（接请求发生在 start 阶段）。"""
    host = ctx.cfg.get("server", {}).get("host", "127.0.0.1")
    port = int(ctx.cfg.get("server", {}).get("port", 8787))
    server = ThreadingHTTPServer((host, port), _make_handler(ctx))
    tls = ctx.cfg.get("server", {}).get("tls") or {}
    if tls.get("enabled") and tls.get("cert") and tls.get("key"):
        cert = str(ctx.storage.path("server.tls.cert", tls["cert"]))
        key = str(ctx.storage.path("server.tls.key", tls["key"]))
        server.socket = ssl.wrap_socket(server.socket, certfile=cert, keyfile=key, server_side=True)
    return server


def start(ctx, server):
    """装配全部完成后由组合根调用：开始接收请求。

    非 daemon：组合根返回后进程仍常驻，直到 Ctrl+C / 显式 shutdown。
    """
    threading.Thread(target=server.serve_forever, daemon=False).start()
    host, port = server.server_address[:2]
    tls = (ctx.cfg.get("server", {}) or {}).get("tls") or {}
    return server


def _make_handler(ctx):
    class _Handler(BaseHTTPRequestHandler):
        server_version = "AI_NEW/0.1"

        def log_message(self, fmt, *args):  # 请求日志走自己的 log，不用 stderr 刷屏
            pass

        def do_GET(self):
            self._route("GET")

        def do_POST(self):
            self._route("POST")

        def _route(self, method):
            parsed = urllib.parse.urlparse(self.path)
            path = parsed.path
            try:
                if path.startswith("/api/"):
                    self._api(method, path, parsed)
                else:
                    self._static(path)
            except Exception as e:  # noqa: BLE001
                self._json_error(e)

        def _api(self, method, path, parsed):
            payload = {}
            if parsed.query:
                for k, v in urllib.parse.parse_qsl(parsed.query):
                    payload[k] = v
            body = {}
            if method == "POST":
                body = self._read_json_body()
                if body is None:
                    return
                if isinstance(body, dict):
                    payload.update(body)

            # 公开面：存活探头（只回 ok/uptime，无业务数据）、登录前置、登录换票；其余走鉴权。
            public = path == "/api/health" or path == "/api/health/live" or path.startswith("/api/auth/") or (
                path == "/api/rpc/demand_engine/run" and body.get("id") == "auth-login")
            if not public:
                verdict = ctx.api.call("auth.verify", {"token": _extract_token(self)})
                if not verdict.get("allow"):
                    self._json_error(ctx.ApiError("未登录或会话已失效",
                                                  code="unauthorized", status=401))
                    return

            if path == "/api/modules":
                self._json_ok({"modules": sorted(ctx.loaded),
                               "routes": ctx.api.routes()})
                return
            if path.startswith("/api/sse/"):
                self._sse(path, parsed)
                return
            parts = [p for p in path.split("/") if p]
            # /api/<a>/<b>[/...] → 路由名 "a.b"
            if len(parts) < 3:
                self._json_error(ctx.ApiError("API 路径必须是 /api/<module>/<fn>",
                                              code="bad_path", status=404))
                return
            if parts[1] == "rpc":
                # 进程间 RPC：通道抽象的网络实现打到这里，返回未包装的原始结果
                if len(parts) < 4:
                    self._json_error(ctx.ApiError("RPC 路径必须是 /api/rpc/<module>/<fn>",
                                                  code="bad_path", status=404))
                    return
                rpc = True
                name = parts[2] + "." + parts[3]
            else:
                rpc = False
                name = parts[1] + "." + parts[2]
            result = ctx.api.call(name, payload)
            if rpc:
                self._json_ok({"result": result})
            else:
                self._json_ok(result)

        def _read_json_body(self):
            length = int(self.headers.get("Content-Length") or 0)
            if length <= 0:
                return {}
            raw = self.rfile.read(length)
            out = ctx.codec.json_decode(raw.decode("utf-8"))
            if not out.get("ok"):
                self._json_error(ctx.ApiError("请求体不是合法 JSON",
                                              code="bad_json", status=400))
                return None
            body = out["value"]
            return body if isinstance(body, dict) else {}

        def _sse(self, path, parsed):
            """流式能力：只有标了 stream 的路由能进；返回值里的 items 逐条写成 data: 帧。"""
            parts = [p for p in path.split("/") if p]
            if len(parts) < 4:
                self._json_error(ctx.ApiError("SSE 路径必须是 /api/sse/<module>/<fn>",
                                              code="bad_path", status=404))
                return
            name = parts[2] + "." + parts[3]
            route = ctx.api.route(name)
            if route is None:
                self._json_error(ctx.ApiError("API 不存在: %s" % name,
                                              code="no_route", status=404))
                return
            if not route.get("stream"):
                self._json_error(ctx.ApiError("%s 不是流式路由" % name,
                                              code="not_stream", status=400))
                return
            payload = {k: v for k, v in urllib.parse.parse_qsl(parsed.query)
                       if k not in ("token",)}
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "keep-alive")
            self.send_header("X-Accel-Buffering", "no")
            self.end_headers()
            try:
                while True:
                    result = ctx.api.call(name, payload)
                    for item in (result.get("items") or []):
                        chunk = ctx.codec.json_encode(item)
                        self.wfile.write(("data: " + chunk["text"] + "\n\n").encode("utf-8"))
                    if result.get("cursor") is not None:
                        payload["cursor"] = result["cursor"]
                    self.wfile.write(b": keep-alive\n\n")
                    self.wfile.flush()
                    ctx.api.call("clock.sleep", {"seconds": 1}, caller=None)
            except (BrokenPipeError, ConnectionResetError, OSError):
                return

        def _static(self, path):
            """静态资源归 web 模块：http 只搬字节，不认识页面内容。"""
            try:
                asset = ctx.web.asset(ctx, path.lstrip("/") or "index.html")
            except ctx.ApiError as e:
                self._json_error(e)
                return
            data = str(asset.get("content") or "").encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", asset.get("content_type") or "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _json_ok(self, obj):
            out = ctx.codec.json_encode({"ok": True, **obj} if isinstance(obj, dict) else obj)
            data = out["text"].encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _json_error(self, e):
            if isinstance(e, ctx.ApiError):
                status, code, message = e.status, e.code, e.message
            elif isinstance(e, ValueError):
                status, code, message = 400, "bad_request", str(e)
            else:
                # 没有需求订阅"http 失败"，就只能把堆栈打到 stderr：不自己记日志
                import traceback
                traceback.print_exc()
                status, code, message = 500, "internal", "internal error"
            out = ctx.codec.json_encode({"ok": False, "error": message, "code": code})
            data = out["text"].encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

    return _Handler


def _extract_token(handler):
    got = handler.headers.get("X-Auth-Token") or ""
    if not got:
        cookie = handler.headers.get("Cookie") or ""
        for part in cookie.split(";"):
            k, _, v = part.strip().partition("=")
            if k == "hive_token":
                got = v
    return got


def _content_type(suffix):
    return {
        ".html": "text/html; charset=utf-8",
        ".js": "text/javascript; charset=utf-8",
        ".css": "text/css; charset=utf-8",
        ".json": "application/json; charset=utf-8",
        ".svg": "image/svg+xml",
        ".png": "image/png",
        ".ico": "image/x-icon",
    }.get(suffix, "application/octet-stream")
