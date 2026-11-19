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
    ctx.api.register("llm.decode_sse", _route_decode_sse, "SSE 事件列表 → 对话结果", module="llm")
    ctx.api.register("llm.chat", _route_chat, "对话闭环：HTTP 直连 → SSE 解码", module="llm")
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


def _fail(ctx, resp):
    """传输失败：优先透传上游错误体里的 error.code，否则回落到 net 归类码。"""
    code = resp.get("code") or "net_error"
    detail = resp.get("error")
    if detail:
        dec = ctx.api.call("codec.json_decode", {"text": detail}, caller=None)
        if dec.get("ok"):
            obj = dec.get("value")
            inner = obj.get("error") if isinstance(obj, dict) else None
            if isinstance(inner, dict) and inner.get("code"):
                code = inner["code"]
    return {"ok": False, "error": detail, "code": code}


def _route_chat(ctx, payload):
    enc = _encode_call(ctx, payload, True)
    if not enc.get("ok"):
        return enc
    body = ctx.api.call("codec.json_encode", {"value": enc.get("payload")}, caller=None)
    stream_key = (payload.get("cancel") or {}).get("id") or ""
    resp = ctx.api.call("net.request_stream", {
        "url": enc.get("url"), "method": "POST",
        "headers": enc.get("headers"), "body": body.get("text"),
        "timeout": payload.get("timeout"), "stream_key": stream_key}, caller=None)
    if not resp.get("ok"):
        return _fail(ctx, resp)
    return ctx.api.call("llm.decode_sse", {"items": resp.get("items") or []}, caller=None)


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
        return _fail(ctx, resp)
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
