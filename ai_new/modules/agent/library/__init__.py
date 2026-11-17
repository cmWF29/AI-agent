"""岗位库模块：角色/流程的纯计算。取数落盘在需求里。"""
from __future__ import annotations

from .private import _pure


def setup(ctx):
    pairs = [
        ("library.list", _pure.listp),
        ("library.get", _pure.getp),
        ("library.positions", _pure.positionsp),
        ("library.position", _pure.positionp),
        ("library.design", _pure.designp),
        ("library.summary", _pure.summaryp),
        ("library.role_prompt", _pure.promptp),
        ("library.check", _pure.checkp),
        ("library.review", _pure.reviewp),
        ("library.prompt_blocks", _pure.prompt_blocks),
        ("library.kind_file", _pure.kind_file),
        ("library.prompt_path", _pure.prompt_path),
        ("library.save_record", _pure.save_record),
    ]
    for name, fn in pairs:
        ctx.api.register(name, _as_handler(fn), module="library")
    return True


def _as_handler(fn):
    return lambda ctx, payload: fn(payload)
