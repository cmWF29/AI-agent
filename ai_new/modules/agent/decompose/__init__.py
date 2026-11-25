"""拆解模块：Skill.md 包 → 模型拆解 → 直接成形为 Skill 单元（岗位/流程/工具）入库。

闭环（解析包内容、取工具名单、拼提示词、调模型、解码、成形）收在 decompose.run
能力内；需求树只编排"跑拆解 → 成形入库记录 → 分库落盘"，不做拼装与判断。
"""
from __future__ import annotations

from .private import _pure


def setup(ctx):
    for name, fn in [
        ("decompose.parse_skill_doc", _pure.parse_skill_doc),
        ("decompose.promptize", _pure.promptize),
        ("decompose.parse", _pure.parse),
        ("decompose.install_parts", _pure.install_parts),
    ]:
        ctx.api.register(name, _as_handler(fn), module="decompose")
    ctx.api.register("decompose.run", _route_run,
                     "拆解闭环：解析包内容→取工具名单→拼提示→ReAct 拉装→模型→解码→成形入库记录",
                     module="decompose")
    ctx.api.register("decompose.install", _route_install,
                     "拆解入库：产物有效才合并四库并产出落盘 effects；无效回空 effects 不落盘",
                     module="decompose")
    ctx.api.register("decompose.inspect", _route_inspect,
                     "安全读包 + 环境探测 + 依赖检查；只扫描探测，不执行任何外壳",
                     module="decompose")
    ctx.api.register("decompose.deps_install", _route_deps_install,
                     "隔离安装依赖：固定 argv、锁版本、写审计日志，失败回滚并保留日志",
                     module="decompose")
    ctx.api.register("decompose.register", _route_register,
                     "校验后登记角色 / 工具 / 流程；同 skill+version 幂等重跑不重复建",
                     module="decompose")
    ctx.api.register("decompose.status", _route_status,
                     "拆解任务状态与产物清单只读视图数据",
                     module="decompose")
    # 拆解循环专用工具：拉文档文本、白名单装 pip 包；shell 已由通用 tools 模块注册为
    # 内置执行工具，这里只补拆解闭环的 schema 名单，不重复注册 fn。
    for tool in _pure.tool_defs():
        fn = _TOOL_FNS.get(tool["name"])
        if fn is None or ctx.tools.has(tool["name"]):
            continue
        ctx.tools.register(tool["name"], tool["desc"], tool["params"], fn,
                           module="decompose", kinds=None, deps={}, builtin=False)
    return True


def _msg_tpl(ctx):
    """消息模板表：拆解模块自己的 data，读不到就退化成空。"""
    row = ctx.api.call("store.read", {
        "module": "agent/decompose", "path": "messages.yaml"}, caller=None)
    return row.get("value") or {}


# 拆解任务台账：模块自有数据目录下的 tasks.yaml；只碰自己的目录，不写正式库。
_TASKS_PATH = "tasks.yaml"


def _read_tasks(ctx):
    row = ctx.api.call("store.read", {
        "module": "agent/decompose", "path": _TASKS_PATH}, caller=None)
    rec = row.get("value")
    if not isinstance(rec, dict):
        rec = {}
    rec.setdefault("tasks", {})
    return rec


def _tasks_effect(state):
    return {"kind": "write", "module": "agent/decompose",
            "path": _TASKS_PATH, "value": state}


def _read_lib(ctx, module, path):
    row = ctx.api.call("store.read", {"module": module, "path": path}, caller=None)
    return row.get("value") or {}


def _env_snapshot(ctx, deps):
    """主机事实探测：命令在不在 PATH、环境变量在不在；探测结果整份交纯函数判定。"""
    deps = deps or {}
    snap = {"cli": {}, "env": {}}
    for cmd in _pure._as_list(deps.get("cli")):
        r = ctx.api.call("host.which", {"name": cmd}, caller=None)
        snap["cli"][cmd] = bool(r.get("found"))
    for var in _pure._as_list(deps.get("env")):
        r = ctx.api.call("host.env", {"name": var}, caller=None)
        snap["env"][var] = r.get("value")
    return snap


