"""工具注册表与输出策略。"""
from __future__ import annotations


class ToolRegistry:
    def __init__(self, ctx):
        self.ctx = ctx
        self._tools = {}

    def register_demand(self, name, desc, params, demand, module=None, kinds=None, deps=None):
        """工具就是一个需求 id：执行=跑那条需求，工具本身不再持有实现。"""
        return self.register(name, desc, params, None, module=module,
                             kinds=kinds, demand=demand, deps=deps)

    def register(self, name, desc, params, fn, module=None, kinds=None, demand=None, deps=None):
        if name in self._tools:
            raise ValueError("tool already registered: " + name)
        self._tools[name] = {
            "name": name, "desc": desc, "params": params or [],
            "fn": fn, "module": module or "", "kinds": kinds, "demand": demand,
            "deps": deps or {},
        }
        return name

    def list_tools(self):
        return [
            {"name": t["name"], "desc": t["desc"], "module": t["module"],
             "params": t["params"], "kinds": t["kinds"], "deps": t["deps"],
             "builtin": True}
            for t in sorted(self._tools.values(), key=lambda x: x["name"])
        ]

    def tools_for(self, kind):
        return [
            t for t in self._tools.values()
            if not t["kinds"] or kind in t["kinds"]
        ]

    def pick(self, allow, kind):
        """按名单裁剪工具：显式名单优先取交集；名单为空则按会话类型放行。"""
        if allow:
            wanted = set(allow)
            base = [t for t in self._tools.values() if t["name"] in wanted]
        else:
            base = self.tools_for(kind)
        return [{"name": t["name"], "desc": t["desc"],
                 "params": t["params"], "module": t["module"]} for t in base]

    def execute(self, name, args, session=None, defer=False):
        if name not in self._tools:
            raise self.ctx.ApiError("工具不存在: %s" % name, code="no_tool", status=404)
        t = self._tools[name]
        if t["kinds"] and isinstance(session, dict) and session.get("kind") not in t["kinds"]:
            raise self.ctx.ApiError("该会话不可用此工具: %s" % name,
                                    code="tool_forbidden", status=403)
        args = dict(args or {})
        if isinstance(session, dict):
            # 会话上下文是工具参数的缺省落点：模型显式给的优先，其余由会话记录补
            for key, src in (("id", "ticket"), ("ticket", "ticket"),
                             ("role", "role"), ("session", "id")):
                if not args.get(key) and session.get(src):
                    args[key] = session[src]
        if t.get("demand"):
            if defer:
                # 组合一律写成需求：注册表只声明"该跑哪个需求"，伸手的是需求身份
                return {"ok": True, "deferred": True, "demand": t["demand"],
                        "input": args}
            result = self.ctx.runtime.call(t["demand"], args)
        else:
            result = t["fn"](self.ctx, args or {}, session=session)
        # 落盘是有副作用的业务动作：工具注册表不隐式写盘；
        # 大输出要不要留存、存到哪、怎么存，由需求显式调 store 能力决定。
        return result
