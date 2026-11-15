"""运维纯函数：总览拼装、记录成形、日志行解析成事件。取数不在这里。"""
from __future__ import annotations


def assemble(p):
    keys = ("config", "sessions", "tickets", "knowledge", "artifacts",
            "library", "projects", "agents", "demands")
    return {k: p.get(k) or {} for k in keys}


def record(p):
    rec = {"ts": p.get("now") or "", "level": p.get("level") or "info",
           "event": p.get("hook") or ""}
    data = p.get("data")
    if isinstance(data, dict):
        for key, value in data.items():
            rec[key] = value if isinstance(value, (str, int, float, bool)) or value is None \
                else str(value)
    return rec


def line(p):
    return {"line": p.get("text") or ""}


def events(p):
    rows = p.get("rows") or []
    events = []
    for row in rows:
        if isinstance(row, dict):
            events.append(row)
        else:
            events.append({"raw": row})
    return {"lines": len(events), "events": events}


def tail(p):
    rows = p.get("rows") or []
    n = max(1, int(p.get("lines") or 50))
    return {"rows": rows[-n:]}
