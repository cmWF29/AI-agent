"""本地打桩 LLM 服务：把被测系统的模型 endpoint 指到本地桩，脚本化/随机回响应并注入故障。

不接真实上游，供压测与故障场景测试复用：
- scripted：按步序回预设 tool_call 或收口文本（可带 stage/summary 结构化字段）；
- random ：无 script 时按 tool_rate 概率回一条 tool_call，否则一轮收口；
- 故障注入：断连（直接关连接）、HTTP 故障码（429/5xx/400）、上下文/token 超限。

桩只回模型答复；工具调用由被测系统 tools.execute 真实执行并回填，桩不替代工具。
"""
from __future__ import annotations

import json
import random
import re
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class StubStats:
    """桩计数器：加锁汇总调用分类与故障码。"""

    def __init__(self):
        self.lock = threading.Lock()
        self.calls = 0
        self.text = 0
        self.tool_calls = 0
        self.errors = 0
        self.closed = 0
        self.by_code = {}

    def bump(self, code):
        with self.lock:
            self.by_code[code] = self.by_code.get(code, 0) + 1


class StubPolicy:
    """打桩场景参数。缺省全关：纯文本一轮收口、无延迟、无故障。

    script          步序表：每项 {"tool_call": {"name", "arguments"}} 或
                    {"reply": 文本, "stage": 状态, "summary": 摘要}；按调用步序取，取完回收口。
    tool_rate       随机回 tool_call 的概率（无 script 时生效）。
    delay_base      每轮基础延迟秒；delay_jitter 为附加随机抖动上限秒。
    close_rate      断连概率：命中则直接关连接，不发响应。
    fail_code       故障 HTTP 状态码；fail_rate 为命中概率。
    token_limit     消息条数阈值：入参 messages 条数超过阈值返上下文超限错误。
    """

    def __init__(self, script=None, tool_rate=0.0, spawn_rate=0.0, delay_base=0.0,
                 delay_jitter=0.0, close_rate=0.0, fail_code=0, fail_rate=0.0, token_limit=0,
                 pm_roles=None, role_rounds=1, filler_words=120):
        self.script = list(script or [])
        self.tool_rate = float(tool_rate)
        self.spawn_rate = float(spawn_rate)
        self.delay_base = float(delay_base)
        self.delay_jitter = float(delay_jitter)
        self.close_rate = float(close_rate)
        self.fail_code = int(fail_code or 0)
        self.fail_rate = float(fail_rate)
        self.token_limit = int(token_limit or 0)
        # PM 依次分派的角色序列；角色在收口前重复“读→写→备注”的遍数；正文每段字数。
        self.pm_roles = list(pm_roles or ["developer", "tester", "reviewer"])
        self.role_rounds = int(role_rounds or 1)
        self.filler_words = int(filler_words or 120)


def _tool_frame(call_id, name, arguments):
    return {"choices": [{
        "delta": {"tool_calls": [{
            "index": 0, "id": call_id, "type": "function",
            "function": {"name": name, "arguments": arguments or "{}"}}]},
        "finish_reason": "tool_calls"}]}


