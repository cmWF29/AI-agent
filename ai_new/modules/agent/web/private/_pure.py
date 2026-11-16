"""控制台纯函数：路径合法化、MIME 猜测、清单成形。读盘归 store。"""
from __future__ import annotations

_TYPES = {"html": "text/html; charset=utf-8", "css": "text/css; charset=utf-8",
          "js": "application/javascript; charset=utf-8", "json": "application/json", "yaml": "application/yaml; charset=utf-8",
          "svg": "image/svg+xml", "png": "image/png", "jpg": "image/jpeg",
          "ico": "image/x-icon", "woff2": "font/woff2"}


def rel(p):
    path = (p.get("path") or "manage.html").strip("/")
    return {"path": path}


def mime(p):
    name = (p.get("path") or "").rsplit(".", 1)
    ext = name[1].lower() if len(name) == 2 else ""
    return {"type": _TYPES.get(ext, "application/octet-stream")}


def info(p):
    return {"name": "ai_new", "console": p.get("console") or {},
            "routes": p.get("routes") or [], "demands": p.get("demands") or []}