def _flow_states(flow):
    """流程 nodes/edges 归一为状态机 states：边转 next 邻接，无出边者标终态。"""
    nodes = flow.get("nodes") or []
    edges = flow.get("edges") or []
    ids = [n.get("id") for n in nodes if isinstance(n, dict)]
    nexts = {i: [] for i in ids}
    for edge in edges:
        if isinstance(edge, dict) and edge.get("from") in nexts \
                and edge.get("to") not in nexts[edge["from"]]:
            nexts[edge["from"]].append(edge["to"])
    return [{"id": i, "next": nexts[i], "terminal": not nexts[i]} for i in ids]


def _as_handler(fn):
    def handler(ctx, payload):
        payload = dict(payload or {})
        payload["tpl"] = _msg_tpl(ctx)
        return fn(payload)
    return handler


async def _tool_fetch(ctx, args, session=None):
    """拆解期只读拉取 http(s) 文档文本；非 http(s) 直接拒，不走任意地址。"""
    tpl = _msg_tpl(ctx)
    url = str((args or {}).get("url") or "").strip()
    if not url:
        return {"ok": False, "error": tpl.get("missing_url") or "", "code": "bad_request"}
    if not (url.startswith("http://") or url.startswith("https://")):
        return {"ok": False, "error": tpl.get("bad_url") or "", "code": "bad_url"}
    resp = await ctx.api.acall("net.request",
                        {"url": url, "method": "GET", "timeout": 30}, caller=None)
    if not isinstance(resp, dict) or resp.get("ok") is False:
        out = dict(resp or {})
        out["ok"] = False
        out.setdefault("code", "fetch_failed")
        out.setdefault("error", tpl.get("fetch_failed") or "")
        return out
    return {"ok": True, "url": url, "text": resp.get("text") or ""}


async def _tool_pip(ctx, args, session=None):
    """拆解期白名单装单个 pip 包：包名先过纯函数校验，固定 argv 直传，不经 shell。"""
    tpl = _msg_tpl(ctx)
    check = _pure.safe_pkg((args or {}).get("pkg"), tpl)
    if not check.get("ok"):
        return {"ok": False, "error": check.get("error"), "code": "bad_pkg"}
    exe = (ctx.api.call("host.executable", {}, caller=None) or {}).get("path") or "python"
    resp = await ctx.api.acall("exec.run",
                        {"argv": [exe, "-m", "pip", "install", check["pkg"]],
                         "timeout": 300}, caller=None)
    out = {"ok": bool(resp.get("ok")), "pkg": check["pkg"]}
    if not out["ok"]:
        out["error"] = resp.get("error") or tpl.get("pip_failed") or ""
    else:
        out["seconds"] = resp.get("seconds")
    return out


_TOOL_FNS = {"fetch_url": _tool_fetch, "pip_install": _tool_pip}


