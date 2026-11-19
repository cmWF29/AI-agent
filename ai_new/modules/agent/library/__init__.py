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
        ("library.stage_contract", _pure.stage_contractp),
        ("library.stage_transition", _pure.stage_transitionp),
        ("library.stage_tools", _pure.stage_toolsp),
        ("library.stage_block", _pure.stage_blockp),
        ("library.stage_gaps", _pure.stage_gapsp),
        ("library.stage_conditions", _pure.stage_conditionsp),
        ("library.stage_apply_overrides", _pure.stage_apply_overridesp),
        ("library.kind_file", _pure.kind_file),
        ("library.prompt_path", _pure.prompt_path),
        ("library.save_record", _pure.save_record),
        ("library.skills_list", _pure.skills_listp),
        ("library.disabled_skills", _pure.disabled_p),
        ("library.skill_status", _pure.skill_statusp),
        ("library.skill_uninstall", _pure.skill_uninstallp),
    ]
    for name, fn in pairs:
        ctx.api.register(name, _as_handler(fn), module="library")
    return True


def _as_handler(fn):
    def handler(ctx, payload):
        row = ctx.api.call("store.read", {
            "module": "agent/library", "path": "messages.yaml"}, caller=None)
        payload = dict(payload or {})
        payload["tpl"] = row.get("value") or {}
        if "paths" not in payload:
            payload["paths"] = _cfg_paths(ctx)
        return fn(payload)
    return handler


def _cfg_paths(ctx):
    row = ctx.api.call("config.get", {"key": "library.paths"}, caller=None)
    return row.get("value") or {}
