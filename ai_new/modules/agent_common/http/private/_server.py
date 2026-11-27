"""HTTP 服务实现：stdlib ThreadingHTTPServer。"""
from __future__ import annotations

import asyncio
import gzip
import ssl
import zlib
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

# GET 只留给无副作用入口；其余 /api/ 一律 POST。否则带 Cookie 的浏览器链接/图片
# 就能触发删除、归档这类写路由，形成 CSRF 之外的“GET 写”。
_GET_API = {"/api/health", "/api/health/live", "/api/health/assemble",
            "/api/modules", "/api/auth/status", "/api/auth/verify"}
# 未登录可直达的唯一入口：存活探针、登录状态、登录换票/校验、控制台壳词表。
_PUBLIC_API = {"/api/health", "/api/health/live",
               "/api/auth/login", "/api/auth/status", "/api/auth/verify"}
_PUBLIC_DEMANDS = {"auth-login", "console-chrome"}
_DEFAULT_BODY_LIMIT = 8 * 1024 * 1024
# 控制台需求入口（单条与批处理）与操作员身份：只在鉴权通过后注入，公开入口不享受。
_CONSOLE_DEMAND_API = {"/api/rpc/demand_engine/run", "/api/rpc/demand_engine/batch"}
_OPERATOR_CALLER = {"scope": "global", "role": "admin", "session": "console"}


class _Server(ThreadingHTTPServer):
    """控制台一页会并发拉起几十个静态资源，默认 backlog=5 会把跨公网的突发连接丢进重试。"""
    daemon_threads = True
    request_queue_size = 128
    tls_ctx = None

    def process_request_thread(self, request, client_address):
        """TLS 握手放进工作线程：半开连接只能占住自己，不能卡死整个 accept 队列。"""
        if self.tls_ctx is not None:
            try:
                request = self.tls_ctx.wrap_socket(request, server_side=True)
            except (ssl.SSLError, OSError):
                self.shutdown_request(request)
                return
        super().process_request_thread(request, client_address)


def setup(ctx):
    """只建服务、绑端口，不接请求（接请求发生在 start 阶段）。"""
    host = ctx.cfg.get("server", {}).get("host", "127.0.0.1")
    port = int(ctx.cfg.get("server", {}).get("port", 8787))
    server = _Server((host, port), _make_handler(ctx))
    tls = ctx.cfg.get("server", {}).get("tls") or {}
    if tls.get("enabled") and tls.get("cert") and tls.get("key"):
        cert = str(ctx.storage.path("server.tls.cert", tls["cert"]))
        key = str(ctx.storage.path("server.tls.key", tls["key"]))
        # 3.12 起 ssl.wrap_socket 已移除，只能自建上下文再包 socket（协议版本显式给 TLS）。
        tls_ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        tls_ctx.load_cert_chain(cert, key)
        # 监听 socket 保持明文；每个连接在 worker 里单独握手（见 process_request_thread）。
        server.tls_ctx = tls_ctx
    return server


def start(ctx, server):
    """装配全部完成后由组合根调用：开始接收请求。

    daemon 线程：常驻模式靠 ``_await_serve`` 的主线程等待信号保活；装配即返回的
    进程（单测/烟测/嵌入方）不应被 serve_forever 拖住解释器退出。
    """
    threading.Thread(target=server.serve_forever, daemon=True, name="http-serve").start()
    host, port = server.server_address[:2]
    tls = (ctx.cfg.get("server", {}) or {}).get("tls") or {}
    return server


