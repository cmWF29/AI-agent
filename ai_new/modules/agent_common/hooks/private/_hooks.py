"""钩子实现：点声明与触发。**这里不装任何订阅者**。

点是模块侧的能力面：模块在自己的功能执行处预留点，声明名字和参数。
"谁在这个点上做事"完全不在本模块 —— 那是需求层（ctx.demand_engine）的事：
emit 只是把事件交给需求层派发。

接线野心为零，所以它也没有任何"业务不知道就丢事件"的隐忧：没有需求订阅的点，
扫描器在装配前就会报出来（声明了但没人用）。
"""
from __future__ import annotations


class Hooks:
    def __init__(self, ctx, engine):
        self.ctx = ctx
        self.engine = engine
        self._points = {}      # name -> {"module": str, "params": tuple}

    # ---- 声明 ----
    def point(self, name, params=()):
        if not isinstance(name, str) or "." not in name:
            raise ValueError("hook 点名必须是 '模块.名字' 形式: %r" % (name,))
        rec = self._points.get(name)
        if rec is None:
            self._points[name] = {"module": name.split(".")[0], "params": tuple(params)}
        elif tuple(params) and rec["params"] and tuple(params) != rec["params"]:
            raise ValueError("hook 点参数声明不一致: %s" % name)
        return name

    def points(self):
        return [
            {"name": name, "module": rec["module"], "params": list(rec["params"])}
            for name, rec in sorted(self._points.items())
        ]

    # ---- 触发 ----
    def emit(self, name, payload=None, level="info"):
        """到点了：交给需求层，按需求的 on/do 去调模块服务。

        未声明的点直接返回失败，不改运行状态；返回值是每条投递的结果，
        **不抛异常** —— 需求挂了不能把提供功能的模块一起拖死。
        """
        if name not in self._points:
            return [{"hook": name, "ok": False, "error": "未声明的 hook 点"}]
        return self.engine.dispatch(name, {"hook": name, "level": level, "data": payload or {}})
