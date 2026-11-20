"""ReAct 模块：只提供消息/工具形状的纯计算。循环在 react-run 需求里。"""
from __future__ import annotations

import asyncio

from .private import _pure


def _msg_tpl(ctx):
    """消息模板表：react 模块自己的 data，读不到就退化成空。"""
    row = ctx.api.call("store.read", {
        "module": "agent_common/react", "path": "messages.yaml"}, caller=None)
    return row.get("value") or {}


def setup(ctx):
    for name, fn in [
        ("react.schemas", _pure.schemas),
        ("react.assistant", _pure.assistant),
        ("react.toolnames", _pure.toolnames),
        ("react.args", _pure.args),
        ("react.toolmsg", _pure.toolmsg),
        ("react.result", _pure.result),
        ("react.context_view", _pure.context_view),
        ("react.checkpoint", _pure.checkpoint),
        ("react.classify_tool", _pure.classify_tool),
        ("react.parse_final", _pure.parse_final),
        ("react.strip_fence", _pure.strip_fence),
        ("react.extract_json", _pure.extract_json),
        ("react.attach_protocol", _pure.attach_protocol),
    ]:
        ctx.api.register(name, lambda payload, fn=fn: fn(payload), module="react")
    ctx.api.register("react.run", _route_run, "ReAct 循环：模型→工具→再模型，闭环在能力内", module="react")
    return True


def _tool_threshold(ctx, payload):
    if payload.get("tool_output_chars"):
        return int(payload.get("tool_output_chars"))
    row = ctx.api.call("config.get",
        {"key": "sessions.context.tool_output_chars"}, caller=None)
    return int(row.get("value"))


def _logs_paths(ctx):
    row = ctx.api.call("config.get", {"key": "logs.paths"}, caller=None)
    return row.get("value") or {}


async def _exec_tool(ctx, fn, targs, session):
    """单条工具执行：注册表命中直跑；占位需求回退；工具报错归一成观察结果，不掀翻整轮。

    协程内 await 工具路由；子进程/外部调用走异步子进程与流，等待期挂起事件循环
    而不占线程。只负责取回结果，写盘与消息组装由主循环串行收口。
    """
    try:
        out = await ctx.api.acall("tools.execute", {
            "name": fn.get("name"), "args": targs, "defer": True,
            "session": session}, caller=None)
        if isinstance(out, dict) and out.get("deferred"):
            out = await ctx.runtime.acall(out.get("demand"), out.get("input") or {})
        return out
    except ctx.ApiError as exc:
        # 工具报错要作为观察结果回给模型，让它自己纠错，不能掀翻整轮
        return {"ok": False, "error": exc.message, "code": exc.code}


def _stash_tool_output(ctx, session, call_id, text, threshold, stamp=""):
    """工具输出分级：超限先落 ticket 层日志，回路径与读取提示；落盘失败兜底全文回填。"""
    cls = ctx.api.call("react.classify_tool",
                       {"content": text, "threshold": threshold}, caller=None)
    if not cls.get("large"):
        return {"content": text, "stashed": False}
    session = session or {}
    fid = call_id or ("out-%s" % (stamp or "x"))
    project = session.get("project") or ""
    ticket = session.get("ticket") or ""
    pt = _logs_paths(ctx).get("tool") or ""
    rel_path = pt.format(project=project, ticket=ticket, fid=fid) if pt \
        else "%s/%s" % (ticket, fid)
    body_effect = {"kind": "write_text", "module": "agent/logs",
                   "path": rel_path, "text": text}
    rec = ctx.api.call("logs.record", {
        "path": rel_path, "kind": "tool", "layer": "ticket",
        "project": project, "ticket": ticket, "name": fid}, caller=None)
    effects = [body_effect] + (rec.get("effects") or [])
    applied_ok = True
    if effects:
        res = ctx.runtime.apply({"effect": effects}) or {}
        applied = res.get("applied") or []
        # 单条写盘失败会被 apply 记成 {ok:false}；任一失败就不能给模型假路径，回退全文回填。
        applied_ok = not any(isinstance(a, dict) and a.get("ok") is False for a in applied)
    if not applied_ok:
        return {"content": text, "stashed": False, "fallback": "write_failed"}
    tpl = _msg_tpl(ctx).get("stash_note") or ""
    note = tpl.format(size=cls.get("size"), path=rel_path) if tpl else ""
    return {"content": note, "stashed": True, "path": rel_path,
            "rel_path": rel_path, "size": cls.get("size")}


def _checkpoint(ctx, session, path, messages, summary, steps):
    """轮内中间落盘：把当前累积消息/摘要/步数写回会话记录。失败不掀翻 ReAct 循环。

    路径由编排层（session-run）算好传入；react 不拼会话布局。写盘交 runtime 落地，
    能力自己不伸手。检查点只缩小崩溃窗口，跨轮接续仍以 summary 为准。
    """
    if not path or not (session or {}).get("id"):
        return
    try:
        now = ctx.api.call("clock.now", {}, caller=None)
        ckpt = ctx.api.call("react.checkpoint", {
            "rec": session, "messages": messages, "summary": summary,
            "steps": steps, "now": now.get("ts")}, caller=None)
        ctx.runtime.apply({"effect": {"kind": "write", "module": "agent/logs",
                                      "path": path, "value": ckpt}})
    except Exception:  # noqa: BLE001 —— 检查点失败不中断本轮，收尾仍会整段写盘
        pass