def _route_inspect(ctx, payload):
    """安全读包 + 环境探测 + 依赖检查：只扫描与探测，不执行包内脚本、不起外壳。

    包清单先过 scan_bundle 白名单 / 穿越 / 链接 / 上限校验；主机事实由 host 探测后
    交 env_probe、dep_plan 纯计算。缺命令 / 缺包 / 非法包名一律进阻断态，不登记产物。
    """
    tpl = _msg_tpl(ctx)
    bundle = payload.get("bundle") or {}
    files = bundle.get("files") or []
    scan = _pure.scan_bundle({"files": files, "limits": payload.get("limits"), "tpl": tpl})
    if not scan["ok"]:
        first = scan["rejected"][0]
        return {"ok": False, "code": first["code"], "scan": scan,
                "error": tpl.get(first["code"]) or first["reason"]}

    deps = bundle.get("deps") or {}
    snap = _env_snapshot(ctx, deps)
    env = _pure.env_probe({"runtime": bundle.get("runtime"), "deps": deps, "snapshot": snap})

    requirements = bundle.get("requirements") or []
    installed = []
    for req in requirements:
        chk = _pure.safe_pkg(req, tpl)
        if chk["ok"]:
            probe = ctx.api.call("host.importable", {"name": chk["pkg"]}, caller=None)
            if probe.get("importable"):
                installed.append(chk["pkg"])
    plan = _pure.dep_plan({"requirements": requirements, "installed": installed, "tpl": tpl})
    if plan["rejected"]:
        bad = plan["rejected"][0]
        return {"ok": False, "code": bad["code"], "deps": plan, "env": env,
                "error": tpl.get(bad["code"]) or bad.get("error") or ""}

    blocked = (not env["ready"]) or bool(plan["missing"]) or bool(plan["rejected"])
    pure_key = _pure.idempotent_key({"id": bundle.get("id"), "version": bundle.get("version")})
    sig = "%s|%s" % (pure_key["id"], pure_key["version"])
    dig = ctx.api.call("codec.digest", {"text": sig, "algorithm": "sha1"}, caller=None)
    key = dig.get("hex", "")[:32]
    now = ctx.api.call("clock.now", {}, caller=None)

    state = _read_tasks(ctx)
    existing = state["tasks"].get(key) or {}
    if existing.get("status") == "registered":
        # 已登记任务重跑预检：不降级、不重复建，只补一条审计留痕。
        audit = _pure.audit_record({
            "action": "inspect", "at": now.get("ts"), "source": existing.get("source"),
            "license": existing.get("license"), "version": existing.get("version"),
            "skill": existing.get("id"),
            "bundle": {"files": [a["path"] for a in scan["accepted"]],
                       "bytes": scan["totals"]["bytes"]},
            "deps": {"missing": plan["missing"], "env": env["missing"]},
            "result": {"ok": True, "reused": True}})
        existing["audit"].append(audit)
        return {"ok": True, "reused": True, "task_key": key, "scan": scan,
                "env": env, "deps": plan, "blocked": False, "status": "registered",
                "effects": [_tasks_effect(state)]}

    task = existing
    task.update({
        "key": key, "id": pure_key["id"], "version": pure_key["version"],
        "source": bundle.get("source") or "", "license": bundle.get("license") or "",
        "status": "blocked_missing_deps" if blocked else "inspected",
        "env": env, "deps": plan,
        "scan": {"accepted": scan["accepted"], "totals": scan["totals"]},
        "products": task.get("products") or {}, "audit": task.get("audit") or [],
        "rejected": task.get("rejected") or [], "at": now.get("ts"),
    })
    state["tasks"][key] = task

    audit = _pure.audit_record({
        "action": "inspect", "at": now.get("ts"), "source": task["source"],
        "license": task["license"], "version": task["version"], "skill": task["id"],
        "bundle": {"files": [a["path"] for a in scan["accepted"]], "bytes": scan["totals"]["bytes"]},
        "deps": {"missing": plan["missing"], "env": env["missing"]},
        "result": {"ok": True, "blocked": blocked}})
    task["audit"].append(audit)
    return {"ok": True, "task_key": key, "scan": scan, "env": env, "deps": plan,
            "blocked": blocked, "status": task["status"], "effects": [_tasks_effect(state)]}


async def _route_deps_install(ctx, payload):
    """隔离安装缺失依赖：--target 落到模块自有目录；固定 argv 直传，不进 shell、不提权。

    包名先过白名单校验；逐条装缺失包，失败回滚隔离目录并保留审计日志。cli/env/config
    不在此自动安装，只随计划返回待人工处理。
    """
    tpl = _msg_tpl(ctx)
    key = str(payload.get("task_key") or payload.get("key") or "").strip()
    state = _read_tasks(ctx)
    task = state["tasks"].get(key)
    if not task:
        return {"ok": False, "code": "task_not_found", "effects": [],
                "error": tpl.get("task_not_found") or ""}
    task.setdefault("audit", [])
    if task.get("status") == "registered":
        # 已登记任务重跑装依赖：不重复装、不降级。
        return {"ok": True, "reused": True, "task_key": key, "status": "registered",
                "installs": [], "plan": task.get("deps", {}).get("plan") or [], "effects": []}

    plan = task.get("deps", {}).get("plan") or []
    missing = [e for e in plan if not e.get("installed")]
    installs = []
    own = ctx.storage.own(__file__)
    target = str(own.dir("deps"))
    exe = (ctx.api.call("host.executable", {}, caller=None) or {}).get("path") or "python"
    for entry in missing:
        req = str(entry.get("requirement") or "").strip()
        chk = _pure.safe_pkg(req, tpl)
        if not chk["ok"]:
            installs.append({"pkg": chk["pkg"], "requirement": req, "ok": False,
                             "code": "bad_pkg", "error": chk["error"]})
            continue
        resp = await ctx.api.acall("exec.run",
                                   {"argv": [exe, "-m", "pip", "install",
                                             "--target", target, chk["pkg"]],
                                    "timeout": 300}, caller=None)
        installs.append({"pkg": chk["pkg"], "requirement": req, "ok": bool(resp.get("ok")),
                         "error": resp.get("error") or "", "seconds": resp.get("seconds")})

    failed = [i for i in installs if not i["ok"]]
    all_ok = not failed and not task.get("deps", {}).get("rejected")
    if failed:
        # 失败回滚：清掉本轮隔离目标目录；审计条目保留，便于追溯失败原因。
        try:
            own.remove("deps", recursive=True)
        except Exception:  # noqa: BLE001 —— 回滚失败不阻断审计留痕
            pass

    now = ctx.api.call("clock.now", {}, caller=None)
    task["status"] = "deps_ready" if all_ok else "blocked_missing_deps"
    task["installs"] = installs
    audit = _pure.audit_record({
        "action": "deps_install", "at": now.get("ts"), "source": task.get("source"),
        "license": task.get("license"), "version": task.get("version"), "skill": task.get("id"),
        "bundle": {"files": [a["path"] for a in task.get("scan", {}).get("accepted", [])],
                   "bytes": task.get("scan", {}).get("totals", {}).get("bytes", 0)},
        "deps": {"installs": installs}, "result": {"ok": all_ok, "rolled_back": bool(failed)}})
    task["audit"].append(audit)
    state["tasks"][key] = task
    return {"ok": all_ok, "plan": plan, "installs": installs, "task_key": key,
            "status": task["status"], "audit": audit, "effects": [_tasks_effect(state)]}