def _make_handler(ctx):
    class _Handler(BaseHTTPRequestHandler):
        server_version = "AI_NEW/0.1"
        # HTTP/1.1：连接可复用。默认的 HTTP/1.0 每条响应就关连接，一个页面十来个资源
        # 就是十几次 TLS 握手；跨公网时每一次握手两个 RTT，手感就是"处处都慢半秒"。
        # 所有响应都带 Content-Length，满足 1.1 复用条件。
        protocol_version = "HTTP/1.1"
        # 小包不攒：一次 RPC 的响应只有几百字节，Nagle 会让它多等一个 ACK。
        disable_nagle_algorithm = True

        def log_message(self, fmt, *args):  # 请求日志走自己的 log，不用 stderr 刷屏
            pass

        def send_response(self, code, message=None):
            """所有响应统一带安全头：不嗅探类型、不嵌第三方框、不把带令牌的 URL 送出去。"""
            super().send_response(code, message)
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("Referrer-Policy", "no-referrer")

        def _write(self, data):
            """写响应体：客户端提前断开不是服务错误，不再向上抛成 500 或打堆栈。

            浏览器切页、SSE 被掐断、移动端弱网都会让 ``write`` 抛 BrokenPipe/
            ConnectionReset；连接已不可用，只能关掉，不能把异常再交给 ``_json_error``
            二次写响应（那会变成同一请求的第二次异常与 stderr 噪声）。
            """
            try:
                self.wfile.write(data)
                return True
            except (BrokenPipeError, ConnectionResetError, OSError):
                self.close_connection = True
                return False

        def do_GET(self):
            self._route("GET")

        def do_POST(self):
            self._route("POST")

        def _route(self, method):
            parsed = urllib.parse.urlparse(self.path)
            path = parsed.path
            try:
                if path.startswith("/api/") and method != "POST":
                    if path.startswith("/api/sse/"):
                        pass
                    elif path not in _GET_API:
                        # 405 只对“存在但只接受 POST”的路由成立；未知路径仍是 404，
                        # 不能把拼错的 API 当成方法错误，误导调用方去换动词。
                        name = _api_name(path)
                        if not name:
                            self._json_error(ctx.ApiError(
                                "API 路径形状不合法", code="bad_path", status=404))
                            return
                        if ctx.api.route(name) is None:
                            self._json_error(ctx.ApiError(
                                "API 路由不存在", code="no_route", status=404))
                            return
                        self._json_error(ctx.ApiError(
                            "写路由只接受 POST", code="method_not_allowed", status=405))
                        return
                if path.startswith("/api/"):
                    self._api(method, path, parsed)
                else:
                    self._static(path)
            except (BrokenPipeError, ConnectionResetError):
                # 客户端在响应写完前断开：连接已经不可用，不把它当服务端异常。
                self.close_connection = True
            except Exception as e:  # noqa: BLE001
                try:
                    self._json_error(e)
                except (BrokenPipeError, ConnectionResetError, OSError):
                    self.close_connection = True
            finally:
                self._drain_hooks()

        def _drain_hooks(self):
            """响应已写出：延迟 hook 派发交后台，不占请求线程等长 IO。

            优先把 drain_async 协程提交到进程事件循环后台跑（协程路由直连、不回桥接）；
            提交失败再回退同步轨。收尾任何异常都不影响已写出的响应。
            """
            hooks = getattr(ctx, "hooks", None)
            if hooks is None or not getattr(hooks, "pending", lambda: 0)():
                return
            try:
                loop = ctx.api._ensure_loop()
                asyncio.run_coroutine_threadsafe(hooks.drain_async(), loop)
            except Exception:  # noqa: BLE001 — 异步提交失败回退同步轨
                try:
                    hooks.drain()
                except Exception:  # noqa: BLE001
                    pass

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
                payload.update(body)

            # 登录节流需要真实对端地址：由传输层注入，调用方 body/query 里的 peer
            # 不可信，必须在合并后用连接地址覆盖。登录需求把 peer 透传给 auth.login。
            peer = str(self.client_address[0] or "")
            # body 恒为 dict（_read_json_body 只回 dict），无需再判类型。
            inp = body.get("input")
            if path == "/api/rpc/demand_engine/run" and body.get("id") == "auth-login" \
                    and isinstance(inp, dict):
                inp["peer"] = peer
            elif path in ("/api/auth/login", "/api/rpc/auth/login"):
                body["peer"] = peer
            if path in ("/api/auth/login", "/api/rpc/auth/login"):
                payload["peer"] = peer

            # 公开面是显式 allowlist：新增 auth 路由不会因为前缀相同自动变成匿名入口。
            public = path in _PUBLIC_API or (
                path == "/api/rpc/demand_engine/run"
                and isinstance(body.get("id"), str)
                and body.get("id") in _PUBLIC_DEMANDS)
            if not public:
                verdict = ctx.api.call("auth.verify",
                                       {"token": _extract_token(self, allow_query=path.startswith("/api/sse/"))},
                                       direct=True)
                if not verdict.get("allow"):
                    self._json_error(ctx.ApiError("未登录或会话已失效",
                                                  code="unauthorized", status=401))
                    return

            # 控制台是人来操作的全项目视图：过了鉴权就把调用方身份注入需求入参，
            # 各模块的作用域守卫才认得「这是操作员」而不是无主的空作用域。
            if not public and path in _CONSOLE_DEMAND_API:
                batches = [body.get("input"), body.get("inputs")]
                batches += list(body.get("calls") or []) if isinstance(body.get("calls"), list) else []
                for args in batches:
                    if not isinstance(args, dict):
                        continue
                    slot = args.get("input") if isinstance(args.get("input"), dict) else args
                    slot.setdefault("caller", dict(_OPERATOR_CALLER))

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
            route = ctx.api.route(name)
            if route is not None and route.get("internal"):
                self._json_error(ctx.ApiError("该能力不对外: %s" % name,
                                              code="internal_route", status=403))
                return
            result = ctx.api.call(name, payload, direct=True)
            if rpc:
                self._json_ok({"result": result})
            else:
                self._json_ok(result)

        def _read_json_body(self):
            # 不支持 chunked：不读会留下未消费字节，被当成下一条请求解析（请求走私）。
            if self.headers.get("Transfer-Encoding"):
                self._json_error(ctx.ApiError("不支持分块传输", code="bad_framing", status=400))
                self.close_connection = True
                return None
            raw_len = self.headers.get("Content-Length") or "0"
            try:
                length = int(raw_len)
            except (TypeError, ValueError):
                self._json_error(ctx.ApiError("Content-Length 非法", code="bad_framing", status=400))
                self.close_connection = True
                return None
            if length < 0:
                self._json_error(ctx.ApiError("Content-Length 非法", code="bad_framing", status=400))
                self.close_connection = True
                return None
            if length <= 0:
                return {}
            limit = int((ctx.cfg.get("server") or {}).get("max_body_bytes")
                        or _DEFAULT_BODY_LIMIT)
            if length > limit:
                self._json_error(ctx.ApiError("请求体过大", code="payload_too_large", status=413))
                self.close_connection = True
                return None
            raw = self.rfile.read(length)
            out = ctx.codec.yaml_decode(raw.decode("utf-8"))
            if not out.get("ok"):
                self._json_error(ctx.ApiError("请求体不是合法 YAML",
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
                    result = ctx.api.call(name, payload, direct=True)
                    for item in (result.get("items") or []):
                        chunk = ctx.codec.yaml_encode_flow(item)
                        if not self._write(("data: " + chunk["text"] + "\n\n").encode("utf-8")):
                            return
                    if result.get("cursor") is not None:
                        payload["cursor"] = result["cursor"]
                    if not self._write(b": keep-alive\n\n"):
                        return
                    self.wfile.flush()
                    # 事件驱动路由内部已阻塞等待；只有游标门面才需要固定节流。
                    if not result.get("blocked"):
                        ctx.api.call("clock.sleep", {"seconds": 1}, caller=None, direct=True)
            except (BrokenPipeError, ConnectionResetError, OSError):
                # 流是被对端掐断才退出的：这条连接不能再复用
                self.close_connection = True
                return

        def _static(self, path):
            """静态资源归 web 模块：http 只搬字节，不认识页面内容。

            页面级资源在鉴权前先问 web.gate：未登录直接 302 到登录页，
            不把控制台先发给浏览器再靠前端 401 跳转。
            """
            rel = path.lstrip("/") or "manage.html"
            gate = ctx.api.call("web.gate", {"path": rel}, caller=None, direct=True)
            if not gate.get("public"):
                verdict = ctx.api.call("auth.verify", {"token": _extract_token(self)},
                                       caller=None, direct=True)
                if not verdict.get("allow"):
                    self.send_response(302)
                    self.send_header("Location", "/" + (gate.get("to") or "login.html"))
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
            try:
                asset = ctx.web.asset(ctx, path.lstrip("/") or "manage.html")
            except ctx.ApiError as e:
                self._json_error(e)
                return
            raw = str(asset.get("content") or "").encode("utf-8")
            # 合成包路径不变、内容会变：只能靠校验。ETag 按未压缩字节算，
            # 命中就回 304，客户端不用重下几 KB，也不至于拿到旧 JS。
            etag = '"%x-%x"' % (zlib.crc32(raw), len(raw))
            cache = ("no-cache" if (asset.get("no_cache") or Path(rel).suffix == ".html")
                     else "public, max-age=300")
            if self.headers.get("If-None-Match") == etag:
                self.send_response(304)
                self.send_header("ETag", etag)
                self.send_header("Cache-Control", cache)
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            data, zipped = self._zip(raw)
            self.send_response(200)
            self.send_header("Content-Type", asset.get("content_type") or "text/plain; charset=utf-8")
            self.send_header("ETag", etag)
            self.send_header("Cache-Control", cache)
            if zipped:
                self.send_header("Content-Encoding", "gzip")
                self.send_header("Vary", "Accept-Encoding")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self._write(data)

        def _zip(self, data):
            """传输编码不是业务：客户端说能收 gzip 就把大响应压了再发，页面首屏才跟得上。

            压缩门限走配置，小响应不白付压缩开销。
            """
            floor = int(ctx.api.call("config.get", {"key": "web.gzip_min_bytes"},
                                     caller=None, direct=True).get("value") or 0)
            if len(data) < floor:
                return data, False
            if "gzip" not in (self.headers.get("Accept-Encoding") or "").lower():
                return data, False
            return gzip.compress(data, 6), True

        def _json_ok(self, obj):
            out = ctx.codec.yaml_encode_flow({"ok": True, **obj} if isinstance(obj, dict) else obj)
            data = out["text"].encode("utf-8")
            data, zipped = self._zip(data)
            self.send_response(200)
            self.send_header("Content-Type", "application/yaml; charset=utf-8")
            if zipped:
                self.send_header("Content-Encoding", "gzip")
                self.send_header("Vary", "Accept-Encoding")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self._write(data)

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
            out = ctx.codec.yaml_encode_flow({"ok": False, "error": message, "code": code})
            data = out["text"].encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/yaml; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self._write(data)

    return _Handler


def _api_name(path):
    """把 /api/<a>/<b>[/...] 折成路由名；形状不对返回空串。RPC 走 /api/rpc/<module>/<fn>。"""
    parts = [p for p in path.split("/") if p]
    if len(parts) < 3 or parts[0] != "api":
        return ""
    if parts[1] == "rpc":
        return parts[2] + "." + parts[3] if len(parts) >= 4 else ""
    return parts[1] + "." + parts[2]


def _extract_token(handler, allow_query=False):
    got = handler.headers.get("X-Auth-Token") or ""
    if not got:
        cookie = handler.headers.get("Cookie") or ""
        for part in cookie.split(";"):
            k, _, v = part.strip().partition("=")
            if k == "hive_token":
                got = v
    # EventSource 不能设请求头，只有 SSE 允许把 token 放 query；普通 API 拒绝，
    # 免得令牌落进访问日志、Referer 或浏览器历史。
    if not got and allow_query:
        query = urllib.parse.parse_qs(urllib.parse.urlparse(handler.path).query)
        got = (query.get("token") or [""])[0]
    return got