async def _route_run(ctx, payload):
    """ReAct 闭环：轮次循环、终止判断、工具回填都在能力内部，需求树只留一次调用。

    存档 messages 全量保留；发往上游的上下文视图只带 system + 滚动摘要 + 本轮指令，
    历史原始往返不进载荷。本轮新增往返在视图内可见，收口后并入滚动摘要。
    """
    session = payload.get("session") or {}
    archive = list(payload.get("messages") or [])
    path = payload.get("path") or ""
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
    new_stage = ""
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
        answer = await ctx.runtime.acall("llm-chat", {
            "base_url": payload.get("base_url"),
            "api_key": payload.get("api_key"),
            "model": payload.get("model"),
            "cancel": gate,
            "messages": messages,
            "tools": schemas})
        if not isinstance(answer, dict):
            answer = {}
        if answer.get("ok") is False:
            # 后端没交答复（报错或被打断）：这一轮没有可交付的内容，不写半截消息
            failed = answer
            cancelled = (answer.get("killed") == "cancelled"
                         or (bool(gate) and ctx.runtime.cancelled(gate.get("id"), gate.get("since"))))
            break
        calls = answer.get("tool_calls")
        parsed = {"reply": answer.get("content"), "summary": "", "stage": ""}
        if not calls:
            # 收口步：剥围栏 → 截取 JSON 区间 → codec 解码 → 拆出答复与摘要；失败则整段作答复，摘要回退旧值。
            stripped = ctx.api.call("react.strip_fence",
                                    {"text": answer.get("content")}, caller=None)
            extracted = ctx.api.call("react.extract_json",
                                     {"text": stripped.get("text")}, caller=None)
            raw = ctx.api.call("codec.json_decode",
                               {"text": extracted.get("text")}, caller=None)
            parsed = ctx.api.call("react.parse_final", {
                "obj": raw.get("value"), "content": answer.get("content")}, caller=None)
        amsg = ctx.api.call("react.assistant", {
            "content": parsed["reply"],
            "tool_calls": calls,
            "at": ctx.api.call("clock.now", {}, caller=None).get("ts")}, caller=None)
        messages = messages + [amsg]
        new_msgs.append(amsg)
        steps += 1
        names = ctx.api.call("react.toolnames", {
            "tool_calls": amsg.get("tool_calls")}, caller=None)
        if not amsg.get("tool_calls") or not names:
            if str(parsed.get("summary") or "").strip():
                new_summary = parsed["summary"]
            if str(parsed.get("stage") or "").strip():
                new_stage = parsed["stage"]
            _checkpoint(ctx, session, path, archive + new_msgs, new_summary, steps)
            done = True
            continue
        # 工具步：先把这条带 tool_calls 的 assistant 落检查点，崩溃后存档不丢这一步
        _checkpoint(ctx, session, path, archive + new_msgs, new_summary, steps)
        # 同一轮的多条工具协程并发跑（gather），再按模型原顺序收口回填；
        # 工具在异步轨并发阻塞，写盘/消息组装仍在主循环串行，避免并发落盘竞争。
        jobs = []
        tool_idx = 0
        for call in amsg.get("tool_calls") or []:
            tool_idx += 1
            fn = (call or {}).get("function") or {}
            raw = ctx.api.call("codec.json_decode", {"text": fn.get("arguments")}, caller=None)
            targs = ctx.api.call("react.args", {"value": raw.get("value")}, caller=None)
            jobs.append((call, fn, tool_idx, targs))
        outs = await asyncio.gather(*[_exec_tool(ctx, fn, targs, session)
                                      for _, fn, _, targs in jobs])
        for (call, fn, tool_idx, _), out in zip(jobs, outs):
            enc = ctx.api.call("codec.json_encode", {"value": out}, caller=None)
            stamp = "%d-%d" % (steps, tool_idx)
            stash = _stash_tool_output(ctx, session, (call or {}).get("id"),
                                       enc.get("text") or "", threshold, stamp)
            tmsg = ctx.api.call("react.toolmsg", {
                "id": (call or {}).get("id"), "name": fn.get("name"),
                "content": stash["content"],
                "at": ctx.api.call("clock.now", {}, caller=None).get("ts")}, caller=None)
            messages = messages + [tmsg]
            new_msgs.append(tmsg)
            _checkpoint(ctx, session, path, archive + new_msgs, new_summary, steps)
    if gate:
        ctx.runtime.stream_clear(gate.get("id"))
    full = archive + new_msgs
    return ctx.api.call("react.result", {"messages": full, "steps": steps,
                                          "cancelled": cancelled,
                                          "failed": failed,
                                          "summary": new_summary,
                                          "stage": new_stage}, caller=None)
