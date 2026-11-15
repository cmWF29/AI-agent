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


# ---- 纯函数面（给不需要路由的内部调用，仍然不含任何 I/O） ----
def encode(ctx, **kwargs):
    return _client.encode(**kwargs)


def decode(ctx, payload):
    return _client.decode(payload)


def decode_sse(ctx, items):
    return _client.decode_sse(items)