def _route_register(ctx, payload):
    """校验后登记角色 / 工具 / 流程：过登记守卫与流程契约，幂等重跑不重复建。

    生成物只允许新增或覆盖非 builtin；命中 builtin 岗位 / 内置工具即拒绝并给错误码。
    登记经 install_parts / install_effects 成形，不直接手写正式库数据文件。
    """
    tpl = _msg_tpl(ctx)
    draft = payload.get("draft") or {}
    meta = payload.get("meta") or {}
    key = str(payload.get("task_key") or payload.get("key") or "").strip()
    state = _read_tasks(ctx)
    task = state["tasks"].get(key)
    if not task:
        return {"ok": False, "code": "task_not_found", "effects": [],
                "error": tpl.get("task_not_found") or ""}
    task.setdefault("audit", [])
    if task.get("status") == "registered":
        return {"ok": True, "reused": True, "task_key": key,
                "products": task.get("products") or {}, "audit": task.get("audit") or [],
                "effects": []}
    if task.get("status") == "blocked_missing_deps":
        return {"ok": False, "code": "deps_blocked", "task_key": key,
                "effects": [], "error": tpl.get("deps_blocked") or ""}

    roles = _read_lib(ctx, "agent/library", "roles.yaml")
    tools = _read_lib(ctx, "agent_common/tools", "tools.yaml")
    skills = _read_lib(ctx, "agent/library", "skills.yaml")
    builtin_ids = {rid for rid, rec in roles.items()
                   if isinstance(rec, dict) and rec.get("builtin")}
    builtin_tools = {name for name, rec in tools.items()
                     if isinstance(rec, dict) and rec.get("builtin")}
    products = {"role": {"id": task.get("id") or draft.get("id") or meta.get("id") or ""},
                "tools": draft.get("tools") or []}
    guard = _pure.register_guard({"products": products,
                                  "existing": {"roles": roles, "tools": tools},
                                  "builtin_ids": builtin_ids,
                                  "builtin_tools": builtin_tools,
                                  "tpl": tpl})
    if not guard["ok"]:
        bad = guard["rejected"][0]
        task["status"] = "rejected"
        task["rejected"] = guard["rejected"]
        state["tasks"][key] = task
        return {"ok": False, "code": bad["code"], "guard": guard,
                "effects": [_tasks_effect(state)],
                "error": tpl.get(bad["code"]) or bad["reason"]}

    flow = draft.get("flow") or {}
    states = _flow_states(flow)
    contract = ctx.api.call("library.stage_contract", {"states": states}, caller=None)
    if flow.get("nodes") and not contract.get("states"):
        task["status"] = "rejected"
        task["rejected"] = [{"kind": "flow", "id": flow.get("nodes"),
                             "code": "flow_contract_invalid", "reason": "流程节点 / 边引用未闭合"}]
        state["tasks"][key] = task
        return {"ok": False, "code": "flow_contract_invalid", "guard": guard,
                "effects": [_tasks_effect(state)],
                "error": tpl.get("flow_contract_invalid") or ""}

    parts = ctx.api.call("decompose.install_parts", {
        "id": task.get("id"), "draft": draft, "meta": meta,
        "source": task.get("source"),
        "now": payload.get("now"), "tpl": tpl}, caller=None)
    if not (parts or {}).get("skill"):
        return {"ok": False, "code": "invalid_parts", "parts": parts, "effects": [],
                "error": tpl.get("invalid_parts") or ""}

    eff = _pure.install_effects({"parts": parts, "tpl": tpl, "roles": roles,
                                 "flows": _read_lib(ctx, "agent/library", "flows.yaml"),
                                 "tools": tools, "skills": skills})
    if not eff["ok"]:
        return {"ok": False, "code": "invalid_parts", "effects": [],
                "error": eff.get("error") or ""}

    now = ctx.api.call("clock.now", {}, caller=None)
    task["status"] = "registered"
    task["products"] = {"role": parts["role"]["id"],
                        "tools": [t["name"] for t in parts["tools"]],
                        "flow": bool(flow.get("nodes") or flow.get("checks"))}
    accepted = task.get("scan", {}).get("accepted", [])
    audit = _pure.audit_record({
        "action": "register", "at": now.get("ts"), "source": task.get("source"),
        "license": task.get("license"), "version": task.get("version"),
        "skill": parts["role"]["id"],
        "bundle": {"files": [a["path"] for a in accepted],
                   "bytes": task.get("scan", {}).get("totals", {}).get("bytes", 0)},
        "deps": {"tools": task["products"]["tools"]}, "result": {"ok": True}})
    task["audit"].append(audit)
    state["tasks"][key] = task
    return {"ok": True, "reused": False, "task_key": key, "parts": parts,
            "products": task["products"], "audit": audit,
            "effects": eff["effects"] + [_tasks_effect(state)]}


