"""频道纯函数：拆行、拼消息、取窗口、算游标。不碰盘、不取时间。"""
from __future__ import annotations


def split(p):
    return {"lines": [line for line in (p.get("text") or "").splitlines() if line.strip()]}


def make(p):
    rows = p.get("rows") or []
    channel = p.get("channel") or "default"
    seq = len(rows) + 1
    return {"id": "%s-%06d" % (channel, seq), "seq": seq, "channel": channel,
            "role": p.get("role") or "user", "content": p.get("content") or "",
            "ts": int(p.get("ts") or 0), "meta": p.get("meta") or {}}


def tail(p):
    rows = [r for r in (p.get("rows") or []) if isinstance(r, dict)]
    raw = p.get("limit")
    default_limit = int(p.get("default_limit"))
    max_limit = int(p.get("max_limit"))
    n = max(1, min(int(raw) if raw is not None else default_limit, max_limit))
    return {"channel": p.get("channel") or "default",
            "cursor": rows[-1]["seq"] if rows else 0,
            "messages": [{"role": r.get("role"), "content": r.get("content")} for r in rows[-n:]]}


def since(p):
    after = int(p.get("cursor") or 0)
    rows = [r for r in (p.get("rows") or []) if isinstance(r, dict) and int(r.get("seq") or 0) > after]
    return {"items": rows, "cursor": rows[-1]["seq"] if rows else after}


def channels(p):
    out = []
    for row in p.get("rows") or []:
        name = str(row.get("path") or "").rsplit("/", 1)[-1]
        if name.endswith(".jsonl"):
            name = name[:-6]
        lines = [x for x in (row.get("text") or "").splitlines() if x.strip()]
        out.append({"channel": name, "count": len(lines), "last_ts": None})
    return {"channels": out}


def bad(p):
    return {"ok": False, "code": p.get("code") or "bad_role",
            "status": p.get("status") or 400, "error": p.get("error") or "参数不合法"}
