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
        # 落盘是有副作用的业务动作：工具注册表不隐式写盘；
        # 大输出要不要留存、存到哪、怎么存，由需求显式调 store 能力决定。
        return result
