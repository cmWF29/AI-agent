"""ReAct 纯函数：把响应切成消息、把工具定义切成模型能吃的形状。循环在 react-run 需求里。"""
from __future__ import annotations


def schema(p):
    props, required = {}, []
    for item in p.get("tool") or []:
        props[item["name"]] = {"type": item.get("type") or "string",
                               "description": item.get("desc") or ""}
        if item.get("required"):
            required.append(item["name"])
    return {"type": "function",
            "function": {"name": p.get("name"), "description": p.get("desc") or "",
                         "parameters": {"type": "object", "properties": props,
                                        "required": required}}}


def schemas(p):
    return [schema({"name": t["name"], "desc": t.get("desc"),
                    "tool": t.get("params")}) for t in p.get("tools") or []]


def assistant(p):
    msg = {"role": "assistant", "content": p.get("content") or ""}
    calls = p.get("tool_calls") or []
    if calls:
        msg["tool_calls"] = calls
    return msg


def toolnames(p):
    return [((c.get("function") or {}).get("name")) for c in p.get("tool_calls") or []]


def args(p):
    value = p.get("value")
    return value if isinstance(value, dict) else {}


def toolmsg(p):
    return {"role": "tool", "tool_call_id": p.get("id") or "call_0",
            "name": p.get("name") or "", "content": p.get("content") or "{}"}


def step(p):
    return {"index": p.get("index"), "content": p.get("content") or "",
            "tools": p.get("tools") or []}


def result(p):
    msgs = p.get("messages") or []
    return {"steps": p.get("steps") or 0, "messages": msgs,
            "last": msgs[-1] if msgs else None, "cancelled": bool(p.get("cancelled"))}


def toolerr(p):
    return {"error": p.get("message") or "", "code": p.get("code") or "tool_error"}
