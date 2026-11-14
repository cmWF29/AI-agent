"""模块 API 框架。

一个模块 = 一组具名的 HTTP 路由 + 自己的事件订阅 + 自己的存储。
模块只提供自己的能力；跨模块同步关系必须走 ctx.rule(rule_id, ...)，
实际 peer 路由由 data/rules/catalog.json 的规则步骤决定。
ctx.api 只用于模块自己的路由或 rules 模块执行规则。
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
      * setup()     只做自己的初始化、注册事件订阅、注册工具/路由；
      * shutdown()  只清理自己的资源；
      * 不 import 其它模块；跨模块关系用 self.ctx.rule("规则 id", ...)，
        事件订阅用 self.event("事件规则 id", handler)，不直接调对方模块 API。
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

    def event(self, event_id, handler, name=""):
        """登记本模块对某条事件规则的订阅；由 rules 模块在装配末尾统一绑定。"""
        return self.ctx.event(event_id, handler, source=self.name, name=name)

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
        self.event_subscriptions = []       # setup 阶段登记，rules 模块最后统一绑定

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

    @staticmethod
    def _caller_module(depth=1):
        try:
            frame = sys._getframe(depth)
            name = frame.f_globals.get("__name__") or ""
            parts = name.split(".")
            if len(parts) >= 3 and parts[0] == "hive" and parts[1] == "modules":
                return parts[2]
        except Exception:
            pass
        return ""

    def rule(self, rule_id, **payload):
        """按规则 ID 执行跨模块业务关系。

        模块不认识对方模块，只认识“规则”。规则目录（data/rules/catalog.json）
        才是关系的唯一来源；实际 peer API 调用发生在 rules 模块里。
        """
        t0 = time.time()
        caller = self._caller_module(2)
        try:
            result = self.hub.request("rules.run", {
                "rule": rule_id, "payload": payload, "source": caller,
            })
        except ApiError as exc:
            self._trace_rule(rule_id, payload, None, int((time.time() - t0) * 1000),
                             caller=caller, error=exc.message)
            raise
        self._trace_rule(rule_id, payload, result, int((time.time() - t0) * 1000), caller=caller)
        return result

    def event(self, event_id, handler, source="", name=""):
        """登记模块对事件关系的订阅，不在模块里写死 topic。

        rules 模块装配完成后按 catalog.json 的 events 解析 topic 并调用
        bus.subscribe；这样事件关系也能被规则面板和静态门禁看到。
        """
        if not event_id:
            raise ApiError("事件订阅缺少 event id", status=400, code="event_required")
        for sub in self.event_subscriptions:
            if sub["event"] == event_id and sub["source"] == source:
                raise ApiError("重复订阅事件规则: %s" % event_id, status=409, code="event_duplicate")
        self.event_subscriptions.append({
            "event": event_id, "source": source, "handler": handler,
            "name": name or event_id,
        })
        return event_id

    def _trace_rule(self, rule_id, payload, result, ms, caller="", error=""):
        trace = self.trace
        if trace is None:
            return
        try:
            trace.record("rule.call", {
                "caller": caller, "from": caller, "rule": rule_id, "ms": ms,
                "payload": payload, "result": result, "error": error,
            }, session=payload.get("session") or payload.get("session_id") or "",
               ticket=payload.get("ticket") or payload.get("ticket_id") or "")
        except Exception:
            pass

    def api(self, route_id, **payload):
        """执行一条已注册路由（模块自身路由，或 rules 模块的规则步骤）。

        业务模块不得用本方法直接调另一个业务模块；跨模块关系统一走 rule()。
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
