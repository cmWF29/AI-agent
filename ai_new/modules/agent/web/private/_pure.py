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


def gate(p):
    """静态资源的登录门槛：页面要登录，登录页与壳资源放行。

    壳资源（js/css/图标/字体）不含业务数据；页面里才有需求清单与数据入口，
    所以未登录时在页面这一层就重定向，不等前端跑完再去 401。
    """
    path = (p.get("path") or "manage.html").strip("/")
    name = path.rsplit("/", 1)[-1]
    ext = name.rsplit(".", 1)[1].lower() if "." in name else ""
    if name == "login.html":
        return {"public": True, "to": "login.html"}
    if ext != "html":
        return {"public": True, "to": ""}
    return {"public": False, "to": "login.html"}


def info(p):
    return {"name": "ai_new", "console": p.get("console") or {},
            "routes": p.get("routes") or [], "demands": p.get("demands") or []}


def console_path(p):
    """控制台资源相对路径：模板由需求层配置表给出，纯函数只填参。"""
    paths = p.get("paths") or {}
    t = paths.get("console") or ""
    rel = (p.get("path") or "").strip("/")
    return {"path": t.format(rel=rel) if t else rel}
