"""配置模块：只做配置的读取、合并、落盘。无任何业务。"""
from __future__ import annotations

from .private import _loader

def setup(ctx):
    """装配入口：把默认配置和用户配置合并进 ctx.cfg。"""
    _loader.setup(ctx)

def get(ctx, key: str, default=None):
    """按点号路径读配置。"""
    return _loader.get(ctx, key, default)

def set_value(ctx, key: str, value):
    """按点号路径写配置，持久化到 data/config.json。"""
    return _loader.set_value(ctx, key, value)

def redacted(ctx):
    """返回脱敏后的配置视图（key 里含 token/password/key 的字段打码）。"""
    return _loader.redacted(ctx)
