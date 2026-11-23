"""运维纯函数：总览拼装、记录成形、日志行解析成事件。取数不在这里。"""
from __future__ import annotations


# ---- 首屏概览投影（字段白名单）----
# 总览面板只认统计条与运行环境那几个字段；完整记录仍走各自清单按需接口
# （session-list / ticket-list / projects-list / artifacts-index …），不在首屏大包里捎带。
_SESSION_BRIEF = ("id", "kind", "name", "ticket", "role", "project",
                  "status", "created", "updated", "summary")
_TICKET_BRIEF = ("id", "title", "status", "project", "kind", "pm",
                  "created", "updated", "closed")
_PROJECT_BRIEF = ("id", "name", "archived", "created", "root")
_TOOLS_KEEP = ("total", "ready", "missing_tools", "can_install",
               "install_blocked", "pip_missing", "manual_missing")


def _source_result(src):
    """需求回包信封 {ok, demand, result, calls}：概览只取 result 层。"""
    if isinstance(src, dict):
        res = src.get("result")
        return res if isinstance(res, dict) else {}
    return {}


def _brief_items(items, fields):
    """列表项白名单投影：只留概览需要的标量字段，原文/消息/角色细节不下发首屏。"""
    out = []
    for it in items or []:
        if isinstance(it, dict):
            out.append({k: it.get(k) for k in fields})
    return out


def _project_overview(src):
    res = _source_result(src)
    items = _brief_items(res.get("items"), _PROJECT_BRIEF)
    archived = [it.get("id") for it in items if it.get("archived")]
    return {"result": {"items": items, "archived": archived}}


def _config_overview(src):
    cfg = src if isinstance(src, dict) else {}
    server = cfg.get("server") if isinstance(cfg.get("server"), dict) else {}
    auth = server.get("auth") if isinstance(server.get("auth"), dict) else {}
    llm = cfg.get("llm") if isinstance(cfg.get("llm"), dict) else {}
    return {"server": {"host": server.get("host"), "port": server.get("port"),
                       "version": server.get("version"),
                       "auth": {"enabled": auth.get("enabled")}},
            "llm": {"base_url": llm.get("base_url")}}


def assemble(p):
    """首屏总览：按白名单投影各源；完整数据留在各自按需清单接口，不靠删数据瘦身。"""
    p = p or {}
    sessions_res = _source_result(p.get("sessions"))
    tickets_res = _source_result(p.get("tickets"))
    knowledge_res = _source_result(p.get("knowledge"))
    artifacts_res = _source_result(p.get("artifacts"))
    library_res = _source_result(p.get("library"))
    tools_res = _source_result(p.get("tools"))
    docs_res = _source_result(p.get("docs"))
    return {
        "config": _config_overview(p.get("config")),
        "sessions": {"result": {"items": _brief_items(sessions_res.get("items"),
                                                      _SESSION_BRIEF)}},
        "tickets": {"result": {"items": _brief_items(tickets_res.get("items"),
                                                     _TICKET_BRIEF)}},
        "knowledge": {"result": {"counts": dict(knowledge_res.get("counts") or {})}},
        "artifacts": {"result": {k: artifacts_res.get(k)
                                  for k in ("files", "bytes", "chars")}},
        "library": {"result": {"counts": dict(library_res.get("counts") or {})}},
        "projects": _project_overview(p.get("projects")),
        "tools": {"result": {k: tools_res.get(k) for k in _TOOLS_KEEP}},
        "docs": {"result": {"counts": dict(docs_res.get("counts") or {}),
                             "items": _brief_items(
                                 docs_res.get("items"),
                                 ("doc_kind", "layer", "name", "path",
                                  "project", "ticket", "source", "type"))}},
    }


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
