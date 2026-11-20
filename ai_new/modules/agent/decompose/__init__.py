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
    # 拆解循环专用工具：拉文档文本、白名单装 pip 包；shell 已由通用 tools 模块注册为
    # 内置执行工具，这里只补拆解闭环的 schema 名单，不重复注册 fn。
    for tool in _pure.tool_defs():
        if ctx.tools.has(tool["name"]):
            continue
        ctx.tools.register(tool["name"], tool["desc"], tool["params"],
                           _TOOL_FNS[tool["name"]], module="decompose",
                           kinds=None, deps={}, builtin=False)
    return True


def _msg_tpl(ctx):
    """消息模板表：拆解模块自己的 data，读不到就退化成空。"""
    row = ctx.api.call("store.read", {
        "module": "agent/decompose", "path": "messages.yaml"}, caller=None)
    return row.get("value") or {}


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
        return resp or {"ok": False, "error": tpl.get("fetch_failed") or "", "code": "fetch_failed"}
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


def _route_install(ctx, payload):
    """入库闭环：成形 Skill 单元 → 有效才合并四库并产出 write effects；无效回空 effects。

    读现有库、合并、effects 成形都在能力内；需求只调本能力再 runtime.apply。
    拆解没成功（缺标识/坏草稿）时不产出任何写盘动作，正式库不被重写。
    """
    parts = ctx.api.call("decompose.install_parts", {
        "draft": payload.get("draft"), "meta": payload.get("meta"),
        "source": payload.get("source"), "now": payload.get("now")}, caller=None)
    if not (parts or {}).get("skill"):
        return {"ok": False, "effects": [],
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
            return fetched or {"ok": False, "code": "fetch_failed",
                               "error": tpl.get("fetch_failed") or ""}
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
