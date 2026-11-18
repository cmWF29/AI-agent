"""工具模块：注册、白名单、执行、依赖就绪探测。无业务；落盘由需求显式编排。"""
from __future__ import annotations

from .private import _registry, _pure

# 外部登记工具共用的占位执行需求：真实后端接入前，执行统一回占位提示（#48 搁置）。
EXTERNAL_DEMAND = "tool-external-run"


def _msg_tpl(ctx):
    """消息模板表：工具模块自己的 data，读不到就退化成空。"""
    row = ctx.api.call("store.read", {
        "module": "agent_common/tools", "path": "messages.yaml"}, caller=None)
    return row.get("value") or {}


def setup(ctx):
    """装配入口：ctx.tools 指向注册表。"""
    ctx.tools = _registry.ToolRegistry(ctx)
    ctx.api.register("tools.execute", _route_execute,
                     "执行工具：注册表命中直跑；未命中按公共登记回退占位，项目禁用工具不执行", module="tools")
    ctx.api.register("tools.pick", _route_pick,
                     "岗位工具名单：内置注册表 ∪ 公共外部登记，按名单/类型与项目禁用裁剪", module="tools")
    ctx.api.register("tools.list", _route_list,
                     "工具清单：内置 ∪ 外部登记，附依赖就绪状态", module="tools")
    ctx.api.register("tools.deps", _route_deps,
                     "依赖盘点：分类汇总在位/缺失依赖、工具就绪统计与待装计划（只读）", module="tools")
    ctx.api.register("tools.install_missing", _route_install_missing,
                     "安装缺失的 Python 包；cli/env/config 只列待人工处理", module="tools")
    ctx.api.register("tools.external_run", _route_external_run,
                     "外部工具占位执行：后端未接入前回显登记与依赖提示", module="tools")
    ctx.tools.register("shell", "在运行环境执行命令：argv 数组直传、不经 shell；"
                                "用于拉取资源、跑随包脚本与自验。", [
        {"name": "argv", "type": "list",
         "desc": "命令与参数数组，如 [\"python\",\"-m\",\"pip\",\"install\",\"x\"]",
         "required": True},
        {"name": "cwd", "type": "string", "desc": "工作目录（可选）", "required": False},
        {"name": "timeout", "type": "number", "desc": "超时秒（可选，默认 300）",
         "required": False}],
        _tool_shell, module="tools", kinds=["role"], deps={}, builtin=True)
    return ctx.tools


def start(ctx):
    """全部内置工具注册完成后，把外部登记工具并入注册表；内置同名优先，不被覆盖。

    归属已禁用 Skill 的外部工具不并入运行注册表。
    """
    row = ctx.api.call("store.read", {
        "module": "agent_common/tools", "path": "tools.yaml"}, caller=None)
    skills = ctx.api.call("store.read", {
        "module": "agent/library", "path": "skills.yaml"}, caller=None)
    disabled = {sid for sid, rec in (skills.get("value") or {}).items()
                if isinstance(rec, dict) and rec.get("status") == "disabled"}
    for name, rec in (row.get("value") or {}).items():
        if not name or not isinstance(rec, dict) or ctx.tools.has(name):
            continue
        if rec.get("skill") in disabled:
            continue
        ctx.tools.register_demand(
            name, rec.get("desc") or "", rec.get("params") or [],
            demand=rec.get("demand") or EXTERNAL_DEMAND,
            module=rec.get("module") or "external",
            kinds=rec.get("kinds") or [], deps=rec.get("deps") or {}, builtin=False)


def register(ctx, name, desc, params, fn, module=None, kinds=None, deps=None):
    """注册工具；kinds 为会话类型白名单（None=所有会话可见），deps 为依赖声明。"""
    return ctx.tools.register(name, desc, params, fn, module=module,
                              kinds=kinds, deps=deps)


def _tool_shell(ctx, args, session=None):
    """通用命令执行：argv 数组直传 exec.run，不经 shell；超时与打断复用进程通道。"""
    argv = [str(a) for a in (args or {}).get("argv") or []]
    if not argv:
        return {"ok": False, "error": _msg_tpl(ctx).get("argv_required") or "",
                "code": "bad_request"}
    return ctx.api.call("exec.run", {
        "argv": argv,
        "cwd": (args or {}).get("cwd") or "",
        "timeout": (args or {}).get("timeout") or 300}, caller=None)


def execute(ctx, name, args, session=None):
    """执行工具；注册表不隐式落盘，留存由需求编排。"""
    return ctx.tools.execute(name, args, session=session)


def list_tools(ctx):
    """全部内置工具（脱敏描述）。"""
    return ctx.tools.list_tools()


