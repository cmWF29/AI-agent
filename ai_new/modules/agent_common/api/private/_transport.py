"""通信是抽象：直接调用 / 内存队列 / 网络，同一份模板代码，不同运行时。

模块里写的永远是 `ctx.api.call(route, payload, caller)`。这条调用走哪条通道，
不由代码决定，由**编译出来的** `data/gen/bindings.yaml` 决定：

    部署意图 data/deploy.yaml  ──编译──▶  data/gen/bindings.yaml

编译是 api 模块自己的能力：装配期自动编一次（boot），也可以 `--compile-transport`
在装配之前编，或运行中调 `api.transport_compile`。于是"代码是模板，真的运行是另一套
绑定"成了结构：模板不动，换部署拓扑只重跑编译。

三条通道的语义要显式区分，不能混：
    direct  同进程直连，有返回值 —— 单机默认
    memory  同进程共享内存队列，**单向**：调用方拿到的是"已入队"，不是结果
    http    本地 / 跨机网络 RPC，有返回值 —— 多机部署的同一套绑定

没有绑定文件时默认全直连 —— 单进程里跑，和以前完全一样。
"""
from __future__ import annotations

import queue
import threading
import urllib.error
import urllib.request


class Transport:
    def __init__(self, ctx):
        self.ctx = ctx
        self._bindings = None
        self._queue = queue.Queue()
        self._worker = None

    # ---- 绑定（懒加载：装配早期还没有 storage）----
    def bindings(self):
        if self._bindings is None:
            md = self.ctx.storage.own(__file__)
            raw = md.read_text("gen/bindings.yaml") if md.exists("gen/bindings.yaml") else "{}"
            self._bindings = (self.ctx.codec.yaml_decode(raw or "{}")["value"] or {})
        return self._bindings

    def reload(self):
        self._bindings = None

    def kind_for(self, route):
        routes = self.bindings().get("routes") or {}
        item = routes.get(route) or routes.get(route.split(".")[0] + ".*")
        if item is None:
            return (self.bindings().get("default") or {}).get("kind") or "direct", None
        return item.get("kind") or "direct", item.get("base")

    def describe(self):
        routes = self.bindings().get("routes") or {}
        return {"default": (self.bindings().get("default") or {}).get("kind") or "direct",
                "routes": routes,
                "source": "data/gen/bindings.yaml" if self.bindings() else "未生成，全直连"}

    def _timeout(self):
        api = (getattr(self.ctx, "cfg", None) or {}).get("api") or {}
        try:
            return int(api.get("transport_timeout") or 10)
        except (TypeError, ValueError):
            return 10

    # ---- 派发：要返回值 ----
    def send(self, route, payload, handler, caller=None):
        kind, base = self.kind_for(route)
        if kind == "direct":
            return handler(self.ctx, payload or {})
        if kind == "http":
            return self._http(route, payload, base)
        if kind == "memory":
            raise self.ctx.ApiError(
                "内存通道是单向的（%s 要返回值）：需求里改用 send，或把该模块绑回 direct/http" % route,
                code="bad_transport", status=500)
        raise self.ctx.ApiError("未知通信通道: %s (route %s)" % (kind, route),
                                code="bad_transport", status=500)

    # ---- 派发：单向通知（不要返回值）----
    def notify(self, route, payload, handler, caller=None):
        kind, base = self.kind_for(route)
        if kind == "direct":
            handler(self.ctx, payload or {})
            return {"transport": "direct", "sent": route}
        if kind == "memory":
            self._queue.put((route, dict(payload or {}), handler))
            if self._worker is None:
                self._worker = threading.Thread(target=self._drain, daemon=True,
                                                name="api-memory-transport")
                self._worker.start()
            return {"transport": "memory", "queued": route}
        if kind == "http":
            self._http(route, payload, base, notify=True)
            return {"transport": "http", "sent": route}
        raise self.ctx.ApiError("未知通信通道: %s (route %s)" % (kind, route),
                                code="bad_transport", status=500)

    def _drain(self):
        while True:
            route, payload, handler = self._queue.get()
            try:
                handler(self.ctx, payload)
            except Exception:  # noqa: BLE001 —— 投递失败不改变发起方状态
                pass
            finally:
                self._queue.task_done()

    # 通道二：网络 —— 同步 RPC，走 /api/rpc/<module>/<fn>（返回未包装的原始结果）
    def _http(self, route, payload, base, notify=False):
        if not base:
            raise self.ctx.ApiError("通道 http 缺少 base: %s" % route,
                                    code="bad_transport", status=500)
        url = base.rstrip("/") + "/api/rpc/" + route.replace(".", "/")
        body = self.ctx.codec.yaml_encode_flow(payload or {})["text"].encode("utf-8")
        req = urllib.request.Request(url, data=body, method="POST",
                                     headers={"Content-Type": "application/yaml"})
        token = (getattr(self.ctx, "cfg", None) or {}).get("server", {}).get("token") or ""
        if token:
            req.add_header("X-Auth-Token", token)
        try:
            with urllib.request.urlopen(req, timeout=self._timeout()) as resp:
                rec = self.ctx.codec.yaml_decode(resp.read().decode("utf-8"))["value"]
        except (urllib.error.URLError, Exception) as exc:
            raise self.ctx.ApiError("远程调用失败: %s (%s)" % (route, exc),
                                    code="remote_error", status=502)
        if not rec.get("ok"):
            raise self.ctx.ApiError("远程调用被拒: %s %s" % (route, rec.get("error")),
                                    code="remote_error", status=502)
        return {"transport": "http", "sent": route} if notify else rec.get("result")
