"""运行设施实现：效果执行 + 后台驱动。

两条不变量：
1. 只有这里写盘。能力交出 effect，需求调 apply，落到 store 的写路由。
2. 只有这里驱动别的需求。能力交出 demand effect，同样由 apply 执行。
"""
from __future__ import annotations

import threading

STORE_ROUTES = {
    "write": "store.write",
    "remove": "store.remove",
    "remove_dir": "store.remove_dir",
    "append_text": "store.append_text",
    "archive": "store.archive",
    "write_text": "store.write_text",
    "write_bytes": "store.write_bytes",
}


class Runtime:
    def __init__(self, ctx):
        self.ctx = ctx
        self._runs = {}
        self._cancel = {}
        self._stream = {}
        self._lock = threading.Lock()

    def cancelled(self, key, since):
        """同一把钥匙上，since 之后有没有人置过打断位。"""
        return (self._cancel.get(str(key or "")) or 0) > (since or 0)

    # ---- 运行期草稿：内存面，不落盘。进程边跑边吐的正文先攒在这里，定稿后清掉 ----

    def stream_put(self, key, text):
        if not key or text is None:
            return
        with self._lock:
            slot = self._stream.setdefault(str(key), {"text": "", "at": self._now()})
            slot["text"] += str(text)
            slot["at"] = self._now()

    def stream_get(self, key):
        if not key:
            return {"text": "", "running": False}
        with self._lock:
            slot = self._stream.get(str(key))
            if not slot:
                return {"text": "", "running": False}
            return {"text": slot["text"], "running": True, "at": slot["at"]}

    def stream_clear(self, key):
        if not key:
            return
        with self._lock:
            self._stream.pop(str(key), None)

    def call(self, demand, data=None):
        """同步跑一条需求并拿结果：能力的批量动作里，单次动作仍是一条需求。"""
        resp = self.ctx.api.call("demand_engine.run",
                                 {"id": demand, "input": data or {}}, caller=None) or {}
        return resp.get("result") or {}

    def _now(self):
        return (self.ctx.api.call("clock.now", {}, caller=None) or {}).get("ts") or 0

    def apply(self, payload):
        """照单执行：单个 effect、或一串 effect，空则什么都不做。"""
        raw = (payload or {}).get("effect")
        items = raw if isinstance(raw, list) else ([raw] if raw else [])
        applied = []
        for item in items:
            applied.append(self._one(item or {}))
        echo = (payload or {}).get("echo")
        if isinstance(echo, dict):
            echo["applied"] = applied
            return echo
        return {"ok": True, "applied": applied, "count": len(applied), "skipped": not items}

    def _one(self, effect):
        kind = effect.get("kind")
        if kind == "demand":
            return self.ctx.api.call("demand_engine.run", {
                "id": effect.get("id"), "input": effect.get("input") or {}}, caller=None)
        if kind == "dispatch":
            return self.dispatch({"demand": effect.get("id"),
                                   "key": effect.get("key"),
                                   "input": effect.get("input") or {}})
        route = STORE_ROUTES.get(kind)
        if not route:
            return {"ok": False, "code": "unknown_effect", "kind": kind}
        body = {k: v for k, v in effect.items() if k != "kind"}
        return self.ctx.api.call(route, body, caller=None)

    def dispatch(self, payload):
        """后台跑一轮。已在跑就置打断位，等它自己收尾（已产出的会落盘），再开新一轮。"""
        demand = (payload or {}).get("demand") or ""
        if not demand:
            return {"ok": False, "code": "no_demand"}
        key = str((payload or {}).get("key") or demand)
        data = (payload or {}).get("input") or {}
        with self._lock:
            prev = self._runs.get(key)
        interrupted = bool(prev and prev.is_alive())
        slot = {}

        def work():
            if prev and prev.is_alive():
                self._cancel[key] = self._now()
                prev.join()
            with self._lock:
                if self._runs.get(key) is not slot.get("t"):
                    return          # 后面又有人接管，这一棒作废，避免并发跑两轮
            self.ctx.api.call("demand_engine.run", {"id": demand, "input": data}, caller=None)

        thread = threading.Thread(target=work, name="rt-%s" % key, daemon=True)
        slot["t"] = thread
        with self._lock:
            self._runs[key] = thread
        thread.start()
        return {"ok": True, "key": key, "status": "running", "interrupted": interrupted}
