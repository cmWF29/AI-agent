"""会话运行相关的纯函数：追加消息、改状态、收尾、状态计数。"""
from __future__ import annotations


def appendmsg(p):
    rec = dict(p.get("rec") or {})
    msgs = list(rec.get("messages") or [])
    msgs.append({"role": "user", "content": p.get("text") or ""})
    rec["messages"] = msgs
    rec["updated"] = p.get("now") or ""
    if rec.get("status") in ("idle", "gone", None):
        rec["status"] = "queued"
    return rec


def mark(p):
    rec = dict(p.get("rec") or {})
    rec["status"] = p.get("status") or "running"
    rec["updated"] = p.get("now") or ""
    return rec


def finish(p):
    rec = dict(p.get("rec") or {})
    out = p.get("out") or {}
    base = list(rec.get("messages") or [])
    msgs = list(out.get("messages") or base)
    # 运行期间用户又发了消息：它们在 latest 里，不在本轮快照里，必须接在后面，否则被覆盖丢失
    fresh = list((p.get("latest") or {}).get("messages") or [])
    if len(fresh) > len(base):
        msgs = msgs + fresh[len(base):]
    rec["messages"] = msgs
    rec["status"] = "idle"
    rec["steps"] = out.get("steps") or 0
    rec["updated"] = p.get("now") or ""
    last = out.get("last") or {}
    if out.get("cancelled"):
        rec["result"] = {"summary": "（已打断）", "at": p.get("now") or "", "cancelled": True}
    else:
        rec["result"] = {"summary": (last.get("content") or "")[:500], "at": p.get("now") or ""}
    return rec


def reply(p):
    rec = p.get("rec") or {}
    msgs = rec.get("messages") or []
    last = next((m for m in reversed(msgs) if m.get("role") == "assistant"), None)
    return {"id": rec.get("id") or p.get("id"), "status": rec.get("status"),
            "content": (last or {}).get("content") or "", "steps": rec.get("steps", 0)}


def statsp(p):
    statuses = {}
    for it in p.get("items") or []:
        key = it.get("status") or "unknown"
        statuses[key] = statuses.get(key, 0) + 1
    return {"active": sum(1 for it in (p.get("items") or []) if it.get("status") == "running"),
            "max_concurrent": int(p.get("max") or 0), "statuses": statuses}