def _project_external(ctx, project):
    """按项目取外部登记工具字典、已禁用 Skill 集合与项目禁用工具名集合。

    工具定义正文只存公共库一份；项目只持有启停覆盖层。无 project 时退化为公共库。
    """
    ext = ctx.api.call("store.read", {"module": "agent_common/tools",
                                      "path": "tools.yaml"}, caller=None)
    sk = ctx.api.call("store.read", {"module": "agent/library",
                                    "path": "skills.yaml"}, caller=None)
    disabled = ctx.api.call("library.disabled_skills",
                            {"skills": (sk.get("value") or {})}, caller=None)
    disabled_names = []
    if project:
        row = ctx.api.call("store.read", {"module": "agent/projects",
                                          "path": project + ".yaml"}, caller=None)
        ov = ctx.api.call("projects.override_parts", {"rec": row.get("value")}, caller=None)
        disabled_names = ov.get("tools") or []
    return ext.get("value") or {}, disabled.get("ids") or [], disabled_names


def _route_pick(ctx, payload):
    """岗位工具名单：内置注册表 ∪ 公共外部登记，按名单交集/会话类型与项目禁用裁剪。"""
    builtin = ctx.tools.list_tools()
    external, disabled, disabled_names = _project_external(ctx, payload.get("project"))
    merged = _pure.merge({"builtin": builtin, "external": external,
                          "disabled": disabled})
    return _pure.pickp({"items": merged["items"],
                        "tools": payload.get("tools") or [],
                        "kind": payload.get("kind"),
                        "disabled": disabled_names})


def _route_execute(ctx, payload):
    """执行工具：注册表命中直跑；项目禁用工具拦截；未命中按公共登记回退占位，仍无则报 no_tool。"""
    name = payload.get("name")
    session = payload.get("session")
    external, _, disabled_names = _project_external(ctx, (session or {}).get("project"))
    if name in set(disabled_names):
        tpl = _msg_tpl(ctx).get("tool_disabled") or ""
        raise ctx.ApiError(tpl.format(name=name) if tpl else "", code="no_tool", status=404)
    if ctx.tools.has(name):
        return ctx.tools.execute(name, payload.get("args"), session=session,
                                 defer=bool(payload.get("defer")))
    rec = external.get(name)
    if not isinstance(rec, dict):
        tpl = _msg_tpl(ctx).get("tool_missing") or ""
        raise ctx.ApiError(tpl.format(name=name) if tpl else "", code="no_tool", status=404)
    args = dict(payload.get("args") or {})
    args.pop("tool", None)
    return _pure.external_pending({"tool": name, "args": args, "rec": rec,
                                   "tpl": _msg_tpl(ctx).get("external_pending")})


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


def _route_external_run(ctx, payload):
    """外部工具占位闭环：取登记记录 → 纯函数成形占位结果；不探测主机、不执行。"""
    name = payload.get("tool") or ""
    args = dict(payload.get("args") or {})
    args.pop("tool", None)  # 工具名是注册身份，不是业务参数
    row = ctx.api.call("store.read", {
        "module": "agent_common/tools", "path": "tools.yaml"}, caller=None)
    rec = (row.get("value") or {}).get(name) or {}
    return _pure.external_pending({"tool": name, "args": args, "rec": rec,
                                    "tpl": _msg_tpl(ctx).get("external_pending")})


def _route_list(ctx, payload):
    """清单闭环：内置注册表 ∪ 外部登记记录 → 按来源裁剪 → 收集在位快照 → 纯函数判定成形。

    scope=builtin 只给代码内置工具库，scope=external 只给外部登记的工具；默认全量。
    disabled 为已禁用 Skill 标识集合，归属这些 Skill 的工具不进清单。
    """
    builtin = ctx.tools.list_tools()
    merged = _pure.merge({"builtin": builtin,
                          "external": (payload or {}).get("external") or {},
                          "disabled": (payload or {}).get("disabled") or []})
    items = _pure.scope(merged["items"], (payload or {}).get("scope"))
    snapshot = _collect_snapshot(ctx, items)
    return _pure.listing({"tools": items, "snapshot": snapshot,
                          "disabled_names": (payload or {}).get("disabled_names") or []})


def _route_deps(ctx, payload):
    """盘点闭环：合并清单 → 在位快照 → 纯函数聚合分类在位/缺失与就绪统计。

    只读盘点，不装包；口径与安装计划一致（内置 ∪ 外部，已禁用 Skill 剔除）。
    """
    builtin = ctx.tools.list_tools()
    merged = _pure.merge({"builtin": builtin,
                          "external": (payload or {}).get("external") or {},
                          "disabled": (payload or {}).get("disabled") or []})
    snapshot = _collect_snapshot(ctx, merged["items"])
    return _pure.deps_report({"tools": merged["items"], "snapshot": snapshot})


def _route_install_missing(ctx, payload):
    """安装闭环：合并清单 → 在位快照 → 安装计划 → 逐条装缺失 pip 包。

    装包是起进程的 effect，经 exec.run；cli/env/config 不在此自动处理，只随计划返回。
    已禁用 Skill 的工具不参与安装计划。
    """
    builtin = ctx.tools.list_tools()
    merged = _pure.merge({"builtin": builtin,
                          "external": (payload or {}).get("external") or {},
                          "disabled": (payload or {}).get("disabled") or []})
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
