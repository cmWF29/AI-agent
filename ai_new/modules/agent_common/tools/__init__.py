"""工具模块：注册、白名单、执行、依赖就绪探测。无业务；落盘由需求显式编排。"""
from __future__ import annotations

from .private import _registry, _pure


def setup(ctx):
    """装配入口：ctx.tools 指向注册表。"""
    ctx.tools = _registry.ToolRegistry(ctx)
    ctx.api.register("tools.execute",
                     lambda c, payload: ctx.tools.execute(payload.get("name"),
                                                       payload.get("args"),
                                                       session=payload.get("session"),
                                                       defer=bool(payload.get("defer"))),
                     module="tools")
    ctx.api.register("tools.pick",
                     lambda c, payload: {"items": ctx.tools.pick(
                         payload.get("tools") or [], payload.get("kind"))},
                     module="tools")
    ctx.api.register("tools.list", _route_list,
                     "工具清单：内置 ∪ 外部登记，附依赖就绪状态", module="tools")
    return ctx.tools


def register(ctx, name, desc, params, fn, module=None, kinds=None, deps=None):
    """注册工具；kinds 为会话类型白名单（None=所有会话可见），deps 为依赖声明。"""
    return ctx.tools.register(name, desc, params, fn, module=module,
                              kinds=kinds, deps=deps)


def execute(ctx, name, args, session=None):
    """执行工具；注册表不隐式落盘，留存由需求编排。"""
    return ctx.tools.execute(name, args, session=session)


def list_tools(ctx):
    """全部内置工具（脱敏描述）。"""
    return ctx.tools.list_tools()


def _collect_snapshot(ctx, tools):
    """遍历依赖收集在位快照：命令/包/环境变量/配置项。探测是主机事实，经 host/config 取。"""
    snap = {"cli": {}, "pip": {}, "env": {}, "config": {}}
    for t in tools:
        deps = t.get("deps") or {}
        for cmd in deps.get("cli") or []:
            if cmd and cmd not in snap["cli"]:
                r = ctx.api.call("host.which", {"name": cmd}, caller=None)
                snap["cli"][cmd] = bool(r.get("found"))
        for pkg in deps.get("pip") or []:
            if pkg and pkg not in snap["pip"]:
                r = ctx.api.call("host.importable", {"name": pkg}, caller=None)
                snap["pip"][pkg] = bool(r.get("importable"))
        for var in deps.get("env") or []:
            if var and var not in snap["env"]:
                r = ctx.api.call("host.env", {"name": var}, caller=None)
                snap["env"][var] = r.get("value")
        for key in deps.get("config") or []:
            if key and key not in snap["config"]:
                r = ctx.api.call("config.get", {"key": key}, caller=None)
                snap["config"][key] = r.get("value")
    return snap


def _route_list(ctx, payload):
    """清单闭环：内置注册表 ∪ 外部登记记录 → 收集在位快照 → 纯函数判定成形。"""
    builtin = ctx.tools.list_tools()
    merged = _pure.merge({"builtin": builtin,
                          "external": (payload or {}).get("external") or {}})
    snapshot = _collect_snapshot(ctx, merged["items"])
    return _pure.listing({"tools": merged["items"], "snapshot": snapshot})
