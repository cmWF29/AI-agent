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
        ("react.context_view", _pure.context_view),
        ("react.classify_tool", _pure.classify_tool),
        ("react.parse_final", _pure.parse_final),
        ("react.strip_fence", _pure.strip_fence),
        ("react.attach_protocol", _pure.attach_protocol),
    ]:
        ctx.api.register(name, lambda payload, fn=fn: fn(payload), module="react")
    ctx.api.register("react.run", _route_run, "ReAct 循环：模型→工具→再模型，闭环在能力内", module="react")
    return True


def _tool_threshold(ctx, payload):
    cfgv = dict((getattr(ctx, "cfg", None) or {}).get("sessions") or {})
    ctxv = dict(cfgv.get("context") or {})
    return int(payload.get("tool_output_chars") or ctxv.get("tool_output_chars") or 1000)


def _stash_tool_output(ctx, session, call_id, text, threshold):
    """工具输出分级：超限先落盘 ticket 层，回路径与读取提示；落盘失败兜底全文回填。"""
    cls = ctx.api.call("react.classify_tool",
                       {"content": text, "threshold": threshold}, caller=None)
    if not cls.get("large"):
        return {"content": text, "stashed": False}
    sid = (session or {}).get("id") or "anon"
    path = "tool/%s/%s.txt" % (sid, call_id or "out")
    saved = ctx.api.call("artifacts.save", {
        "layer": "ticket", "ticket": (session or {}).get("ticket"),
        "project": (session or {}).get("project"),
        "path": path, "content": text}, caller=None)
    if not isinstance(saved, dict) or not saved.get("path"):
        return {"content": text, "stashed": False}
    effects = saved.get("effects") or []
    if effects:
        ctx.runtime.apply({"effect": effects})
    note = ("输出过大（%d 字符）已落盘（ticket 层）：%s。需要时用 artifact_read 传 layer=ticket、"
            "该 path 读取，此处不回填正文。" % (cls.get("size"), path))
    return {"content": note, "stashed": True, "path": saved.get("path"),
            "rel_path": path, "size": cls.get("size")}


def _route_run(ctx, payload):
    """ReAct 闭环：轮次循环、终止判断、工具回填都在能力内部，需求树只留一次调用。

    存档 messages 全量保留；发往上游的上下文视图只带 system + 滚动摘要 + 本轮指令，
    历史原始往返不进载荷。本轮新增往返在视图内可见，收口后并入滚动摘要。
    """
    session = payload.get("session") or {}
    archive = list(payload.get("messages") or [])
    summary = session.get("summary") or ""
    view = ctx.api.call("react.context_view",
                        {"messages": archive, "summary": summary}, caller=None)
    proto_row = ctx.api.call("store.read_text", {
        "module": "agent_common/react", "path": "prompts/final-format.md"}, caller=None)
    view = ctx.api.call("react.attach_protocol", {
        "messages": view.get("messages") or [],
        "protocol": proto_row.get("value") or ""}, caller=None)
    messages = list(view.get("messages") or [])
    new_msgs = []
    new_summary = summary
    steps = 0
    done = False
    cap = 200
    if (payload.get("max_steps") or 0) > 0:
        cap = payload.get("max_steps")
    threshold = _tool_threshold(ctx, payload)
    schemas = ctx.api.call("react.schemas", {"tools": payload.get("tools")}, caller=None)
    gate = payload.get("cancel") or {}
    cancelled = False
    failed = None
    while not (steps >= cap or done):
        if gate and ctx.runtime.cancelled(gate.get("id"), gate.get("since")):
            cancelled = True
            break
        if gate:
            ctx.runtime.stream_clear(gate.get("id"))
        resp = ctx.runtime.call("llm-chat", {
                      "base_url": payload.get("base_url"),
                      "api_key": payload.get("api_key"),
                      "model": payload.get("model"),
                      "mode": payload.get("mode"),
                      "cancel": gate,
                      "messages": messages,
                      "tools": [] if (payload.get("mode") == "agent") else schemas})
        answer = resp or {}
        if answer.get("ok") is False:
            # 后端没交答复（报错或被打断）：这一轮没有可交付的内容，不写半截消息
            failed = answer
            cancelled = (answer.get("killed") == "cancelled"
                         or (bool(gate) and ctx.runtime.cancelled(gate.get("id"), gate.get("since"))))
            break
        calls = answer.get("tool_calls")
        parsed = {"reply": answer.get("content"), "summary": ""}
        if not calls:
            # 收口步：剥围栏 → codec 解码 → 拆出答复与摘要；失败则整段作答复，摘要回退旧值。
            stripped = ctx.api.call("react.strip_fence",
                                    {"text": answer.get("content")}, caller=None)
            raw = ctx.api.call("codec.json_decode",
                               {"text": stripped.get("text")}, caller=None)
            parsed = ctx.api.call("react.parse_final", {
                "obj": raw.get("value"), "content": answer.get("content")}, caller=None)
        amsg = ctx.api.call("react.assistant", {
            "content": parsed["reply"],
            "tool_calls": calls}, caller=None)
        messages = messages + [amsg]
        new_msgs.append(amsg)
        steps += 1
        names = ctx.api.call("react.toolnames", {
            "tool_calls": amsg.get("tool_calls")}, caller=None)
        if not amsg.get("tool_calls") or not names:
            if str(parsed.get("summary") or "").strip():
                new_summary = parsed["summary"]
            done = True
            continue
        for call in amsg.get("tool_calls") or []:
            fn = (call or {}).get("function") or {}
            raw = ctx.api.call("codec.json_decode", {"text": fn.get("arguments")}, caller=None)
            targs = ctx.api.call("react.args", {"value": raw.get("value")}, caller=None)
            try:
                out = ctx.api.call("tools.execute", {
                    "name": fn.get("name"), "args": targs, "defer": True,
                    "session": session}, caller=None)
                if isinstance(out, dict) and out.get("deferred"):
                    out = ctx.runtime.call(out.get("demand"), out.get("input") or {})
            except ctx.ApiError as exc:
                # 工具报错要作为观察结果回给模型，让它自己纠错，不能掀翻整轮
                out = {"ok": False, "error": exc.message, "code": exc.code}
            enc = ctx.api.call("codec.json_encode", {"value": out}, caller=None)
            stash = _stash_tool_output(ctx, session, (call or {}).get("id"),
                                       enc.get("text") or "", threshold)
            tmsg = ctx.api.call("react.toolmsg", {
                "id": (call or {}).get("id"), "name": fn.get("name"),
                "content": stash["content"]}, caller=None)
            messages = messages + [tmsg]
            new_msgs.append(tmsg)
    if gate:
        ctx.runtime.stream_clear(gate.get("id"))
    full = archive + new_msgs
    return ctx.api.call("react.result", {"messages": full, "steps": steps,
                                          "cancelled": cancelled,
                                          "failed": failed,
                                          "summary": new_summary}, caller=None)

