"""项目模块：项目档案。只有纯函数，取数/落盘由需求完成。"""
from __future__ import annotations

from .private import _pure


def setup(ctx):
    """装配入口：注册纯函数；组合逻辑在 demand_engine/data/demands/projects-*.json。"""
    for name, fn in [
        ("projects.build", _pure.build),
        ("projects.view", _pure.view),
        ("projects.present", _pure.present),
        ("projects.screen", _pure.screen),
        ("projects.tree", _pure.tree),
        ("projects.archive", _pure.archive),
        ("projects.missing", _pure.missing),
        ("projects.conflict", _pure.conflict),
        ("projects.deleted", _pure.deleted),
    ]:
        ctx.api.register(name, _as_handler(fn), module="projects")
    return True


def _as_handler(fn):
    """装配适配：纯函数只收 payload，路由协议仍是 fn(ctx, payload)。"""
    return lambda ctx, payload: fn(payload)
