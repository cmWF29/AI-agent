"""运维纯函数：总览拼装、记录成形、日志行解析成事件。取数不在这里。"""
from __future__ import annotations


def assemble(p):
    keys = ("config", "sessions", "tickets", "knowledge", "artifacts",
            "library", "projects", "demands", "tools", "docs")
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


def spans_events(p):
    """trace span 流 → 运行记录行：时间/级别/事件/详情。name 去掉 demand: 前缀再展示。"""
    rows = p.get("rows") or []
    out = []
    for r in rows:
        if not isinstance(r, dict):
            continue
        name = str(r.get("name") or "")
        status = str(r.get("status") or "ok")
        dur = float(r.get("dur_ms") or 0)
        out.append({
            "ts": r.get("start") or 0,
            "level": "info" if status in ("ok", "") else "err",
            "event": name[len("demand:"):] if name.startswith("demand:") else name,
            "detail": "%s · %.0fms" % (status, dur),
        })
    return {"lines": len(out), "events": out}


def merge_events(p):
    """两路运行记录并一路：span 流水（新→旧）在前，系统日志文件（旧→新倒成新→旧）随后。"""
    rows = list(p.get("spans") or []) + list(reversed(p.get("legacy") or []))
    return {"lines": len(rows), "events": rows}


def tail(p):
    rows = p.get("rows") or []
    n = max(1, int(p.get("lines")))
    return {"rows": rows[-n:]}


def export_path(p):
    """导出归档相对路径：exports/<name>，命名归属运维模块。"""
    return {"path": "exports/%s" % (p.get("name") or "")}


def log_line(p):
    """日志行：末尾补换行，文本拼装下沉模块，需求层不拼字符串。"""
    return {"text": (p.get("text") or "") + "\n"}
