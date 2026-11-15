"""工具注册表与输出策略。"""
from __future__ import annotations


class ToolRegistry:
    def __init__(self, ctx):
        self.ctx = ctx
        self._tools = {}

    def register_demand(self, name, desc, params, demand, module=None, kinds=None):
        """工具就是一个需求 id：执行=跑那条需求，工具本身不再持有实现。"""
        return self.register(name, desc, params, None, module=module,
                             kinds=kinds, demand=demand)

    def register(self, name, desc, params, fn, module=None, kinds=None, demand=None):
        if name in self._tools:
            raise ValueError("tool already registered: " + name)
        self._tools[name] = {
            "name": name, "desc": desc, "params": params or [],
            "fn": fn, "module": module or "", "kinds": kinds, "demand": demand,
        }
        return name

    def list_tools(self):
        return [
            {"name": t["name"], "desc": t["desc"], "module": t["module"],
             "params": t["params"], "kinds": t["kinds"]}
            for t in sorted(self._tools.values(), key=lambda x: x["name"])
        ]

    def tools_for(self, kind):
        return [
            t for t in self._tools.values()
            if not t["kinds"] or kind in t["kinds"]
        ]

    def execute(self, name, args, session=None):
        if name not in self._tools:
            raise self.ctx.ApiError("工具不存在: %s" % name, code="no_tool", status=404)
        t = self._tools[name]
        if t["kinds"] and session and session.get("kind") not in t["kinds"]:
            raise self.ctx.ApiError("该会话不可用此工具: %s" % name,
                                    code="tool_forbidden", status=403)
        if t.get("demand"):
            result = self.ctx.api.call("demand_engine.run",
                                       {"id": t["demand"], "input": args or {}},
                                       caller="tools")
        else:
            result = t["fn"](self.ctx, args or {}, session=session)
        return self._maybe_persist(result)

    def _maybe_persist(self, result):
        """统一输出策略：文本过大时先落盘，只给模型返回路径提示。"""
        if not isinstance(result, dict):
            return result
        text = result.get("text") or result.get("content")
        if not isinstance(text, str):
            return result
        limit = int(self.ctx.cfg.get("tools", {}).get("inline_max_chars", 4000))
        if len(text) <= limit:
            return result
        name = self.ctx.storage.safe_id(str(result.get("name") or result.get("path") or "out"))
        now = self.ctx.clock.now()["ts"]
        rel = "toolout/%s-%s.txt" % (name[:40], int(now * 1000))
        path = _md(self.ctx).path(rel)
        ctx.storage.own(__file__).write_text(rel, text)
        result = dict(result)
        result.pop("text", None)
        result.pop("content", None)
        result["persisted"] = rel
        result["note"] = (
            "输出 %d 字符，已落盘到 %s；需要细节时用 ticket_read_doc 或对应的读文件工具按路径读取。"
            % (len(text), rel))
        result["head"] = text[:200]
        return result



def _md(ctx):
    """本模块自己的数据目录：数据跟着模块走，不是全系统一个筐。"""
    return ctx.storage.own(__file__)
