"""需求引擎实现：把 data/demands/*.json 读成"可执行的需求"，在 hook 触发时跑它们。

引擎不知道任何业务名词。它只会三件事：
    1. 装载需求（一个文件 = 一个需求 = 一段可插拔的业务）
    2. 按 `on` 找到该跑哪些需求
    3. 用 _lang 跑它们的语句树（顺序、守卫、循环、变量都是数据）

需求是运行时的东西，但它的**语法是结构的**：所有服务调用都在语句树的 `call` 字段里，
静态扫描能读全，所以"业务"既跑得起来，又不必靠运行时日志才能看懂。
"""
from __future__ import annotations

from . import _lang


class Engine:
    def __init__(self, ctx):
        self.ctx = ctx
        self._cache = None

    # ---- 装载 ----
    def _load(self):
        if self._cache is None:
            self._cache = self._read_all()
        return self._cache

    def _read_all(self):
        names = _md(self.ctx).list_dir("demands")
        items = []
        for name in names:
            if not name.endswith(".yaml"):
                continue
            rec = _md(self.ctx).yaml_read("demands/%s" % name, {}) or {}
            rec.setdefault("id", name[:-5])
            rec.setdefault("enabled", True)
            rec["on"] = _as_hooks(rec.get("on"))
            rec.setdefault("do", [])
            items.append(rec)
        return sorted(items, key=lambda r: r["id"])

    def reload(self):
        self._cache = None

    # ---- 可见性 ----
    def items(self):
        return [
            {"id": r["id"], "title": r.get("title", ""),
             "enabled": bool(r.get("enabled", True)),
             "tags": list(r.get("tags") or []),
             "view": r.get("view") or None,
             "on": list(r["on"]),
             "do": _lang.routes_of(r.get("do"))}
            for r in self._load()
        ]

    # ---- 插拔 ----
    def set_enabled(self, demand_id, enabled):
        for rec in self._load():
            if rec["id"] != demand_id:
                continue
            rec["enabled"] = bool(enabled)
            _md(self.ctx).yaml_write("demands/%s.yaml" % demand_id, rec)
            self.reload()
            return {"id": demand_id, "enabled": bool(enabled)}
        raise self.ctx.ApiError("需求不存在: %s" % demand_id, code="no_demand", status=404)

    # ---- 运行 ----
    def run_callable(self, demand_id, inputs=None):
        """按名跑一段"编排需求"（不挂在点上），返回最后一次调用的结果。"""
        for rec in self._load():
            if rec["id"] != demand_id:
                continue
            if not rec.get("enabled", True):
                return {"ok": False, "error": "需求已下线", "code": "disabled", "demand": demand_id}
            if not rec.get("callable"):
                raise self.ctx.ApiError("需求不按名调用: %s" % demand_id,
                                        code="not_callable", status=400)
            scope = {"input": inputs or {}, "caller": None}
            results = _lang.run(rec.get("do"), scope, self.ctx.api, self.ctx, demand_id)
            last = next((r for r in reversed(results) if r.get("call")), None)
            if last is None:
                return {"ok": False, "error": "没有任何调用", "code": "empty", "demand": demand_id}
            out = last.get("result")
            # 能力结果可以是任意形状（清单类返回列表），只有 dict 才看 ok 字段。
            ok = (bool(out.get("ok", True)) if isinstance(out, dict) else True) \
                and all(r.get("ok") for r in results)
            return {"ok": ok, "demand": demand_id, "result": out,
                    "calls": [r.get("call") for r in results]}
        raise self.ctx.ApiError("需求不存在: %s" % demand_id, code="no_demand", status=404)

    def dispatch(self, hook, envelope):
        results = []
        for rec in self._load():
            if not rec.get("enabled", True) or hook not in rec["on"]:
                continue
            scope = {"event": envelope or {}, "hook": hook, "caller": None}
            results.extend(_lang.run(rec.get("do"), scope, self.ctx.api, self.ctx, rec["id"]))
        return results


def _as_hooks(value):
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [str(v) for v in value]
    return []



def _md(ctx):
    """本模块自己的数据目录：数据跟着模块走，不是全系统一个筐。"""
    return ctx.storage.own(__file__)
