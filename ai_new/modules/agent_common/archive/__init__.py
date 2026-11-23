"""存储治理模块：冷数据自动压缩归档 + 按需动态解压。

边界：
- 压缩是写盘业务动作，只能由需求编排调用 ``archive.compress``；本模块不在后台隐式压；
- 透明读出口在本模块读路由；store 读路径经同一解析出口读到压缩数据；
- 索引、缓存、观测台账都落在本模块自己的数据目录。
"""
from __future__ import annotations

from .private import _engine


def _resolve_abs(ctx, payload):
    """内部解析出口按平台 RPC 约定收 (ctx, payload)，转发到引擎的绝对路径签名。"""
    return _engine.resolve_abs(ctx, payload or {})


def setup(ctx):
    # resolve_abs 为内部解析出口：只给 store 读路径回调，不对外暴露 HTTP。
    ctx.api.register("archive.resolve_abs", _resolve_abs,
                     module="archive", internal=True)
    for name, fn in [
        ("archive.scan", _route_scan),
        ("archive.compress", _route_compress),
        ("archive.read_text", _engine.read_text),
        ("archive.read_bytes", _engine.read_bytes),
        ("archive.read_lines", _engine.read_lines),
        ("archive.stats", _route_stats),
        ("archive.index_query", _engine.index_query),
    ]:
        ctx.api.register(name, fn, module="archive")
    return True


def _route_scan(ctx, payload):
    return _engine.scan(ctx, payload or {})


def _route_compress(ctx, payload):
    return _engine.compress(ctx, payload or {})


def _route_stats(ctx, payload):
    return _engine.stats(ctx, payload or {})