def _route_status(ctx, payload):
    """拆解任务状态与产物清单只读：任务台账 → 状态 / 产物引用 / 环境与依赖检查 / 审计条目。"""
    state = _read_tasks(ctx)
    items, counts, audit_tree = [], {}, []
    summary = {"blocked": 0, "registered": 0, "missing_cli": 0,
               "missing_env": 0, "missing_pkg": 0}
    for key, task in sorted(state["tasks"].items()):
        status = task.get("status") or "inspected"
        counts[status] = counts.get(status, 0) + 1
        env = task.get("env") or {}
        deps = task.get("deps") or {}
        missing_cli = (env.get("missing") or {}).get("cli") or []
        missing_env = (env.get("missing") or {}).get("env") or []
        missing_pkg = [e.get("pkg") for e in (deps.get("missing") or [])]
        summary["missing_cli"] += len(missing_cli)
        summary["missing_env"] += len(missing_env)
        summary["missing_pkg"] += len(missing_pkg)
        if status == "blocked_missing_deps":
            summary["blocked"] += 1
        if status == "registered":
            summary["registered"] += 1
        items.append({
            "key": key, "id": task.get("id"), "version": task.get("version"),
            "source": task.get("source"), "license": task.get("license"),
            "status": status, "products": task.get("products") or {},
            "env": env, "deps": deps, "installs": task.get("installs") or [],
            "audit": task.get("audit") or [], "rejected": task.get("rejected") or [],
            "at": task.get("at"),
        })
        children = [{
            "label": a.get("action") or "", "sub": a.get("at") or "",
            "children": [
                {"label": "来源", "sub": a.get("source") or "—"},
                {"label": "许可证", "sub": a.get("license") or "—"},
                {"label": "版本", "sub": a.get("version") or "—"},
            ],
        } for a in (task.get("audit") or [])]
        audit_tree.append({"label": task.get("id") or key, "badge": status,
                           "sub": task.get("source") or "", "children": children})
    return {"tasks": items, "counts": counts, "summary": summary,
            "audit_tree": audit_tree}


