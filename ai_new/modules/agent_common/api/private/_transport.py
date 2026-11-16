"""通信是抽象：直接调用 / 内存队列 / 网络，同一份模板代码，不同运行时。

模块里写的永远是 `ctx.api.call(route, payload, caller)`。这条调用走哪条通道，
不由代码决定，由**脚本生成的** `data/gen/bindings.json` 决定：

    tools/gen_transport.py  读调用图 + data/deploy.json  →  data/gen/bindings.json

于是"代码是模板，真的运行是另一套代码"成了结构：模板不动，换部署拓扑只重跑生成器。
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
                "routes": len(routes),
                "source": "data/gen/bindings.yaml" if self.bindings() else "未生成，全直连"}

    # ---- 派发 ----
    def send(self, route, payload, handler, caller=None):
        kind, base = self.kind_for(route)
        if kind == "direct":
            return handler(self.ctx, payload or {})
        if kind == "memory":
            return self._enqueue(route, payload, handler)
        if kind == "http":
            return self._http(route, payload, base)
        raise self.ctx.ApiError("未知通信通道: %s (route %s)" % (kind, route),
                                code="bad_transport", status=500)

    # 通道一：内存 —— 异步投递，调用方拿到的是"已入队"
    def _enqueue(self, route, payload, handler):
        self._queue.put((route, dict(payload or {}), handler))
        if self._worker is None:
            self._worker = threading.Thread(target=self._drain, daemon=True,
                                            name="api-memory-transport")
            self._worker.start()
        return {"transport": "memory", "queued": route}

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
    def _http(self, route, payload, base):
        if not base:
            raise self.ctx.ApiError("通道 http 缺少 base: %s" % route,
                                    code="bad_transport", status=500)
        url = base.rstrip("/") + "/api/rpc/" + route.replace(".", "/")
        body = self.ctx.codec.yaml_encode_flow(payload or {})["text"].encode("utf-8")
        req = urllib.request.Request(url, data=body, method="POST",
                                     headers={"Content-Type": "application/yaml"})
        token = (self.ctx.cfg.get("server") or {}).get("token") or ""
        if token:
            req.add_header("X-Auth-Token", token)
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                rec = self.ctx.codec.yaml_decode(resp.read().decode("utf-8"))["value"]
        except (urllib.error.URLError, Exception) as exc:
            raise self.ctx.ApiError("远程调用失败: %s (%s)" % (route, exc),
                                    code="remote_error", status=502)
        if not rec.get("ok"):
            raise self.ctx.ApiError("远程调用被拒: %s %s" % (route, rec.get("error")),
                                    code="remote_error", status=502)
        return rec.get("result")
