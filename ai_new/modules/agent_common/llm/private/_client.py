"""LLM 语义实现（纯计算）：标准输入 → 载荷，响应对象 → 对话结果。

不碰网络、不碰序列化、不读配置：这三件事分别是 net / codec / config 的。
"""
from __future__ import annotations


def _sanitize(messages):
    out = []
    if not isinstance(messages, (list, tuple)):
        return None
    for m in messages:
        if not isinstance(m, dict):
            return None
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
    clean = _sanitize(messages or [])
    if clean is None:
        return {"ok": False, "error": "messages 必须是消息对象列表",
                "code": "bad_messages"}
    payload = {"model": model or "", "messages": clean,
               "stream": bool(stream)}
    if tools:
        if not isinstance(tools, (list, tuple)):
            return {"ok": False, "error": "tools 必须是列表", "code": "bad_tools"}
        payload["tools"] = list(tools)
        if tool_choice:
            payload["tool_choice"] = tool_choice
    if temperature is not None:
        try:
            temp = float(temperature)
        except (TypeError, ValueError):
            return {"ok": False, "error": "temperature 必须是数字",
                    "code": "bad_temperature"}
        if temp != temp or temp in (float("inf"), float("-inf")):
            return {"ok": False, "error": "temperature 必须是有限数字",
                    "code": "bad_temperature"}
        payload["temperature"] = temp
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = "Bearer " + str(api_key)
    return {"ok": True, "url": base + "/chat/completions",
            "headers": headers, "payload": payload}


def _choice(payload):
    choices = payload.get("choices") if isinstance(payload, dict) else None
    if not isinstance(choices, (list, tuple)) or not choices:
        return None
    head = choices[0]
    return head if isinstance(head, dict) else None


def decode(payload):
    """响应对象 → {content, tool_calls, finish, usage}；形状不对返回 ok=False。"""
    if not isinstance(payload, dict):
        return {"ok": False, "error": "响应不是对象", "code": "llm_bad_payload"}
    if payload.get("error"):
        return {"ok": False, "error": str(payload.get("error")), "code": "llm_error"}
    choice = _choice(payload)
    if choice is None:
        return {"ok": False, "error": "响应缺少 choices", "code": "llm_bad_payload"}
    msg = choice.get("message")
    if msg is None:
        msg = {}
    if not isinstance(msg, dict):
        return {"ok": False, "error": "message 不是对象", "code": "llm_bad_payload"}
    content = msg.get("content")
    if content is not None and not isinstance(content, str):
        return {"ok": False, "error": "content 不是字符串", "code": "llm_bad_payload"}
    tool_calls = msg.get("tool_calls")
    if tool_calls is not None and not isinstance(tool_calls, (list, tuple)):
        return {"ok": False, "error": "tool_calls 不是列表", "code": "llm_bad_payload"}
    return {"ok": True, "content": content or "",
            "tool_calls": list(tool_calls) if tool_calls else None,
            "finish": choice.get("finish_reason"),
            "usage": payload.get("usage")}


def decode_sse(items):
    """SSE 事件列表（已由 codec 解析）→ 同样的对话结果。"""
    if not isinstance(items, (list, tuple)):
        return {"ok": False, "error": "SSE 事件必须是列表", "code": "llm_bad_payload"}
    content = []
    tool_parts = {}
    finish = None
    for obj in items:
        if not isinstance(obj, dict):
            return {"ok": False, "error": "SSE 事件不是对象", "code": "llm_bad_payload"}
        choice = _choice(obj)
        if choice is None:
            if "choices" in obj:
                return {"ok": False, "error": "choices 形状不合法", "code": "llm_bad_payload"}
            continue
        delta = choice.get("delta")
        if delta is None:
            delta = {}
        if not isinstance(delta, dict):
            return {"ok": False, "error": "delta 不是对象", "code": "llm_bad_payload"}
        finish = finish or choice.get("finish_reason")
        if delta.get("content"):
            if not isinstance(delta["content"], str):
                return {"ok": False, "error": "content 不是字符串", "code": "llm_bad_payload"}
            content.append(delta["content"])
        calls = delta.get("tool_calls") or []
        if not isinstance(calls, (list, tuple)):
            return {"ok": False, "error": "tool_calls 不是列表", "code": "llm_bad_payload"}
        for tc in calls:
            if not isinstance(tc, dict):
                return {"ok": False, "error": "tool_call 不是对象", "code": "llm_bad_payload"}
            idx = tc.get("index", 0)
            try:
                hash(idx)
            except TypeError:
                return {"ok": False, "error": "tool_call index 不合法",
                        "code": "llm_bad_payload"}
            part = tool_parts.setdefault(idx, {"id": tc.get("id") or "", "name": "", "args": ""})
            fn = tc.get("function") or {}
            if not isinstance(fn, dict):
                return {"ok": False, "error": "function 不是对象", "code": "llm_bad_payload"}
            if tc.get("id"):
                part["id"] = tc["id"]
            if fn.get("name"):
                part["name"] = fn["name"]
            if fn.get("arguments"):
                if not isinstance(fn["arguments"], str):
                    return {"ok": False, "error": "tool arguments 不是字符串",
                            "code": "llm_bad_payload"}
                part["args"] += fn["arguments"]
    tool_calls = []
    for part in tool_parts.values():
        if part["name"]:
            tool_calls.append({"id": part["id"] or "call_%d" % len(tool_calls),
                               "type": "function",
                               "function": {"name": part["name"],
                                            "arguments": part["args"] or "{}"}})
    return {"ok": True, "content": "".join(content), "tool_calls": tool_calls or None,
            "finish": finish, "usage": None}

def wire(p):
    """网络报文成形：请求体、响应原文与连接事实，密钥类头一律打码，只留可回查的东西。

    纯数据，不做 I/O；留存由调用方决定（当前随会话消息一并存档，原文可在前端展开）。
    """
    headers = dict(p.get("headers") or {})
    for key in list(headers):
        low = str(key).lower()
        if "key" in low or "auth" in low or "token" in low:
            headers[key] = "***"
    return {"url": p.get("url") or "", "method": p.get("method") or "POST",
            "headers": headers, "model": p.get("model") or "",
            "request": p.get("request") or "",
            "status": p.get("status"), "response": p.get("response") or "",
            "stream": bool(p.get("stream"))}
