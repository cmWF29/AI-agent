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
        self._subs = {}   # 草稿槽订阅：key -> [threading.Event]，槽变化即唤醒等待方
        self._lock = threading.Lock()

    def cancelled(self, key, since):
        """同一把钥匙上，since 之后有没有人置过打断位。"""
        return (self._cancel.get(str(key or "")) or 0) > (since or 0)

    def stop(self, key):
        """置打断位并等同一把钥匙上的后台线程收尾；不在跑就直接返回。

        硬删会话文件前先 stop：等线程退出后再落删除 effect，避免定稿落盘把文件写回。
        """
        key = str(key or "")
        if not key:
            return {"ok": False, "code": "no_key"}
        with self._lock:
            self._cancel[key] = self._now()
            thread = self._runs.get(key)
        if thread and thread.is_alive():
            thread.join()
        with self._lock:
            self._runs.pop(key, None)
            self._cancel.pop(key, None)
        return {"ok": True, "key": key}

    # ---- 运行期草稿：内存面，不落盘。进程边跑边吐的正文先攒在这里，定稿后清掉 ----

    def stream_put(self, key, text):
        if not key or text is None:
            return
        with self._lock:
            slot = self._stream.setdefault(str(key), {"text": "", "at": self._now()})
            slot["text"] += str(text)
            slot["at"] = self._now()
            subs = list(self._subs.get(str(key), ()))
        for ev in subs:
            ev.set()

    def stream_get(self, key):
        if not key:
            return {"text": "", "running": False, "at": 0}
        with self._lock:
            slot = self._stream.get(str(key))
            if not slot:
                return {"text": "", "running": False, "at": 0}
            return {"text": slot["text"], "running": True, "at": slot["at"]}

    def stream_clear(self, key):
        if not key:
            return
        with self._lock:
            self._stream.pop(str(key), None)
            subs = list(self._subs.get(str(key), ()))
        for ev in subs:
            ev.set()

    def stream_subscribe(self, key):
        """登记一个等待事件；返回 Event，槽变化时被唤醒。"""
        if not key:
            return None
        ev = threading.Event()
        with self._lock:
            self._subs.setdefault(str(key), []).append(ev)
        return ev

    def stream_unsubscribe(self, key, ev):
        if not key or ev is None:
            return
        with self._lock:
            lst = self._subs.get(str(key))
            if lst and ev in lst:
                lst.remove(ev)

    def stream_events(self, key, cursor=None, timeout=15):
        """阻塞等待草稿槽变化：先对齐当前快照，无变化再阻塞等事件；醒后回最新快照。"""
        key = str(key or "")
        ev = self.stream_subscribe(key)
        try:
            snap = self.stream_get(key)
            at = snap.get("at")
            if cursor is not None and at == cursor and ev is not None:
                ev.wait(timeout=timeout)
                snap = self.stream_get(key)
                at = snap.get("at")
            if cursor is None or at != cursor:
                return {"items": [snap], "cursor": at, "blocked": True}
            return {"items": [], "cursor": cursor, "blocked": True}
        finally:
            self.stream_unsubscribe(key, ev)

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
        try:
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
        except Exception as exc:  # noqa: BLE001 —— 单条 effect 失败不掀翻整串，记成失败结果交上层兜底
            return {"ok": False, "code": "apply_error", "kind": kind, "error": str(exc)}

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
            try:
                if prev and prev.is_alive():
                    self._cancel[key] = self._now()
                    prev.join()
                with self._lock:
                    if self._runs.get(key) is not slot.get("t"):
                        return          # 后面又有人接管，这一棒作废，避免并发跑两轮
                self.ctx.api.call("demand_engine.run", {"id": demand, "input": data}, caller=None)
            finally:
                # 本棒收尾（跑完/报错/被接管作废）即自清；已被新线程接管则不动其条目。
                with self._lock:
                    if self._runs.get(key) is slot.get("t"):
                        self._runs.pop(key, None)
                        self._cancel.pop(key, None)

        thread = threading.Thread(target=work, name="rt-%s" % key, daemon=True)
        slot["t"] = thread
        with self._lock:
            self._runs[key] = thread
        thread.start()
        return {"ok": True, "key": key, "status": "running", "interrupted": interrupted}
