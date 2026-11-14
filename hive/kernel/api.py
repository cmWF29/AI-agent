"""模块 API 框架。

一个模块 = 一组具名的 HTTP 路由 + 自己的事件订阅 + 自己的存储。
模块之间同步调用必须走 ctx.api(route_id, **payload)，也就是说“对外 API”就是全部。

route_id 形如 "sessions.get"、"tickets.create"，由 模块名.函数名 组成。
"""
from __future__ import annotations

import re
import sys
import time
from collections import defaultdict


class ApiError(Exception):
    def __init__(self, message, status=400, code="bad_request"):
        super().__init__(message)
        self.message = message
        self.status = status
        self.code = code

    def as_dict(self):
        return {"ok": False, "error": self.message, "code": self.code, "status": self.status}


class Route:
    __slots__ = ("method", "path", "name", "func", "auth", "module", "regex", "params", "route_id")

    def __init__(self, method, path, name, func, auth, module):
        self.method = method.upper()
        self.path = path
        self.name = name
        self.func = func
        self.auth = auth
        self.module = module
        self.route_id = "%s.%s" % (module, name)
        parts = []
        self.params = []
        for seg in path.strip("/").split("/"):
            m = re.fullmatch(r"\{([A-Za-z_][A-Za-z0-9_]*)\}", seg)
            if m:
                self.params.append(m.group(1))
                parts.append(r"(?P<%s>[^/]+)" % m.group(1))
            else:
                parts.append(re.escape(seg))
        self.regex = re.compile("^/" + "/".join(parts) + r"$")


class Api:
    """模块持有的路由集合，用 @api.route 装饰器注册。"""

    def __init__(self, module_name, owner):
        self.module_name = module_name
        self.owner = owner
        self.routes = []

    def route(self, method, path, name=None, auth=True):
        def deco(fn):
            self.routes.append(Route(method, path, name or fn.__name__, fn, auth, self.module_name))
            return fn
        return deco

    def all(self):
        return list(self.routes)


class Router:
    def __init__(self):
        self._routes = []
        self._by_id = {}
        self._modules = {}

    def mount(self, module, api):
        for route in api.all():
            if route.route_id in self._by_id:
                raise ValueError("duplicate route id: %s" % route.route_id)
            self._routes.append(route)
            self._by_id[route.route_id] = route
        self._modules[module.name] = module

    def match(self, method, path):
        method = method.upper()
        for route in self._routes:
            if route.method != method:
                continue
            m = route.regex.match(path)
            if m:
                return route, m.groupdict()
        return None, {}

    def by_id(self, route_id):
        return self._by_id.get(route_id)

    def list(self):
        return [
            {"id": r.route_id, "method": r.method, "path": r.path, "auth": r.auth}
            for r in self._routes
        ]

    def module_names(self):
        return sorted(self._modules.keys())


class Module:
    """所有模块的基类。

    约定：
      * setup()     只做自己的初始化、订阅事件、注册工具/路由；
      * shutdown()  只清理自己的资源；
      * 不 import 其它模块，需要数据时用 self.ctx.api("<module>.<route>", ...)。
    """

    name = "module"

    def __init__(self, ctx):
        self.ctx = ctx
        self.api = Api(self.name, self)
        self.log = ctx.log
        self.bus = ctx.bus
        self.cfg = ctx.cfg

    def setup(self):
        pass

    def shutdown(self):
        pass

    def emit(self, topic, payload=None):
        return self.bus.publish(topic, payload, source=self.name)

    def __repr__(self):
        return "<Module %s>" % self.name


class Context:
    def __init__(self, cfg, bus, log, router=None):
        self.cfg = cfg
        self.bus = bus
        from .hub import Hub
        self.hub = Hub(bus)
        self.log = log
        self.router = router or Router()
        self.modules = {}
        self.tools = None                 # ToolRegistry，由 kernel 装配
        self.state = {}
        self.trace = None                 # Trace，由 kernel 注入（记录模块间 API 通信）
        self.started_at = None

    def register(self, module):
        """装配一个模块：先 setup（模块在此注册路由/工具/订阅），再挂路由。"""
        self.modules[module.name] = module
        module.setup()
        self.router.mount(module, module.api)
        for route in module.api.all():
            self.hub.register_route(route.route_id, route.func, module.name)
        if self.log:
            self.log.debug("module.registered", module=module.name, routes=len(module.api.all()))
        return module

    def get(self, name):
        return self.modules.get(name)

    def api(self, route_id, **payload):
        """跨模块同步查询：经统一通信中枢 request/reply，不认识对方模块对象。

        同时把“谁调了谁、入参出参”记进 trace（需求 19：模块间通信要可视化）。
        """
        if self.router.by_id(route_id) is None:
            raise ApiError("unknown route: %s" % route_id, status=404, code="no_route")
        t0 = time.time()
        try:
            result = self.hub.request(route_id, payload)
        except ApiError as exc:
            self._trace_api(route_id, payload, None, int((time.time() - t0) * 1000), error=exc.message)
            raise
        self._trace_api(route_id, payload, result, int((time.time() - t0) * 1000))
        return result

    def _trace_api(self, route_id, payload, result, ms, error=""):
        trace = self.trace
        if trace is None:
            return
        try:
            caller = ""
            frame = sys._getframe(2)
            caller = (frame.f_globals.get("__name__") or "").rsplit(".", 1)[-1]
            trace.record("api.call", {
                "caller": caller, "from": caller, "route": route_id, "ms": ms,
                "payload": payload, "result": result, "error": error,
            }, session=payload.get("session") or payload.get("session_id") or "",
               ticket=payload.get("ticket") or "")
        except Exception:
            pass

    def shutdown(self):
        for name in reversed(list(self.modules.keys())):
            try:
                self.modules[name].shutdown()
            except Exception as exc:
                if self.log:
                    self.log.error("module.shutdown.error", module=name, error=repr(exc))
