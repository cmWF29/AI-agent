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
        ("decompose.merge_tools", _pure.merge_tools),
        ("decompose.install_parts", _pure.install_parts),
    ]:
        ctx.api.register(name, lambda payload, fn=fn: fn(payload), module="decompose")
    ctx.api.register("decompose.run", _route_run,
                     "拆解闭环：解析包内容→取工具名单→拼提示→ReAct 拉装→模型→解码→成形入库记录",
                     module="decompose")
    # 拆解循环专用受限工具：只开放拉文档文本与白名单装 pip 包，不进普通会话工具名单。
    for tool in _pure.tool_defs():
        ctx.tools.register(tool["name"], tool["desc"], tool["params"],
                           _TOOL_FNS[tool["name"]], module="decompose",
                           kinds=None, deps={}, builtin=False)
    return True


def _tool_fetch(ctx, args, session=None):
    """拆解期只读拉取 http(s) 文档文本；非 http(s) 直接拒，不走任意地址。"""
    url = str((args or {}).get("url") or "").strip()
    if not url:
        return {"ok": False, "error": "缺少 url", "code": "bad_request"}
    if not (url.startswith("http://") or url.startswith("https://")):
        return {"ok": False, "error": "只允许 http(s) 链接", "code": "bad_url"}
    resp = ctx.api.call("net.request",
                        {"url": url, "method": "GET", "timeout": 30}, caller=None)
    if not isinstance(resp, dict) or resp.get("ok") is False:
        return resp or {"ok": False, "error": "链接拉取失败", "code": "fetch_failed"}
    return {"ok": True, "url": url, "text": resp.get("text") or ""}


def _tool_pip(ctx, args, session=None):
    """拆解期白名单装单个 pip 包：包名先过纯函数校验，固定 argv 直传，不经 shell。"""
    check = _pure.safe_pkg((args or {}).get("pkg"))
    if not check.get("ok"):
        return {"ok": False, "error": check.get("error"), "code": "bad_pkg"}
    exe = (ctx.api.call("host.executable", {}, caller=None) or {}).get("path") or "python"
    resp = ctx.api.call("exec.run",
                        {"argv": [exe, "-m", "pip", "install", check["pkg"]],
                         "timeout": 300}, caller=None)
    out = {"ok": bool(resp.get("ok")), "pkg": check["pkg"]}
    if not out["ok"]:
        out["error"] = resp.get("error") or "pip 安装失败"
    else:
        out["seconds"] = resp.get("seconds")
    return out


_TOOL_FNS = {"fetch_url": _tool_fetch, "pip_install": _tool_pip}



def _route_run(ctx, payload):
    """拆解闭环在能力内部：模型没交答复或回的不是 JSON，都短路成错误形状，不写半截记录。

    包正文两种来源：直接粘贴的 skill_md，或给一个网页链接经 net 拉回正文；
    链接优先，拉取失败短路，不带半截内容进模型。
    """
    skill_md = payload.get("skill_md")
    url = str(payload.get("url") or "").strip()
    if url:
        fetched = ctx.api.call("net.request",
                               {"url": url, "method": "GET", "timeout": 30}, caller=None)
        if not isinstance(fetched, dict) or fetched.get("ok") is False:
            return fetched or {"ok": False, "code": "fetch_failed",
                               "error": "链接拉取失败"}
        skill_md = fetched.get("text") or ""
    if not str(skill_md or "").strip() and not url:
        return {"ok": False, "code": "empty_input",
                "error": "请粘贴 Skill.md 正文、拖入文件或填写链接"}
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
    react = ctx.api.call("react.run", {
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
        return {"ok": False, "code": "no_answer", "error": "模型未返回拆解结果"}
    if react.get("failed"):
        return {"ok": False, "code": "no_answer",
                "error": "模型未返回拆解结果", "failed": react.get("failed")}
    if react.get("cancelled"):
        return {"ok": False, "code": "cancelled", "error": "拆解已被打断"}
    last = react.get("last") or {}
    raw = last.get("content") or ""
    obj = ctx.api.call("codec.json_decode", {"text": raw}, caller=None)
    if not obj.get("ok"):
        return {"ok": False, "code": "bad_draft_json",
                "error": "拆解结果不是合法 JSON", "raw": raw}
    return ctx.api.call("decompose.parse", {
        "draft": obj.get("value"), "tools": tools,
        "meta": doc.get("meta"), "pip": doc.get("pip"),
        "scripts": doc.get("scripts")}, caller=None)
