"""统一通信中枢：跨模块只允许通过这里通信。

两层语义：
  * 发现层：低频全局广播，例如 project:mounted，携带实例与挂载容器。
  * 运行层：实例单播，例如 project:<id>:renamed，只投递给订阅该实例的模块。
  * 查询层：request/reply。调用方只知道 route_id 与 payload，不引用对方实现。

底层目前是进程内总线；替换成网络/共享内存时只改本文件，模块代码不变。
"""
from __future__ import annotations

import threading

from .api import ApiError


class Hub:
    def __init__(self, bus):
        self.bus = bus
        self._services = {}
        self._lock = threading.RLock()

    # ---------------- 请求 / 响应 ----------------
    def register_route(self, route_id, handler, module=""):
        with self._lock:
            if route_id in self._services:
                raise ValueError("duplicate service: %s" % route_id)
            self._services[route_id] = {"handler": handler, "module": module}
        return route_id

    def request(self, route_id, payload=None, source=""):
        """同步请求：只通过中枢寻址，不 import、不持有对方模块对象。"""
        with self._lock:
            svc = self._services.get(route_id)
        if svc is None:
            raise ApiError("unknown service: %s" % route_id, status=404, code="no_service")
        envelope = {"route": route_id, "source": source,
                    "payload": payload if payload is not None else {}}
        result = svc["handler"](envelope["payload"])
        return {} if result is None else result

    def services(self):
        with self._lock:
            return [{"route": k, "module": v["module"]} for k, v in sorted(self._services.items())]

    # ---------------- 事件 ----------------
    def publish(self, topic, payload=None, source=""):
        return self.bus.publish(topic, payload or {}, source=source)

    def subscribe(self, pattern, handler, name=""):
        return self.bus.subscribe(pattern, handler, name=name)

    def unsubscribe(self, sid):
        return self.bus.unsubscribe(sid)

    @staticmethod
    def instance_topic(domain, instance_id, action):
        return "%s:%s:%s" % (domain, instance_id, action)

    def publish_instance(self, domain, instance_id, action, payload=None, source=""):
        return self.publish(self.instance_topic(domain, instance_id, action),
                            payload or {}, source=source)

    def subscribe_instance(self, domain, instance_id, action, handler, name=""):
        return self.subscribe(self.instance_topic(domain, instance_id, action), handler, name=name)

    def mount(self, domain, instance_id, container_id, source=""):
        """发现阶段广播：实例已挂载，其他模块可按需绑定自己的渲染。"""
        payload = {"instanceId": instance_id, "mountContainerId": container_id}
        if domain == "project":
            payload["projectId"] = instance_id
        return self.publish("%s:mounted" % domain, payload, source=source)
