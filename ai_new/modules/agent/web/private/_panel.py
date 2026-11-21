"""Web 面板：控制台静态资源定位。

读盘归 store（面板只经 `store.read_text` 取字节），web 自己只做路径合法化与 MIME 猜测，
不认识页面内容，也不直接碰文件系统。
"""
from __future__ import annotations

from . import _pure


class WebPanel:
    def __init__(self, ctx):
        self.ctx = ctx

    def asset(self, ctx, path):
        rel = _pure.rel({"path": path})["path"]
        parts = [seg for seg in rel.split("/") if seg not in ("", ".")]
        if any(seg == ".." for seg in parts):
            raise ctx.ApiError("路径越界: %s" % rel, code="path_escape", status=403)
        for b in (ctx.api.call("config.get", {"key": "web.bundle"},
                               caller=None).get("value") or []):
            if rel == str(b.get("out") or ""):
                chunks = []
                for part in (b.get("parts") or []):
                    got = ctx.api.call("store.read_text",
                                       {"module": "agent/web", "path": _join(ctx, part), "fallback": ""})
                    chunks.append(got.get("value") or "")
                return {"content": "\n;\n".join(chunks),
                        "content_type": "application/javascript; charset=utf-8",
                        "no_cache": True}
        t = _cfg_paths(ctx).get("console") or ""
        target = t.format(rel="/".join(parts)) if t else "/".join(parts)
        out = ctx.api.call("store.read_text",
                           {"module": "agent/web", "path": target, "fallback": ""})
        if not out.get("exists"):
            raise ctx.ApiError("资源不存在: %s" % rel, code="no_asset", status=404)
        ctype = _pure.mime({"path": rel})["type"]
        return {"content": out.get("value") or "", "content_type": ctype}


def _join(ctx, part):
    t = _cfg_paths(ctx).get("console") or ""
    return t.format(rel=str(part))


def _cfg_paths(ctx):
    row = ctx.api.call("config.get", {"key": "web.paths"}, caller=None)
    return row.get("value") or {}


def _as_handler(fn):
    def handler(ctx, payload):
        payload = dict(payload or {})
        if "paths" not in payload:
            payload["paths"] = _cfg_paths(ctx)
        return fn(payload)
    return handler


def setup(ctx):
    ctx.web = WebPanel(ctx)
    for name, fn in [("web.rel", _pure.rel), ("web.mime", _pure.mime),
                     ("web.info", _pure.info), ("web.gate", _pure.gate),
                     ("web.console_path", _pure.console_path)]:
        ctx.api.register(name, _as_handler(fn), module="web")
    return True
