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
    ctx.api.register("tools.install_missing", _route_install_missing,
                     "安装缺失的 Python 包；cli/env/config 只列待人工处理", module="tools")
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
    """清单闭环：内置注册表 ∪ 外部登记记录 → 按来源裁剪 → 收集在位快照 → 纯函数判定成形。

    scope=builtin 只给代码内置工具库，scope=external 只给外部安装的技能库；默认全量。
    """
    builtin = ctx.tools.list_tools()
    merged = _pure.merge({"builtin": builtin,
                          "external": (payload or {}).get("external") or {}})
    items = _pure.scope(merged["items"], (payload or {}).get("scope"))
    snapshot = _collect_snapshot(ctx, items)
    return _pure.listing({"tools": items, "snapshot": snapshot})


def _route_install_missing(ctx, payload):
    """安装闭环：合并清单 → 在位快照 → 安装计划 → 逐条装缺失 pip 包。

    装包是起进程的 effect，经 exec.run；cli/env/config 不在此自动处理，只随计划返回。
    """
    builtin = ctx.tools.list_tools()
    merged = _pure.merge({"builtin": builtin,
                          "external": (payload or {}).get("external") or {}})
    snapshot = _collect_snapshot(ctx, merged["items"])
    plan = _pure.install_plan({"tools": merged["items"], "snapshot": snapshot})
    installs = []
    if plan["pip"]:
        exe = ctx.api.call("host.executable", {}, caller=None).get("path") or "python"
        for pkg in plan["pip"]:
            r = ctx.api.call("exec.run",
                             {"argv": [exe, "-m", "pip", "install", pkg],
                              "timeout": 300}, caller=None)
            installs.append({"pkg": pkg, "ok": bool(r.get("ok")),
                             "error": r.get("error") or ""})
    return {"plan": plan, "installs": installs,
            "ready": plan["ready"] and all(x["ok"] for x in installs)}
