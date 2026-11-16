"""LLM 语义能力：把"对话"翻译成线上的**载荷**，再把**载荷**翻译回对话结果。

它只做语义层的加减乘除：
- `encode`：给定标准输入（messages/tools/连接参数）→ {url, headers, payload}
- `decode`：给定已经解析好的响应对象 → {content, tool_calls, finish, usage}
- `decode_sse`：给定已经解析好的 SSE 事件列表 → 同样的结构

不发请求（那是 `net`）、不解析 JSON（那是 `codec`）、不读配置（那是 `config`）。
"""
from __future__ import annotations

from .private import _client


def setup(ctx):
    ctx.api.register("llm.encode", _route_encode, "对话 → 线上载荷", module="llm")
    ctx.api.register("llm.decode", _route_decode, "响应对象 → 对话结果", module="llm")
    ctx.api.register("llm.decode_sse", _route_decode_sse, "SSE 事件列表 → 对话结果", module="llm")
    ctx.api.register("llm.chat", _route_chat, "对话闭环：按配置选 api / agent 后端", module="llm")
    ctx.api.register("llm.chat_stream", _route_chat_stream, "流式对话闭环：配置→载荷→传输→SSE 解码", module="llm")
    return True


def _route_encode(ctx, payload):
    try:
        return _client.encode(
            base_url=payload.get("base_url"),
            api_key=payload.get("api_key"),
            model=payload.get("model"),
            messages=payload.get("messages") or [],
            tools=payload.get("tools"),
            tool_choice=payload.get("tool_choice"),
            stream=bool(payload.get("stream")),
            temperature=payload.get("temperature"),
        )
    except ctx.ApiError as exc:
        return {"ok": False, "error": exc.message, "code": exc.code}


def _route_decode(ctx, payload):
    return _client.decode(payload.get("payload") or {})


def _route_decode_sse(ctx, payload):
    return _client.decode_sse(payload.get("items") or [])


def _encode_call(ctx, payload, stream):
    # 配置是缺省值，调用方显式给的优先；明文只在能力内部流转，不经 config.get 的脱敏面
    cfgv = dict((getattr(ctx, "cfg", None) or {}).get("llm") or {})
    for key in ("base_url", "api_key", "model"):
        if payload.get(key):
            cfgv[key] = payload.get(key)
    return ctx.api.call("llm.encode", {
        "base_url": cfgv.get("base_url"),
        "api_key": cfgv.get("api_key"),
        "model": cfgv.get("model"),
        "messages": payload.get("messages") or [],
        "tools": payload.get("tools"),
        "tool_choice": payload.get("tool_choice"),
        "temperature": payload.get("temperature"),
        "stream": stream,
    }, caller=None)


def _promptize(payload):
    """把标准对话拼成一段纯文本：外部 agent 只认一段话，不认角色数组。"""
    lines = []
    for msg in payload.get("messages") or []:
        role = (msg or {}).get("role") or "user"
        text = (msg or {}).get("content") or ""
        if not str(text).strip():
            continue
        lines.append("## %s\n%s" % (role, text))
    return {"text": "\n\n".join(lines), "chars": len("\n\n".join(lines))}


def _mode(ctx, payload):
    """后端选择：调用方显式给的优先，其次配置；只认 api / agent 两种。"""
    cfgv = dict((getattr(ctx, "cfg", None) or {}).get("llm") or {})
    want = str(payload.get("mode") or cfgv.get("mode") or "api").lower()
    return "agent" if want == "agent" else "api"


def _route_chat(ctx, payload):
    if _mode(ctx, payload) == "agent":
        return _chat_agent(ctx, payload)
    enc = _encode_call(ctx, payload, False)
    if not enc.get("ok"):
        return enc
    body = ctx.api.call("codec.json_encode", {"value": enc.get("payload")}, caller=None)
    resp = ctx.api.call("net.request", {
        "url": enc.get("url"), "method": "POST",
        "headers": enc.get("headers"), "body": body.get("text"),
        "timeout": payload.get("timeout")}, caller=None)
    if not resp.get("ok"):
        return {"ok": False, "error": resp.get("error"), "code": "net_error"}
    obj = ctx.api.call("codec.json_decode", {"text": resp.get("text")}, caller=None)
    if not obj.get("ok"):
        return obj
    return ctx.api.call("llm.decode", {"payload": obj.get("value")}, caller=None)


def _chat_agent(ctx, payload):
    """外部 agent 后端：拼一段话 → 起进程 → 收回文本。

    agent 自己会调工具、自己跑完，所以这里只交一句最终答复；
    没有 tool_calls，ReAct 循环据此自然收口。
    """
    cfgv = dict((getattr(ctx, "cfg", None) or {}).get("llm") or {})
    agent = dict(cfgv.get("agent") or {})
    argv = [str(a) for a in (agent.get("command") or [])]
    if not argv:
        return {"ok": False, "code": "no_agent_command",
                "error": "agent 模式没有配置 llm.agent.command"}
    text = _promptize({"messages": payload.get("messages") or []})["text"]
    has_slot = any("{prompt}" in a for a in argv)
    filled = [a.replace("{prompt}", text) for a in argv]
    resp = ctx.api.call("exec.run", {
        "argv": filled,
        "stdin": "" if has_slot else text,
        "cwd": agent.get("cwd") or "",
        "timeout": agent.get("timeout") or cfgv.get("timeout") or 600,
        "cancel": payload.get("cancel") or {},
    }, caller=None)
    if not resp.get("ok"):
        return {"ok": False, "code": "agent_failed", "error": resp.get("error"),
                "killed": resp.get("killed")}
    return {"role": "assistant", "content": (resp.get("out") or "").strip(),
            "tool_calls": [], "backend": "agent", "seconds": resp.get("seconds")}


def _route_chat_stream(ctx, payload):
    enc = _encode_call(ctx, payload, True)
    if not enc.get("ok"):
        return enc
    body = ctx.api.call("codec.json_encode", {"value": enc.get("payload")}, caller=None)
    resp = ctx.api.call("net.request", {
        "url": enc.get("url"), "method": "POST",
        "headers": enc.get("headers"), "body": body.get("text"),
        "timeout": payload.get("timeout")}, caller=None)
    if not resp.get("ok"):
        return {"ok": False, "error": resp.get("error"), "code": "net_error"}
    ev = ctx.api.call("codec.sse_decode", {"text": resp.get("text")}, caller=None)
    if not ev.get("ok"):
        return ev
    return ctx.api.call("llm.decode_sse", {"items": ev.get("items")}, caller=None)


# ---- 纯函数面（给不需要路由的内部调用，仍然不含任何 I/O） ----
def encode(ctx, **kwargs):
    return _client.encode(**kwargs)


def decode(ctx, payload):
    return _client.decode(payload)


def decode_sse(ctx, items):
    return _client.decode_sse(items)
