"""API 注册表实现。

- 路由名约定 "module.fn"；
- 跨模块调用必须命中 data/rules/calls.json 的矩阵（caller → 允许的路由列表）；
- 由 http/tests/组合根发起的调用 caller=None，视为系统调用，直接放行；
- handler 统一签名 fn(ctx, payload)；
- **调用走哪条通道不在这里定**：交给 Transport（直连 / 内存 / 网络，绑定由脚本生成）。

调用矩阵 **懒加载**：装配期 config 还没装填 cfg，此时读数据目录会拿到错误路径。
"""
from __future__ import annotations

import asyncio
import threading

import yaml

from . import _transport


class Registry:
    def __init__(self, ctx):
        self.ctx = ctx
        self._routes = {}
        self._matrix = None      # 首次真正调用时再读，见 _rules()
        self.transport = _transport.Transport(ctx)
        self._loop = None
        self._loop_lock = threading.Lock()

    def _ensure_loop(self):
        """进程级事件循环：惰性建在专属守护线程上，供同步壳桥接异步路由。"""
        if self._loop is None:
            with self._loop_lock:
                if self._loop is None:
                    loop = asyncio.new_event_loop()
                    t = threading.Thread(target=loop.run_forever, daemon=True,
                                         name="api-loop")
                    t.start()
                    self._loop = loop
        return self._loop

    def _adapt(self, fn):
        """传输层统一以 handler(ctx, payload) 调用；单参新签名在这里包成两参。"""
        import inspect
        params = [p for p in inspect.signature(fn).parameters.values()
                  if p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD, p.VAR_POSITIONAL)]
        required = [p for p in params if p.default is inspect.Parameter.empty]
        if len(required) >= 2:
            return fn
        return lambda ctx, payload: fn(payload)

    def register(self, name, fn, doc="", module=None, stream=False, internal=False):
        """注册路由。

        stream=True 表示"返回 {items, cursor}"，可以被 http 当 SSE 长流读。
        internal=True 表示只给进程内调用，HTTP 通道一律不放行（起进程这类能力不能远程可调）。
        """
        if name in self._routes:
            raise ValueError("route already registered: " + name)
        self._routes[name] = {"fn": self._adapt(fn),
                              "is_async": asyncio.iscoroutinefunction(fn),
                              "doc": doc, "module": module or name.split(".")[0],
                              "stream": bool(stream), "internal": bool(internal)}
        return name

    def substitute(self, name, fn):
        """替换同一条路由的实现（契约不变）：通信方式可换，调用方无感。"""
        if name not in self._routes:
            raise ValueError("route not registered: " + name)
        self._routes[name]["fn"] = self._adapt(fn)
        self._routes[name]["is_async"] = asyncio.iscoroutinefunction(fn)
        return name

    def routes(self):
        return [
            {"name": name, "doc": r["doc"], "module": r["module"], "stream": r["stream"]}
            for name, r in sorted(self._routes.items())
            if not r.get("internal")
        ]

    def route(self, name):
        """按名取一条路由（不存在返回 None）。"""
        return self._routes.get(name)

    def _rules(self):
        """矩阵是通信层的装配参数，不经过"存储→编解码"的服务链：
        那条链本身要靠矩阵放行，绕回去就是环。"""
        if self._matrix is None:
            md = self.ctx.storage.own(__file__)
            text = md.read_text("calls.yaml") if md.exists("calls.yaml") else "{}"
            self._matrix = yaml.safe_load(text or "{}")
        return self._matrix

    def matrix(self):
        return self._rules()

    def _route(self, name, caller):
        if name not in self._routes:
            raise self.ctx.ApiError("API 不存在: %s" % name, code="no_route", status=404)
        if caller and caller != "demand_engine":
            # 能力只对需求开放：模块自己不许伸手，组合一律写成需求
            raise self.ctx.ApiError(
                "能力只能由需求调用: %s -> %s" % (caller, name),
                code="module_call_forbidden", status=403)
        return self._routes[name]

    def call(self, name, payload=None, caller=None):
        """同步入口：异步路由经进程级 loop 桥接，同步路由走传输通道。"""
        route = self._route(name, caller)
        handler = route["fn"]
        if route["is_async"]:
            fut = asyncio.run_coroutine_threadsafe(
                handler(self.ctx, payload or {}), self._ensure_loop())
            return fut.result()
        return self.transport.send(name, payload, handler, caller=caller)

    async def acall(self, name, payload=None, caller=None):
        """异步入口：异步路由直接 await；同步路由丢默认执行器桥接。"""
        route = self._route(name, caller)
        handler = route["fn"]
        if route["is_async"]:
            return await handler(self.ctx, payload or {})
        return await self._ensure_loop().run_in_executor(
            None, handler, self.ctx, payload or {})


def _match(name, allowed):
    import fnmatch
    for pattern in allowed:
        if pattern == "*" or fnmatch.fnmatchcase(name, pattern):
            return True
    return False
