"""执行后端模块：后端档案与资源守门。纯平台能力，无任何业务。"""
from __future__ import annotations

from .private import _backends, _guard


def setup(ctx):
    """装配入口。"""
    return _backends.setup(ctx)


def backends(ctx):
    return _backends.backends(ctx)


def pick(ctx, backend=""):
    return _backends.pick(ctx, backend)


def check(ctx):
    return _guard.check(ctx)
