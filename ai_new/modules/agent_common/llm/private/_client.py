"""LLM 语义实现（纯计算）：标准输入 → 载荷，响应对象 → 对话结果。

不碰网络、不碰序列化、不读配置：这三件事分别是 net / codec / config 的。
"""
from __future__ import annotations


def _sanitize(messages):
    out = []
    for m in messages or []:
        item = {"role": m.get("role") or "user"}
        if item["role"] == "assistant":
            item["content"] = m.get("content")
            if m.get("tool_calls"):
                item["tool_calls"] = m["tool_calls"]
        elif item["role"] == "tool":
            item["content"] = m.get("content") or ""
            item["tool_call_id"] = m.get("tool_call_id") or ""
        else:
            item["content"] = m.get("content") or ""
        out.append(item)
    return out


def encode(base_url=None, api_key=None, model=None, messages=None,
           tools=None, tool_choice=None, stream=False, temperature=None):
    """标准输入 → {url, headers, payload}。payload 是对象，序列化交给 codec。"""
    base = (base_url or "").rstrip("/")
    if not base:
        return {"ok": False, "error": "缺少 base_url", "code": "llm_not_configured"}
    payload = {"model": model or "", "messages": _sanitize(messages),
               "stream": bool(stream)}
    if tools:
        payload["tools"] = tools
        if tool_choice:
            payload["tool_choice"] = tool_choice
    if temperature is not None:
        payload["temperature"] = float(temperature)
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = "Bearer " + str(api_key)
    return {"ok": True, "url": base + "/chat/completions",
            "headers": headers, "payload": payload}


def decode(payload):
    """响应对象 → {content, tool_calls, finish, usage}；形状不对返回 ok=False。"""
    if not isinstance(payload, dict):
        return {"ok": False, "error": "响应不是对象", "code": "llm_bad_payload"}
    if payload.get("error"):
        return {"ok": False, "error": str(payload.get("error")), "code": "llm_error"}
    choice = (payload.get("choices") or [{}])[0]
    msg = choice.get("message") or {}
    return {"ok": True, "content": msg.get("content") or "",
            "tool_calls": msg.get("tool_calls") or None,
            "finish": choice.get("finish_reason"),
            "usage": payload.get("usage")}


def decode_sse(items):
    """SSE 事件列表（已由 codec 解析）→ 同样的对话结果。"""
    content = []
    tool_parts = {}
    finish = None
    for obj in items or []:
        choice = (obj.get("choices") or [{}])[0]
        delta = choice.get("delta") or {}
        finish = finish or choice.get("finish_reason")
        if delta.get("content"):
            content.append(delta["content"])
        for tc in delta.get("tool_calls") or []:
            idx = tc.get("index", 0)
            part = tool_parts.setdefault(idx, {"id": tc.get("id") or "", "name": "", "args": ""})
            if tc.get("id"):
                part["id"] = tc["id"]
            if tc.get("function", {}).get("name"):
                part["name"] = tc["function"]["name"]
            if tc.get("function", {}).get("arguments"):
                part["args"] += tc["function"]["arguments"]
    tool_calls = []
    for part in tool_parts.values():
        if part["name"]:
            tool_calls.append({"id": part["id"] or "call_%d" % len(tool_calls),
                               "type": "function",
                               "function": {"name": part["name"],
                                            "arguments": part["args"] or "{}"}})
    return {"ok": True, "content": "".join(content), "tool_calls": tool_calls or None,
            "finish": finish, "usage": None}
