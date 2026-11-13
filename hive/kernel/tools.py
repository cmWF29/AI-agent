"""工具注册表与工具调用上下文。

工具不是 kernel 的私产：每个模块都可以往注册表里注册自己的工具，
React 循环只认注册表，不认具体实现 —— 这是“可插拔”的另一半。
"""
from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout

from .api import ApiError


class ToolError(Exception):
    pass


class ToolContext:
    """工具执行时能拿到的一切（也是工具唯一允许的依赖面）。"""

    def __init__(self, cfg, bus, log, session=None, api=None, registry=None):
        self.cfg = cfg
        self.bus = bus
        self.log = log
        self.session = session or {}
        self._api = api
        self.registry = registry

    @property
    def workspace(self):
        return self.session.get("workspace") or self.cfg["root"]

    @property
    def session_id(self):
        return self.session.get("id", "-")

    def api(self, route_id, **payload):
        if not self._api:
            raise ToolError("api 不可用：%s" % route_id)
        return self._api(route_id, **payload)

    def emit(self, topic, payload=None):
        return self.bus.publish(topic, payload, source="tool:%s" % self.session_id)


class Tool:
    def __init__(self, name, description, parameters, handler, timeout=None, origin="kernel", tags=None):
        self.name = name
        self.description = description
        self.parameters = parameters or {"type": "object", "properties": {}}
        self.handler = handler
        self.timeout = timeout
        self.origin = origin
        self.tags = tags or []

    def spec(self):
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


def _normalize_result(raw):
    if isinstance(raw, dict):
        text = raw.get("text")
        if text is None:
            text = str(raw)
        return {"ok": raw.get("ok", True), "text": text, "meta": raw.get("meta", {})}
    if isinstance(raw, str):
        return {"ok": True, "text": raw, "meta": {}}
    if raw is None:
        return {"ok": True, "text": "", "meta": {}}
    return {"ok": True, "text": str(raw), "meta": {}}


class ToolRegistry:
    def __init__(self, cfg=None, workers=6):
        self._tools = {}
        self._lock = threading.RLock()
        self._pool = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="tool")
        self.cfg = cfg

    def register(self, tool):
        with self._lock:
            if tool.name in self._tools:
                raise ValueError("duplicate tool: %s" % tool.name)
            self._tools[tool.name] = tool
        return tool

    def tool(self, name, description, parameters, timeout=None, origin="kernel", tags=None):
        def deco(fn):
            self.register(Tool(name, description, parameters, fn, timeout, origin, tags))
            return fn
        return deco

    def names(self):
        with self._lock:
            return sorted(self._tools.keys())

    def get(self, name):
        with self._lock:
            return self._tools.get(name)

    def specs(self):
        with self._lock:
            return [t.spec() for t in sorted(self._tools.values(), key=lambda x: x.name)]

    def execute(self, name, args, tctx, timeout=None):
        """执行一个工具调用，永远返回结构化结果，绝不抛异常给循环。"""
        tool = self.get(name)
        if tool is None:
            return {"ok": False, "text": "未知工具: %s（可用: %s）" % (name, ", ".join(self.names())), "meta": {"unknown": True}}
        limit = timeout or tool.timeout or (self.cfg["react"]["tool_timeout"] if self.cfg else 120)
        fut = self._pool.submit(self._invoke, tool, args, tctx)
        try:
            return fut.result(timeout=limit)
        except FutureTimeout:
            return {"ok": False, "text": "工具 %s 超时（>%ss）" % (name, limit), "meta": {"timeout": True}}
        except Exception as exc:
            return {"ok": False, "text": "工具 %s 异常: %r" % (name, exc), "meta": {"error": repr(exc)}}

    def _invoke(self, tool, args, tctx):
        try:
            return _normalize_result(tool.handler(args or {}, tctx))
        except ApiError as e:
            return {"ok": False, "text": "API 调用失败: %s" % e.message, "meta": {"code": e.code}}
        except ToolError as e:
            return {"ok": False, "text": "工具错误: %s" % e, "meta": {}}
        except Exception as e:
            return {"ok": False, "text": "工具执行异常: %r" % e, "meta": {"error": repr(e)}}

    def shutdown(self):
        self._pool.shutdown(wait=False, cancel_futures=True)