def _text_frames(text):
    text = text or ""
    half = max(1, len(text) // 2)
    return [
        {"choices": [{"delta": {"content": text[:half]}}]},
        {"choices": [{"delta": {"content": text[half:]}, "finish_reason": "stop"}]},
    ]


def _structured_frames(obj):
    """收口步结构化输出：reply 进气泡，stage/summary 随 JSON 一并交被测侧解析。"""
    return _text_frames(json.dumps(obj, ensure_ascii=False))


# 角色一轮内的工具步进：读依据 → 写产出 → 落备注；运行时再按当前上下文可用工具过滤。
_ROLE_STEPS = [
    "knowledge_search", "knowledge_read", "ticket_read_doc", "artifact_read",
    "artifact_write", "knowledge_write", "ticket_note",
]
# 压测桩内置岗位状态链（与 roles.yaml 契约对齐；正式流程以后端契约为准）。
_ROLE_NEXT = {
    "developer": ["understand", "implement", "verify"],
    "tester": ["design", "run", "report"],
    "reviewer": ["study", "review", "deliver"],
}
_ROLE_READ = {"knowledge_search", "knowledge_read", "ticket_read_doc", "artifact_read"}
_ROLE_WRITE = {"artifact_write", "knowledge_write"}

_FILLER = {
    "knowledge_search": "检索既有知识条目与历史方案，比对本工单约束，定位可复用依据与待补缺口；"
                        "逐条记录来源条目、适用条件和未覆盖项，作为后续实现与评审的参考基础。",
    "knowledge_read": "通读命中的知识条目原文，提炼与本工单相关的规则、接口约定和边界限制；"
                      "标注与需求直接对应的要点，存疑处单独列出，避免把不相关条目当成依据。",
    "ticket_read_doc": "重读工单需求、验收标准与附件说明，明确改动范围、必须产出的交付物和禁止项；"
                       "对照当前进度核对已有依据是否齐备，缺项在备注里明确列出。",
    "artifact_read": "查看已有交付件与代码现状，摸清结构、命名与既有实现方式；"
                     "识别可复用部分与需要新增或调整的位置，记录阅读结论供本轮产出使用。",
    "artifact_write": "按验收标准落盘本轮交付件：补充必要的实现、文档或用例，命名与归属目录符合岗位约定；"
                      "内容覆盖需求要点，关键片段写明用途与约束，便于后续评审与测试核对。",
    "knowledge_write": "把本轮形成的规则、约定或复用结论沉淀为知识条目，标注适用范围与来源工单；"
                       "避免写入临时性过程记录，保证后续同类任务可检索复用。",
    "ticket_note": "在工单备注里记录本轮结论：已完成项、依据来源、遗留缺口与下一步建议；"
                  "结论与交付件一致，不夸大为已通过验收，缺口如实标注。",
}


def _filler(tool, words):
    base = _FILLER.get(tool, "按岗位职责完成本轮处理，记录结论与依据。")
    extra = ("复核前后结论是否一致，检查交付件路径、命名与归属是否正确；"
             "补充必要的上下文说明，确保下游角色能据此继续，不留模糊假设。")
    out = base
    while len(out) < words:
        out += extra
    return out[:words]


def _sse_payload(frames):
    chunks = ["data: " + json.dumps(f, ensure_ascii=False) + "\n\n" for f in frames]
    chunks.append("data: [DONE]\n\n")
    return "".join(chunks).encode("utf-8")


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args):  # 压测不刷访问日志
        pass

    def _read_body(self):
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b""
        try:
            return json.loads(raw.decode("utf-8") or "{}")
        except Exception:  # noqa: BLE001 —— 坏体按空请求处理
            return {}

    def do_POST(self):
        policy = self.server.policy
        stats = self.server.stats
        req = self._read_body()
        with stats.lock:
            stats.calls += 1

        delay = policy.delay_base + random.uniform(0, policy.delay_jitter)
        if delay > 0:
            time.sleep(delay)

        # 断连：直接关连接，被测侧感知 unreachable / net_error。
        if random.random() < policy.close_rate:
            with stats.lock:
                stats.closed += 1
            try:
                self.connection.close()
            except Exception:  # noqa: BLE001
                pass
            return

        # 上下文/token 超限：消息条数超阈值返错误体。
        messages = req.get("messages") or []
        if policy.token_limit and len(messages) > policy.token_limit:
            stats.bump("context_length_exceeded")
            body = json.dumps({"error": {"message": "context length exceeded",
                                         "code": "context_length_exceeded"}},
                              ensure_ascii=False).encode("utf-8")
            try:
                self.send_response(400)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            except Exception:  # noqa: BLE001
                with stats.lock:
                    stats.errors += 1
            return

        # HTTP 故障码：429 限流 / 5xx 服务端错误。
        if policy.fail_code and random.random() < policy.fail_rate:
            stats.bump(str(policy.fail_code))
            body = json.dumps({"error": {"message": "stub http error",
                                         "code": "http_%s" % policy.fail_code}},
                              ensure_ascii=False).encode("utf-8")
            try:
                self.send_response(policy.fail_code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            except Exception:  # noqa: BLE001
                with stats.lock:
                    stats.errors += 1
            return

        frames = self._frames(req, stats)
        payload = _sse_payload(frames)
        try:
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            self.wfile.write(payload)
        except Exception:  # noqa: BLE001
            with stats.lock:
                stats.errors += 1

    def _frames(self, req, stats):
        policy = self.server.policy
        step_idx = self.server.step_idx
        self.server.step_idx = step_idx + 1
        script = policy.script

        if script:
            step = script[min(step_idx, len(script) - 1)]
            call = step.get("tool_call")
            if call:
                with stats.lock:
                    stats.tool_calls += 1
                return [_tool_frame("call_%d" % stats.calls,
                                     call.get("name") or "noop",
                                     call.get("arguments") or "{}")]
            with stats.lock:
                stats.text += 1
            if "stage" in step or "summary" in step:
                obj = {"reply": step.get("reply") or ""}
                if step.get("stage"):
                    obj["stage"] = step["stage"]
                if step.get("summary"):
                    obj["summary"] = step["summary"]
                return _structured_frames(obj)
            return _text_frames(step.get("reply") or "")

        tools = req.get("tools") or []
        by_name = {}
        for spec in tools or []:
            fn = spec.get("function") or {}
            nm = fn.get("name") or spec.get("name")
            if nm:
                by_name[nm] = spec
        msgs = req.get("messages") or []
        done = sum(1 for m in msgs if m.get("role") == "assistant")

        def _args(tool):
            filler = _filler(tool, policy.filler_words)
            if tool == "artifact_write":
                return {"layer": "ticket", "path": "docs/feature.md", "content": filler}
            if tool == "artifact_read":
                return {"layer": "ticket", "path": "docs/feature.md"}
            if tool == "knowledge_write":
                return {"layer": "ticket", "name": "round-note", "content": filler}
            if tool == "knowledge_read":
                return {"layer": "ticket", "name": "round-note"}
            if tool == "knowledge_search":
                return {"query": "工单要点 验收标准 既有方案"}
            if tool == "ticket_note":
                return {"text": filler}
            return {}

        # 从 system 提示识别岗位与当前状态（压测桩脚本化模拟；正式流程以后端契约为准）。
        sys_text = " ".join(m.get("content") or "" for m in msgs if m.get("role") == "system")
        role = ""
        for kw, rid in (("开发角色", "developer"), ("测试角色", "tester"), ("评审角色", "reviewer")):
            if kw in sys_text:
                role = rid
                break
        cur = ""
        mcur = re.search(r"当前阶段：[^（(]*（([a-z_]+)", sys_text)
        if mcur:
            cur = mcur.group(1)

        if role:
            chain = _ROLE_NEXT.get(role) or []
            steps = [t for t in _ROLE_STEPS if t in by_name]
            if policy.role_rounds > 1:
                steps = steps * policy.role_rounds
            already_tool = any(m.get("role") == "tool" for m in msgs)
            if steps and not already_tool:
                with stats.lock:
                    stats.tool_calls += 1
                return [_tool_frame("call_%d" % stats.calls, steps[0],
                                    json.dumps(_args(steps[0]), ensure_ascii=False))]
            nxt = ""
            if cur in chain:
                idx = chain.index(cur)
                if idx + 1 < len(chain):
                    nxt = chain[idx + 1]
            with stats.lock:
                stats.text += 1
            obj = {"reply": _filler("ticket_note", policy.filler_words),
                   "summary": "本轮交付完成，结论、依据与遗留缺口已记入工单备注。"}
            if nxt:
                obj["stage"] = nxt
            return _structured_frames(obj)

        # PM 上下文：analyze 先读需求并自报进 plan，plan 态依次分派角色，全部分派后收口。
        if "role_spawn" in by_name or "role_task" in by_name or "ticket_split" in by_name:
            assigned = set()
            in_block = False
            for line in sys_text.splitlines():
                ls = line.strip()
                if ls.startswith("## 已分派角色"):
                    in_block = True
                    continue
                if in_block and ls.startswith("## "):
                    in_block = False
                if in_block and ls.startswith("- "):
                    assigned.add(ls[2:].strip())
            pending = [r for r in policy.pm_roles if r not in assigned]
            already_tool = any(m.get("role") == "tool" for m in msgs)
            if pending and not already_tool:
                role = pending[0]
                args = json.dumps({"role": role, "display": role,
                                   "task": "按工单验收标准完成交付，产出落到工单交付目录，结论记入备注。"},
                                  ensure_ascii=False)
                with stats.lock:
                    stats.tool_calls += 1
                return [_tool_frame("call_%d" % stats.calls, "role_spawn", args)]
            with stats.lock:
                stats.text += 1
            return _structured_frames({
                "reply": "（stub）PM 已分派各角色并确认分工，工单进入执行、测试与评审阶段。",
                "summary": "协同推进，依据工单验收标准交付，依据与缺口记入备注。"})

        # analyze 态：先读工单需求，下一轮自报进入编排阶段。
        read = next((n for n in ("ticket_read_doc", "artifact_read", "knowledge_read") if n in by_name), None)
        if read and done < 1:
            with stats.lock:
                stats.tool_calls += 1
            return [_tool_frame("call_%d" % stats.calls, read, json.dumps(_args(read), ensure_ascii=False))]
        with stats.lock:
            stats.text += 1
        return _structured_frames({
            "reply": "（stub）需求要点与验收标准已梳理，进入编排与角色分派。",
            "stage": "plan",
            "summary": "明确改动范围与交付要求，准备分派开发、测试、评审角色。"})


def start_stub(policy=None):
    """起桩服务（守护线程），返回 (server, thread, base_url)。"""
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    server.policy = policy or StubPolicy()
    server.stats = StubStats()
    server.step_idx = 0
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    return server, thread, "http://127.0.0.1:%d/v1" % port
