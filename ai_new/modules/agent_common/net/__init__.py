"""出站网络能力：把请求发出去、把响应收回来。不认识对面是谁。

**为什么单独成模块**：网络是"与外界打交道"的能力，`llm` 自己 new 一个 urllib 请求，
就等于把传输耦合进了一个只该负责"对话"的模块 —— 换通道（代理、内网网关、本地桩）
就得改 llm。收编之后，`llm` 只调 `net.request`，换实现只换 net。
"""
from __future__ import annotations

from .private import _client


def setup(ctx):
    ctx.api.register("net.request", _route_request, "出站 HTTP(S) 请求", module="net")
    ctx.api.register("net.request_stream", _route_request_stream,
                     "出站 SSE 流式请求：逐帧推草稿槽并汇总事件", module="net")
    return True


def _route_request(ctx, payload):
    return _client.request(
        ctx,
        payload.get("url"),
        method=payload.get("method") or "GET",
        headers=payload.get("headers") or {},
        body=payload.get("body"),
        timeout=payload.get("timeout"),
    )


def _route_request_stream(ctx, payload):
    return _client.request_stream(
        ctx,
        payload.get("url"),
        method=payload.get("method") or "POST",
        headers=payload.get("headers") or {},
        body=payload.get("body"),
        timeout=payload.get("timeout"),
        stream_key=payload.get("stream_key") or "",
    )


def request(ctx, url, method="GET", headers=None, body=None, timeout=None):
    return _client.request(ctx, url, method=method, headers=headers, body=body, timeout=timeout)


def request_stream(ctx, url, method="POST", headers=None, body=None, timeout=None,
                   stream_key=""):
    return _client.request_stream(ctx, url, method=method, headers=headers, body=body,
                                  timeout=timeout, stream_key=stream_key)
