"""运行设施实现：效果执行 + 后台调度（有界池复用）。

两条不变量：
1. 只有这里写盘。能力交出 effect，需求调 apply，落到 store 的写路由。
2. 只有这里驱动别的需求。能力交出 demand effect，同样由 apply 执行。

并发模型：后台会话任务提交到有界会话池（线程复用），阻塞的同步需求链在
池线程内跑；工具/子进程执行走独立工具池，与会话调度池分离，互不占坑。
容量由 config.runtime.session_workers / tool_workers 显性声明。
"""
from __future__ import annotations

import concurrent.futures
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
        self._runs = {}      # key -> concurrent.futures.Future（后台会话任务）
        self._cancel = {}
        self._stream = {}
        self._subs = {}   # 草稿槽订阅：key -> [threading.Event]，槽变化即唤醒等待方
        self._lock = threading.Lock()
        self._session_pool = concurrent.futures.ThreadPoolExecutor(
            max_workers=self._cfg_int("session_workers", 8),
            thread_name_prefix="session")
        self._tool_pool = concurrent.futures.ThreadPoolExecutor(
            max_workers=self._cfg_int("tool_workers", 8),
            thread_name_prefix="tool")

    # ---- 配置（容量显性读入，不在代码里藏默认）----
    def _cfg_int(self, key, default):
        cfg = getattr(self.ctx, "cfg", None) or {}
        rt = cfg.get("runtime") or {}
        try:
            return int(rt.get(key) or default)
        except (TypeError, ValueError):
            return default

    # ---- 打断位 ----
    def cancelled(self, key, since):
        """同一把钥匙上，since 之后有没有人置过打断位。"""
        return (self._cancel.get(str(key or "")) or 0) > (since or 0)

    def stop(self, key):
        """置打断位并等同一把钥匙上的后台任务收尾；不在跑就直接返回。

        硬删会话文件前先 stop：等任务退出后再落删除 effect，避免定稿落盘把文件写回。
        """
        key = str(key or "")
        if not key:
            return {"ok": False, "code": "no_key"}
        with self._lock:
            self._cancel[key] = self._now()
            fut = self._runs.get(key)
        if fut is not None and not fut.done():
            fut.cancel()
            self._await_future(fut)
        with self._lock:
            self._runs.pop(key, None)
            self._cancel.pop(key, None)
        return {"ok": True, "key": key}

    def _await_future(self, fut):
        """等后台任务收尾；等待失败不掀翻删除链路。"""
        try:
            fut.result(timeout=30)
        except Exception:  # noqa: BLE001
            pass

    def active_keys(self):
        """当前仍在跑的后台任务钥匙集合；供自愈扫描区分僵死记录与在途任务。"""
        with self._lock:
            return {k for k, f in self._runs.items() if not f.done()}

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
        """登记一个等待事件；返回 Event，槽变化时被唤醒等待方。"""
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

    def _now(self):
        return (self.ctx.api.call("clock.now", {}, caller=None) or {}).get("ts") or 0

    def call(self, demand, data=None):
        """同步跑一条需求并拿结果：能力的批量动作里，单次动作仍是一条需求。"""
        resp = self.ctx.api.call("demand_engine.run",
                                 {"id": demand, "input": data or {}}, caller=None) or {}
        return resp.get("result") or {}

    async def acall(self, demand, data=None):
        """异步轨跑一条需求并拿结果：协程内 await，结果收口到能力面。"""
        resp = await self.ctx.api.acall("demand_engine.run",
                                        {"id": demand, "input": data or {}}, caller=None) or {}
        return resp.get("result") or {}

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
        interrupted = bool(prev and not prev.done())
        slot = {}
        fut = self._session_pool.submit(self._work, key, slot, prev, demand, data)
        slot["t"] = fut
        with self._lock:
            self._runs[key] = fut
        return {"ok": True, "key": key, "status": "running", "interrupted": interrupted}

    def _work(self, key, slot, prev, demand, data):
        """池线程内跑一棒：先等上一棒真正收尾，再判接管作废，最后跑需求；收尾自清。"""
        try:
            if prev and not prev.done():
                self._cancel[key] = self._now()
                try:
                    prev.result(timeout=30)
                except Exception:  # noqa: BLE001 —— 上一棒失败不掀翻本棒
                    pass
            with self._lock:
                if self._runs.get(key) is not slot.get("t"):
                    return      # 后面又有人接管，这一棒作废，避免并发跑两轮
            self._run_demand(demand, data)
        finally:
            # 本棒收尾（跑完/报错/被接管作废）即自清；已被新任务接管则不动其条目。
            with self._lock:
                if self._runs.get(key) is slot.get("t"):
                    self._runs.pop(key, None)
                    self._cancel.pop(key, None)

    def _run_demand(self, demand, data):
        return self.ctx.api.call("demand_engine.run",
                                 {"id": demand, "input": data}, caller=None)

    def submit_tool(self, fn, *args, **kwargs):
        """把一条工具/子进程执行提交到独立工具池，返回 future；与会话调度池互不占坑。

        并发模型：调用方先把同一轮的多条工具执行全部 submit，再逐个收 future 回填，
        工具在工具池线程内并发跑；写盘/回填仍由会话线程串行收口，避免并发落盘竞争。
        """
        return self._tool_pool.submit(fn, *args, **kwargs)
