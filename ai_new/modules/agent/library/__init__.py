"""岗位库模块：角色/流程的纯计算。取数落盘在需求里。"""
from __future__ import annotations

from .private import _pure


def setup(ctx):
    pairs = [
        ("library.list", _pure.listp),
        ("library.get", _pure.getp),
        ("library.positions", _pure.positionsp),
        ("library.position", _pure.positionp),
        ("library.bind_tools", _pure.bind_tools),
        ("library.design", _pure.designp),
        ("library.summary", _pure.summaryp),
        ("library.role_prompt", _pure.promptp),
        ("library.check", _pure.checkp),
        ("library.review", _pure.reviewp),
        ("library.prompt_blocks", _pure.prompt_blocks),
        ("library.stage_contract", _pure.stage_contractp),
        ("library.stage_transition", _pure.stage_transitionp),
        ("library.stage_tools", _pure.stage_toolsp),
        ("library.flow_context", _pure.flow_contextp),
        ("library.stage_gaps", _pure.stage_gapsp),
        ("library.stage_conditions", _pure.stage_conditionsp),
        ("library.stage_apply_overrides", _pure.stage_apply_overridesp),
        ("library.stage_refs", _pure.stage_refsp),
        ("library.kind_file", _pure.kind_file),
        ("library.prompt_path", _pure.prompt_path),
        ("library.prompt_fold", _pure.prompt_fold),
        ("library.save_record", _pure.save_record),
        ("library.skills_list", _pure.skills_listp),
        ("library.disabled_skills", _pure.disabled_p),
        ("library.skill_status", _pure.skill_statusp),
        ("library.skill_uninstall", _pure.skill_uninstallp),
    ]
    for name, fn in pairs:
        ctx.api.register(name, _as_handler(fn), module="library")
    # PM 的提示词治理权：读提示词、追加/替换提示词规则；只放行 PM，不碰源码目录。
    if getattr(ctx, "tools", None) is None:
        return True
    ctx.tools.register_demand("prompt_read", "读岗位当前提示词（只读）",
                              [{"name": "role", "type": "string", "desc": "岗位 id（pm/developer/tester/reviewer/...）", "required": True}],
                              demand="library-role-prompt", module="library", kinds=["pm"])
    ctx.tools.register_demand("prompt_patch", "改岗位提示词：追加治理规则或整段替换（PM 专用）",
                              [{"name": "role", "type": "string", "desc": "岗位 id", "required": True},
                               {"name": "append", "type": "string", "desc": "追加规则；mode=append 时必填", "required": False},
                               {"name": "reason", "type": "string", "desc": "为什么要改，写清本轮空转/重复动作证据", "required": True},
                               {"name": "mode", "type": "string", "desc": "append（默认）/replace", "required": False},
                               {"name": "text", "type": "string", "desc": "mode=replace 时的完整新提示词", "required": False}],
                              demand="library-prompt-patch", module="library", kinds=["pm"])
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
