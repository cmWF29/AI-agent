"""钩子实现：点声明与触发。**这里不装任何订阅者**。

点是模块侧的能力面：模块在自己的功能执行处预留点，声明名字和参数。
"谁在这个点上做事"完全不在本模块 —— 那是需求层（ctx.demand_engine）的事：
emit 只是把事件交给需求层派发。

点分两种：
    同步点（默认）—— 属于请求/事务链路，emit 当场派发，结果回给调用方；
    延迟点（defer=True）—— 通知型，不在链路里等它。emit 只入队，
                           请求把响应写完之后由 http 收尾调 drain() 派发。

延迟派发仍是**同一线程顺序执行**：不新开线程、不并发写盘，只是把"用户要等多久"
从请求里摘出去。队列满或多轮自触发都靠上限收口，不会滚雪球。
"""
from __future__ import annotations

PENDING_LIMIT = 200


class Hooks:
    def __init__(self, ctx, engine):
        self.ctx = ctx
        self.engine = engine
        self._points = {}      # name -> {"module": str, "params": tuple, "defer": bool}
        self._pending = []     # [(name, envelope)]：延迟点的待派发队列
        self.errors = []       # 延迟派发里冒出来的异常留痕

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
            if len(self._pending) >= PENDING_LIMIT:
                return [{"hook": name, "ok": False, "error": "延迟队列已满"}]
            self._pending.append((name, {"hook": name, "level": level,
                                         "data": payload or {}}))
            return [{"hook": name, "ok": True, "deferred": True}]
        return self.engine.dispatch(name, {"hook": name, "level": level,
                                           "data": payload or {}})

    # ---- 延迟派发 ----
    def drain(self, limit=10):
        """响应已经写给用户了：把队列里的延迟点按入队顺序跑掉（一次最多一批）。"""
        batch = self._pending[:limit]
        del self._pending[:len(batch)]
        done = []
        for hook, envelope in batch:
            try:
                done.extend(self.engine.dispatch(hook, envelope))
            except Exception as error:  # noqa: BLE001 — 延迟派发失败不能反噬请求
                self.errors.append({"hook": hook, "error": str(error)})
        return done

    def pending(self):
        """还有多少延迟点在排队（可见性用）。"""
        return len(self._pending)

    def clear(self):
        """丢弃待派发的延迟点（用例隔离 / 停机前收口用）。"""
        dropped = len(self._pending)
        del self._pending[:]
        return dropped
