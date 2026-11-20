"""钩子实现：点声明与触发。**这里不装任何订阅者**。

点是模块侧的能力面：模块在自己的功能执行处预留点，声明名字和参数。
"谁在这个点上做事"完全不在本模块 —— 那是需求层（ctx.demand_engine）的事：
emit 只是把事件交给需求层派发。

点分两种：
    同步点（默认）—— 属于请求/事务链路，emit 当场派发，结果回给调用方；
    延迟点（defer=True）—— 通知型，不在链路里等它。emit 只入队，
                           请求把响应写完之后由 http 收尾调 drain 派发。

延迟派发：同步轨 drain 在线程内顺序跑；异步轨 drain_async 在事件循环内 await，
协程路由直连不回桥接。队列由锁保护，并发 drain 不会重复跑同一事件。
"""
from __future__ import annotations

import threading

PENDING_LIMIT = 200


class Hooks:
    def __init__(self, ctx, engine):
        self.ctx = ctx
        self.engine = engine
        self._points = {}      # name -> {"module": str, "params": tuple, "defer": bool}
        self._pending = []     # [(name, envelope)]：延迟点的待派发队列
        self.errors = []       # 延迟派发里冒出来的异常留痕
        self._lock = threading.Lock()

    # ---- 声明 ----
    def point(self, name, params=(), defer=False):
        if not isinstance(name, str) or "." not in name:
            raise ValueError("hook 点名必须是 '模块.名字' 形式: %r" % (name,))
        rec = self._points.get(name)
        if rec is None:
            self._points[name] = {"module": name.split(".")[0], "params": tuple(params),
                                  "defer": bool(defer)}
        else:
            if tuple(params) and rec["params"] and tuple(params) != rec["params"]:
                raise ValueError("hook 点参数声明不一致: %s" % name)
            if bool(defer) != rec["defer"]:
                raise ValueError("hook 点同步/延迟声明不一致: %s" % name)
        return name

    def points(self):
        return [
            {"name": name, "module": rec["module"], "params": list(rec["params"]),
             "defer": rec["defer"]}
            for name, rec in sorted(self._points.items())
        ]

    def _runtime(self):
        return getattr(self.ctx, "runtime", None)

    # ---- 触发 ----
    def emit(self, name, payload=None, level="info"):
        """到点了：同步点当场派发；延迟点先入队，等响应写完再跑。

        未声明的点直接返回失败，不改运行状态；返回值是每条投递的结果，
        **不抛异常** —— 需求挂了不能把提供功能的模块一起拖死。
        """
        rec = self._points.get(name)
        if rec is None:
            return [{"hook": name, "ok": False, "error": "未声明的 hook 点"}]
        if rec["defer"]:
            envelope = {"hook": name, "level": level, "data": payload or {}}
            rt = self._runtime()
            if rt is not None:
                rt.enqueue_hook(name, envelope)
            else:
                with self._lock:
                    if len(self._pending) >= PENDING_LIMIT:
                        return [{"hook": name, "ok": False, "error": "延迟队列已满"}]
                    self._pending.append((name, envelope))
            return [{"hook": name, "ok": True, "deferred": True}]
        return self.engine.dispatch(name, {"hook": name, "level": level,
                                           "data": payload or {}})

    def _claim(self, limit):
        """认领一批待派发事件：持久队列在 runtime 内锁内摘除，避免重复派发。"""
        rt = self._runtime()
        if rt is not None:
            return [(i["hook"], i) for i in rt.claim_hooks(limit)]
        with self._lock:
            batch = self._pending[:limit]
            del self._pending[:len(batch)]
            return batch

    # ---- 延迟派发 ----
    def drain(self, limit=10):
        """同步轨收尾：把队列里的延迟点按入队顺序跑掉（一次最多一批）。"""
        done = []
        for hook, envelope in self._claim(limit):
            try:
                done.extend(self.engine.dispatch(hook, envelope))
            except Exception as error:  # noqa: BLE001 — 延迟派发失败不能反噬请求
                self.errors.append({"hook": hook, "error": str(error)})
        return done

    async def drain_async(self, limit=10):
        """异步轨收尾：协程内 await 派发，协程路由直连事件循环，不回桥接死锁。"""
        done = []
        for hook, envelope in self._claim(limit):
            try:
                done.extend(await self.engine.adispatch(hook, envelope))
            except Exception as error:  # noqa: BLE001 — 延迟派发失败不能反噬请求
                self.errors.append({"hook": hook, "error": str(error)})
        return done

    def pending(self):
        """还有多少延迟点在排队（可见性用）。"""
        rt = self._runtime()
        return rt.pending_hooks() if rt is not None else len(self._pending)

    def clear(self):
        """丢弃待派发的延迟点（用例隔离 / 停机前收口用）。"""
        rt = self._runtime()
        if rt is not None:
            rt.clear_hooks()
            return
        with self._lock:
            dropped = len(self._pending)
            del self._pending[:]
        return dropped
