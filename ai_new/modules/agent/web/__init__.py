"""Web 模块：控制台只认注册表/需求清单，不认识业务名词。页面读盘归 store。"""
from __future__ import annotations

from .private import _panel


def setup(ctx):
    return _panel.setup(ctx)
