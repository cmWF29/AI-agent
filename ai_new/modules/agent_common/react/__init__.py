"""ReAct 模块：只提供消息/工具形状的纯计算。循环在 react-run 需求里。"""
from __future__ import annotations

from .private import _pure


def setup(ctx):
    for name, fn in [
        ("react.schemas", _pure.schemas),
        ("react.assistant", _pure.assistant),
        ("react.toolnames", _pure.toolnames),
        ("react.args", _pure.args),
        ("react.toolmsg", _pure.toolmsg),
        ("react.result", _pure.result),
    ]:
        ctx.api.register(name, lambda payload, fn=fn: fn(payload), module="react")
    ctx.api.register("react.run", _route_run, "ReAct 循环：模型→工具→再模型，闭环在能力内", module="react")
    return True


def _route_run(ctx, payload):
    """ReAct 闭环：轮次循环、终止判断、工具回填都在能力内部，需求树只留一次调用。"""
    messages = list(payload.get("messages") or [])
    steps = 0
    done = False
    cap = 200
    if (payload.get("max_steps") or 0) > 0:
        cap = payload.get("max_steps")
    schemas = ctx.api.call("react.schemas", {"tools": payload.get("tools")}, caller=None)
    gate = payload.get("cancel") or {}
    cancelled = False
    while not (steps >= cap or done):
        if gate:
            st = ctx.api.call("demand_engine.run", {
                "id": gate.get("probe"), "input": {
                    "id": gate.get("id"), "since": gate.get("since")}}, caller=None) or {}
            st = (st.get("result") if isinstance(st, dict) else None) or {}
            if st.get("cancelled"):
                cancelled = True
                break
        resp = ctx.api.call("demand_engine.run", {
            "id": "llm-chat",
            "input": {"base_url": payload.get("base_url"),
                      "api_key": payload.get("api_key"),
                      "model": payload.get("model"),
                      "messages": messages, "tools": schemas}}, caller=None)
        answer = resp.get("result") or {}
        amsg = ctx.api.call("react.assistant", {
            "content": answer.get("content"),
            "tool_calls": answer.get("tool_calls")}, caller=None)
        messages = messages + [amsg]
        steps += 1
        names = ctx.api.call("react.toolnames", {
            "tool_calls": amsg.get("tool_calls")}, caller=None)
        if not amsg.get("tool_calls") or not names:
            done = True
            continue
        for call in amsg.get("tool_calls") or []:
            fn = (call or {}).get("function") or {}
            raw = ctx.api.call("codec.json_decode", {"text": fn.get("arguments")}, caller=None)
            targs = ctx.api.call("react.args", {"value": raw.get("value")}, caller=None)
            try:
                out = ctx.api.call("tools.execute", {
                    "name": fn.get("name"), "args": targs, "defer": True,
                    "session": payload.get("session")}, caller=None)
                if isinstance(out, dict) and out.get("deferred"):
                    out = ctx.api.call("demand_engine.run", {
                        "id": out.get("demand"), "input": out.get("input") or {}}, caller=None)
            except ctx.ApiError as exc:
                # 工具报错要作为观察结果回给模型，让它自己纠错，不能掀翻整轮
                out = {"ok": False, "error": exc.message, "code": exc.code}
            enc = ctx.api.call("codec.json_encode", {"value": out}, caller=None)
            tmsg = ctx.api.call("react.toolmsg", {
                "id": (call or {}).get("id"), "name": fn.get("name"),
                "content": enc.get("text")}, caller=None)
            messages = messages + [tmsg]
    return ctx.api.call("react.result", {"messages": messages, "steps": steps,
                                          "cancelled": cancelled}, caller=None)

