"""健康纯函数：探针成形、聚合组装。输入都是别人给的快照。"""
from __future__ import annotations


def live(p):
    return {"ok": True, "name": "ai_new",
            "uptime": int((p.get("now") or 0) - (p.get("started") or 0))}


def assemble(p):
    items = (p.get("tickets") or {}).get("items") or []
    counts = {}
    for item in items:
        key = item.get("status")
        counts[key] = counts.get(key, 0) + 1
    host = p.get("host") or {}
    disk = {"total_mb": int((host.get("total_gb") or 0) * 1024),
            "free_mb": int((host.get("free_gb") or 0) * 1024)} if host else {}
    library = p.get("library") or {}
    library_inner = library.get("result") or {}
    return {
        "ok": True,
        "uptime": int((p.get("now") or 0) - (p.get("started") or 0)),
        "modules": p.get("modules") or [],
        "sessions": p.get("sessions") or {},
        "tickets": {"total": len(items), "by_status": counts},
        "knowledge": p.get("knowledge") or {},
        "artifacts": p.get("artifacts") or {},
        "library": {"counts": library_inner.get("counts")},
        "disk": disk,
    }
