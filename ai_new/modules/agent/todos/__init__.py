"""待办模块：模型自生成的 todolist，增删查改只走 todo 工具；状态存会话快照。

流程状态机是岗位预定的、模型必须遵守；待办是模型自己排的分步计划，不等价于流程，
所以两者分开放：流程在 rec.stages，待办在 rec.todos，视图各自显式呈现。
"""
from __future__ import annotations

from .private import _pure

def _limit(ctx):
    """待办上限只有一处来源：配置；读不到就按 0 处理（等于不收新条目），不在这里写死。"""
    v = ctx.api.call("config.get", {"key": "todos.max_items"}, caller=None).get("value")
    return int(v or 0)


def _msg_tpl(ctx):
    """消息模板表：待办模块自己的 data，读不到就退化成空。"""
    row = ctx.api.call("store.read", {
        "module": "agent/todos", "path": "messages.yaml"}, caller=None)
    return row.get("value") or {}


def setup(ctx):
    ctx.api.register("todos.apply", _route_apply,
                     "待办增删查改：纯函数成形，回落盘用的会话补丁", module="todos")
    ctx.api.register("todos.context", _route_context,
                     "待办上下文：当前清单拼成一条 system 消息", module="todos")
    if not ctx.tools.has("todo"):
        ctx.tools.register(
            "todo",
            _msg_tpl(ctx).get("todo_tool_desc") or "",
            [{"name": "action", "type": "string", "required": True,
             "desc": _msg_tpl(ctx).get("todo_tool_action") or ""},
             {"name": "id", "type": "string", "required": False,
              "desc": "待办 id（update/remove 必填）"},
             {"name": "text", "type": "string", "required": False,
              "desc": "待办正文（add 必填）"},
             {"name": "status", "type": "string", "required": False,
              "desc": "pending / doing / done"},
             {"name": "items", "type": "list", "required": False,
              "desc": _msg_tpl(ctx).get("todo_tool_items") or ""}],
            None, module="todos", kinds=None, deps={}, builtin=True,
            demand="todo-write")
    return True


def _route_apply(ctx, payload):
    """待办动作：当前表 + 本次参数 → 新表；有改动才回会话补丁，由会话快照一并落盘。"""
    payload = dict(payload or {})
    if not isinstance(payload.get("args"), dict):
        # 工具经需求进来时入参就是工具参数本身，直接当动作参数用
        payload["args"] = payload
    payload["tpl"] = _msg_tpl(ctx)
    payload["limit"] = _limit(ctx)
    out = _pure.apply_ops(payload)
    if out.get("ok") and out.get("changed"):
        out["session_patch"] = {"todos": out["todos"]}
        out["tip"] = _msg_tpl(ctx).get("todowrite_tip") or ""
    return out


def _route_context(ctx, payload):
    """待办上下文：拼成 system 消息；空表回 None 让编排跳过。"""
    payload = dict(payload or {})
    payload["tpl"] = _msg_tpl(ctx)
    payload["limit"] = _limit(ctx)
    return _pure.context(payload)