def _route_install(ctx, payload):
    """入库闭环：成形 Skill 单元 → 有效才合并四库并产出 write effects；无效回空 effects。

    读现有库、合并、effects 成形都在能力内；需求只调本能力再 runtime.apply。
    拆解没成功（缺标识/坏草稿）时不产出任何写盘动作，正式库不被重写。
    """
    run = payload.get("run")
    if isinstance(run, dict) and run.get("ok") is False:
        return {"ok": False, "code": run.get("code") or "run_failed", "effects": [],
                "error": run.get("error") or _msg_tpl(ctx).get("run_failed") or ""}
    src = run if isinstance(run, dict) and run.get("draft") is not None else payload
    parts = ctx.api.call("decompose.install_parts", {
        "draft": src.get("draft"), "meta": src.get("meta"),
        "source": payload.get("source"), "now": payload.get("now")}, caller=None)
    if not (parts or {}).get("skill"):
        return {"ok": False, "code": "invalid_parts", "effects": [],
                "error": (parts or {}).get("error")
                         or _msg_tpl(ctx).get("invalid_parts") or ""}

    def _read(module, path):
        row = ctx.api.call("store.read", {"module": module, "path": path}, caller=None)
        return row.get("value") or {}

    eff = _pure.install_effects({
        "parts": parts, "tpl": _msg_tpl(ctx),
        "roles": _read("agent/library", "roles.yaml"),
        "flows": _read("agent/library", "flows.yaml"),
        "tools": _read("agent_common/tools", "tools.yaml"),
        "skills": _read("agent/library", "skills.yaml")})
    return {"ok": True, "parts": parts, "effects": eff.get("effects") or []}



async def _route_run(ctx, payload):
    """拆解闭环在能力内部：模型没交答复或回的不是 JSON，都短路成错误形状，不写半截记录。

    包正文两种来源：直接粘贴的 skill_md，或给一个网页链接经 net 拉回正文；
    链接优先，拉取失败短路，不带半截内容进模型。
    """
    skill_md = payload.get("skill_md")
    url = str(payload.get("url") or "").strip()
    tpl = _msg_tpl(ctx)
    if url:
        fetched = await ctx.api.acall("net.request",
                               {"url": url, "method": "GET", "timeout": 30}, caller=None)
        if not isinstance(fetched, dict) or fetched.get("ok") is False:
            out = dict(fetched or {})
            out["ok"] = False
            out.setdefault("code", "fetch_failed")
            out.setdefault("error", tpl.get("fetch_failed") or "")
            return out
        skill_md = fetched.get("text") or ""
    if not str(skill_md or "").strip() and not url:
        return {"ok": False, "code": "empty_input",
                "error": tpl.get("empty_input") or ""}
    doc = ctx.api.call("decompose.parse_skill_doc", {
        "skill_md": skill_md,
        "requirements": payload.get("requirements"),
        "scripts": payload.get("scripts")}, caller=None)
    skills = ctx.api.call("store.read", {
        "module": "agent/library", "path": "skills.yaml"}, caller=None)
    disabled = ctx.api.call("library.disabled_skills",
                            {"skills": skills.get("value") or {}}, caller=None)
    tools = ctx.api.call("tools.list", {"disabled": disabled.get("ids") or []},
                         caller=None).get("items") or []
    prompt = ctx.api.call("decompose.promptize", {
        "system": payload.get("system"), "meta": doc.get("meta"),
        "body": doc.get("body"), "pip": doc.get("pip"),
        "scripts": doc.get("scripts"), "tools": tools}, caller=None)
    react = await ctx.api.acall("react.run", {
        "messages": prompt.get("messages"),
        "tools": _pure.tool_defs(),
        "base_url": payload.get("base_url"),
        "api_key": payload.get("api_key"),
        "model": payload.get("model"),
        "mode": payload.get("mode"),
        "max_steps": payload.get("max_steps"),
        "session": payload.get("session"),
        "cancel": payload.get("cancel")}, caller=None)
    if not isinstance(react, dict):
        return {"ok": False, "code": "no_answer", "error": tpl.get("no_answer") or ""}
    if react.get("failed"):
        return {"ok": False, "code": "no_answer",
                "error": tpl.get("no_answer") or "", "failed": react.get("failed")}
    if react.get("cancelled"):
        return {"ok": False, "code": "cancelled", "error": tpl.get("cancelled") or ""}
    last = react.get("last") or {}
    raw = last.get("content") or ""
    obj = ctx.api.call("codec.json_decode", {"text": raw}, caller=None)
    if not obj.get("ok"):
        return {"ok": False, "code": "bad_draft_json",
                "error": tpl.get("bad_draft_json") or "", "raw": raw}
    return ctx.api.call("decompose.parse", {
        "draft": obj.get("value"), "tools": tools,
        "meta": doc.get("meta"), "pip": doc.get("pip"),
        "scripts": doc.get("scripts")}, caller=None)
