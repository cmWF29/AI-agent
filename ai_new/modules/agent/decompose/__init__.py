"""技能拆解模块：自然语言 → 模型拆解 → 结构化草稿。

闭环（取工具名单、拼提示词、调模型、解码、成形草稿）收在 decompose.run 能力内；
需求树只编排"跑拆解 → 成形草稿记录 → 落草稿文件"，不做拼装与判断。
"""
from __future__ import annotations

from .private import _pure


def setup(ctx):
    for name, fn in [
        ("decompose.promptize", _pure.promptize),
        ("decompose.parse", _pure.parse),
        ("decompose.draft_record", _pure.draft_record),
        ("decompose.save_draft", _pure.save_draft),
        ("decompose.draft_file", _pure.draft_file),
        ("decompose.draft_get", _pure.draft_get),
        ("decompose.accept_parts", _pure.accept_parts),
    ]:
        ctx.api.register(name, lambda payload, fn=fn: fn(payload), module="decompose")
    ctx.api.register("decompose.run", _route_run,
                     "拆解闭环：取工具名单→拼提示→模型→解码→成形草稿", module="decompose")
    return True


def _route_run(ctx, payload):
    """拆解闭环在能力内部：模型没交答复或回的不是 JSON，都短路成错误形状，不写半截草稿。"""
    tools = ctx.api.call("tools.list", {}, caller=None).get("items") or []
    prompt = ctx.api.call("decompose.promptize",
                          {"text": payload.get("text"), "system": payload.get("system"),
                           "tools": tools}, caller=None)
    resp = ctx.runtime.call("llm-chat", {
        "messages": prompt.get("messages"),
        "base_url": payload.get("base_url"),
        "api_key": payload.get("api_key"),
        "model": payload.get("model"),
        "mode": payload.get("mode"),
        "cancel": payload.get("cancel")})
    if not isinstance(resp, dict) or resp.get("ok") is False:
        return resp or {"ok": False, "code": "no_answer",
                        "error": "模型未返回拆解结果"}
    raw = resp.get("content") or ""
    obj = ctx.api.call("codec.json_decode", {"text": raw}, caller=None)
    if not obj.get("ok"):
        return {"ok": False, "code": "bad_draft_json",
                "error": "拆解结果不是合法 JSON", "raw": raw}
    return ctx.api.call("decompose.parse",
                        {"draft": obj.get("value"), "tools": tools}, caller=None)
