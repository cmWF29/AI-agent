"""日志模块：日志数据归属与统一索引清单。成形/分组纯计算在此，落盘由需求 apply。

日志只由系统动作落盘（会话记录、工单历程、工具输出、群聊消息、系统事件），
不向 LLM 开放写口；清单条目恒 category=log、source=system。
"""
from __future__ import annotations

from .private import _pure


def setup(ctx):
    ctx.api.register("logs.record", _route_record,
                     "登记一条日志清单条目：成形→合并清单→返回写清单效果", module="logs")
    # logs.group 视图分组由视图需求编排调用，待 F 批次接入视图需求时再注册。
    return True


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
