"""日志模块：日志数据归属与统一索引清单。成形/分组纯计算在此，落盘由需求 apply。

日志只由系统动作落盘（会话记录、工单历程、工具输出、群聊消息、系统事件），
不向 LLM 开放写口；清单条目恒 category=log、source=system。
"""
from __future__ import annotations

from .private import _pure


def setup(ctx):
    ctx.api.register("logs.record", _route_record,
                     "登记一条日志清单条目：成形→合并清单→返回写清单效果", module="logs")
    ctx.api.register("logs.group", _as_handler(_pure.group),
                     "日志清单按公共/项目/工单三级分组成形；纯分组不读正文", module="logs")
    ctx.api.register("logs.purge", _route_purge,
                     "剔除清单归属前缀（或单文件路径）下的条目；返回写清单效果", module="logs")
    return True


def _as_handler(fn):
    def handler(ctx, payload):
        payload = dict(payload or {})
        if "tpl" not in payload:
            payload["tpl"] = _msg_tpl(ctx)
        return fn(payload)
    return handler


def _msg_tpl(ctx):
    row = ctx.api.call("store.read", {
        "module": "agent/logs", "path": "messages.yaml"}, caller=None)
    return row.get("value") or {}


def _cfg_paths(ctx):
    row = ctx.api.call("config.get", {"key": "logs.paths"}, caller=None)
    return row.get("value") or {}


def _route_record(ctx, payload):
    """登记清单：不自己 apply，清单写盘效果交调用方并入 effects 串。"""
    paths = _cfg_paths(ctx)
    now = ctx.api.call("clock.now", {}, caller=None)
    rel_path = payload.get("path") or ""
    entry = _pure.entry({
        "path": rel_path,
        "source": payload.get("source") or "system",
        "layer": payload.get("layer") or "public",
        "project": payload.get("project") or "",
        "ticket": payload.get("ticket") or "",
        "kind": payload.get("kind") or "",
        "name": payload.get("name") or rel_path.rsplit("/", 1)[-1],
        "now": now.get("iso"),
    })
    index_path = paths.get("index") or "index.yaml"
    old = ctx.api.call("store.read", {
        "module": "agent/logs", "path": index_path,
        "fallback": {"entries": []}}, caller=None)
    merged = _pure.index_upsert({
        "entries": (old.get("value") or {}).get("entries") or [],
        "entry": entry})
    return {"entry": entry, "effects": [
        {"kind": "write", "module": "agent/logs", "path": index_path, "value": merged}]}


def _route_purge(ctx, payload):
    """剔除清单：不自己 apply，清单写盘效果交调用方并入 effects 串。"""
    paths = _cfg_paths(ctx)
    prefix = payload.get("prefix") or payload.get("path") or ""
    index_path = paths.get("index") or "index.yaml"
    old = ctx.api.call("store.read", {
        "module": "agent/logs", "path": index_path,
        "fallback": {"entries": []}}, caller=None)
    merged = _pure.index_purge({
        "entries": (old.get("value") or {}).get("entries") or [],
        "prefix": prefix, "paths": payload.get("paths") or []})
    return {"effects": [
        {"kind": "write", "module": "agent/logs", "path": index_path, "value": merged}]}
