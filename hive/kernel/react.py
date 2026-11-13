"""极简 ReAct 循环 —— 全系统唯一的“思考”内核。

设计要点：
  * 只做 4 件事：取消息 → 调 LLM → 执行工具 → 把结果写回消息；
  * 可插拔：工具来自注册表，工具输出策略来自 OutputPolicy，事件全部发到总线；
  * 四种介入方式：
      串行  —— 一个工具接一个工具执行（默认）
      并发  —— react.parallel_tools=true 时多工具并行
      插队  —— drain() 返回 note，循环把它作为用户插话塞进上下文
      打断  —— drain() 返回 abort，循环在当前边界立刻收尾
  * 流式：llm.delta 事件逐字广播，前端能看到“正在说”，死循环/跑偏一眼可见；
  * 透明：每一次 LLM 请求/响应、工具参数/结果都进 trace，网页可查原文。
"""
from __future__ import annotations

import json
import time
from concurrent.futures import ThreadPoolExecutor

from .llm import LLMError
from .tools import ToolContext


def _msg(role, content, **extra):
    """统一的消息构造：带 ts（网页群聊要按时间线排序）。"""
    m = {"role": role, "content": content, "ts": round(time.time(), 3)}
    m.update(extra)
    return m


class ReactLoop:
    def __init__(self, cfg, bus, log, llm, tools, output, api=None, trace=None):
        self.cfg = cfg
        self.bus = bus
        self.log = log
        self.llm = llm
        self.tools = tools
        self.output = output
        self.api = api
        self.trace = trace

    # ---------------- 对外入口 ----------------
    def run(self, session, user_text=None, drain=None, hooks=None, max_steps=None):
        sid = session.get("id", "unknown")
        messages = session.setdefault("messages", [])
        limit = int(max_steps or session.get("max_steps") or self.cfg["react"]["max_steps"])
        emit = self._emitter(sid, hooks)
        trace_fn = self._tracer(sid, session.get("ticket") or "")

        if user_text:
            messages.append(_msg("user", user_text))
        emit("react.start", {"session": sid, "steps_limit": limit, "messages": len(messages)})
        session["partial"] = {"text": "", "step": 0, "t": round(time.time(), 3), "state": "thinking"}

        steps = 0
        aborted = False
        try:
            while steps < limit:
                steps += 1
                interrupts = drain() if callable(drain) else []
                if interrupts:
                    abort = self._apply_interrupts(sid, messages, interrupts, emit)
                    if abort:
                        aborted = True
                        emit("react.aborted", {"session": sid, "step": steps, "reason": "interrupt"})
                        break

                window = self._trim(messages, int(self.cfg["react"]["max_history_messages"]))
                specs = self._tool_specs(session)
                emit("llm.request", {"session": sid, "step": steps, "messages": len(window), "tools": len(specs)})
                session["partial"] = {"text": "", "step": steps, "t": round(time.time(), 3), "state": "thinking"}
                t0 = time.time()

                def on_delta(piece, _step=steps):
                    session.setdefault("partial", {})
                    session["partial"]["text"] = session["partial"].get("text", "") + piece
                    session["partial"]["state"] = "speaking"
                    session["partial"]["t"] = round(time.time(), 3)
                    self.bus.publish("llm.delta", {"session": sid, "step": _step, "text": piece},
                                     source="react")
                    if callable(hooks):
                        try:
                            hooks("llm.delta", {"session": sid, "step": _step, "text": piece})
                        except Exception:
                            pass

                try:
                    resp = self.llm.chat(window, tools=specs or None, temperature=session.get("temperature"),
                                         on_delta=on_delta, trace=trace_fn)
                except LLMError as e:
                    emit("llm.error", {"session": sid, "step": steps, "error": e.message, "status": e.status})
                    self.log.error("llm.error", session=sid, error=e.message, status=e.status)
                    session["partial"] = {"text": "", "step": steps, "state": "error", "error": e.message}
                    return {"status": "llm_error", "error": e.message, "steps": steps, "final": ""}
                emit("llm.response", {
                    "session": sid, "step": steps, "latency_ms": resp["latency_ms"],
                    "tool_calls": len(resp["tool_calls"]), "chars": len(resp["content"] or ""),
                    "usage": resp.get("usage", {}), "streamed": bool(resp.get("streamed")),
                })
                self._record_usage(sid, resp)

                assistant = _msg("assistant", resp["content"] or "")
                if resp["tool_calls"]:
                    assistant["tool_calls"] = [
                        {
                            "id": tc["id"],
                            "type": "function",
                            "function": {"name": tc["name"], "arguments": json.dumps(tc["arguments"], ensure_ascii=False)},
                        }
                        for tc in resp["tool_calls"]
                    ]
                messages.append(assistant)
                session["updated_at"] = time.time()
                session["partial"] = {"text": "", "step": steps, "state": "idle"}

                if not resp["tool_calls"]:
                    final = resp["content"] or ""
                    emit("react.finish", {"session": sid, "steps": steps, "status": "ok", "chars": len(final)})
                    return {"status": "ok", "final": final, "steps": steps, "usage": resp.get("usage", {})}

                results = self._exec_tools(session, resp["tool_calls"], emit, trace_fn)
                for call, result, rendered in results:
                    messages.append(_msg("tool", rendered["text"], tool_call_id=call["id"], name=call["name"]))
                    emit("tool.result", {
                        "session": sid, "tool": call["name"], "ok": result["ok"],
                        "mode": rendered["mode"], "chars": rendered["chars"], "path": rendered["path"],
                    })
                session["updated_at"] = time.time()

                # 工具跑完后再看一次打断，避免长循环里用户已经喊停还在继续调模型
                interrupts = drain() if callable(drain) else []
                if interrupts:
                    abort = self._apply_interrupts(sid, messages, interrupts, emit)
                    if abort:
                        aborted = True
                        emit("react.aborted", {"session": sid, "step": steps, "reason": "interrupt_after_tools"})
                        break

            status = "aborted" if aborted else "max_steps"
            emit("react.finish", {"session": sid, "steps": steps, "status": status})
            return {"status": status, "final": "", "steps": steps}
        finally:
            session["partial"] = {"text": "", "step": steps, "state": "done", "t": round(time.time(), 3)}

    # ---------------- 内部 ----------------
    def _tracer(self, sid, ticket):
        trace = self.trace

        def fn(kind, data):
            if trace is None:
                return
            try:
                trace.record(kind, data, session=sid, ticket=ticket)
            except Exception:
                pass
        return fn

    def _emitter(self, sid, hooks):
        def emit(name, data):
            payload = {"session": sid}
            payload.update(data or {})
            self.bus.publish(name, payload, source="react")
            if callable(hooks):
                try:
                    hooks(name, payload)
                except Exception:
                    pass
        return emit

    def _record_usage(self, sid, resp):
        usage = resp.get("usage") or {}
        if usage:
            self.bus.publish("llm.usage", {
                "session": sid,
                "prompt_tokens": usage.get("prompt_tokens", 0),
                "completion_tokens": usage.get("completion_tokens", 0),
                "total_tokens": usage.get("total_tokens", 0),
            }, source="react")

    def _tool_specs(self, session):
        allowed = session.get("tools")
        specs = self.tools.specs()
        if allowed is None:
            return specs
        if isinstance(allowed, str):
            allowed = [allowed]
        return [s for s in specs if s["function"]["name"] in allowed]

    def _apply_interrupts(self, sid, messages, interrupts, emit):
        abort = False
        for item in interrupts:
            kind = item.get("kind", "note")
            text = item.get("text") or ""
            if kind == "abort":
                emit("react.interrupt", {"session": sid, "kind": "abort", "text": text})
                abort = True
            else:
                emit("react.interrupt", {"session": sid, "kind": "note", "chars": len(text)})
                messages.append(_msg("user", "[用户插话，优先处理] " + text))
        return abort

    def _trim(self, messages, limit):
        if limit <= 0 or len(messages) <= limit:
            return messages
        start = len(messages) - limit
        while start < len(messages) and messages[start].get("role") == "tool":
            start += 1
        return messages[start:]

    def _exec_tools(self, session, calls, emit, trace_fn=None):
        tctx = ToolContext(self.cfg, self.bus, self.log, session=session, api=self.api, registry=self.tools)
        results = []
        if self.cfg["react"].get("parallel_tools") and len(calls) > 1:
            with ThreadPoolExecutor(max_workers=min(4, len(calls)), thread_name_prefix="tool-par") as pool:
                futures = [pool.submit(self._exec_one, tctx, c, emit, trace_fn) for c in calls]
                results = [f.result() for f in futures]
        else:
            for call in calls:
                results.append(self._exec_one(tctx, call, emit, trace_fn))
        return results

    def _exec_one(self, tctx, call, emit, trace_fn=None):
        name = call["name"]
        emit("tool.start", {"tool": name, "args": _preview_args(call["arguments"]), "call_id": call["id"]})
        if callable(trace_fn):
            trace_fn("tool.call", {"tool": name, "args": call["arguments"], "call_id": call["id"]})
        if call.get("parse_error"):
            text = "工具参数解析失败：%s。请重新发起调用并给出合法 JSON。" % call["parse_error"]
            if callable(trace_fn):
                trace_fn("tool.result", {"tool": name, "ok": False, "text": text})
            return call, {"ok": False, "text": text, "meta": {}}, {"mode": "inline", "chars": len(text), "text": text, "path": None}
        t0 = time.time()
        result = self.tools.execute(name, call["arguments"], tctx)
        rendered = self.output.apply(tctx.session_id, name, result["text"], call["id"])
        if rendered["mode"] == "file":
            self.log.info("tool.output.offloaded", session=tctx.session_id, tool=name, chars=rendered["chars"], path=rendered["path"])
        if callable(trace_fn):
            trace_fn("tool.result", {"tool": name, "ok": result["ok"], "ms": int((time.time() - t0) * 1000),
                                     "mode": rendered["mode"], "chars": rendered["chars"],
                                     "path": rendered["path"], "text": result["text"]})
        return call, result, rendered


def _preview_args(args, n=200):
    try:
        s = json.dumps(args, ensure_ascii=False)
    except Exception:
        s = str(args)
    return s if len(s) <= n else s[:n] + "..."
