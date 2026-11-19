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
                 delay_jitter=0.0, close_rate=0.0, fail_code=0, fail_rate=0.0, token_limit=0):
        self.script = list(script or [])
        self.tool_rate = float(tool_rate)
        self.spawn_rate = float(spawn_rate)
        self.delay_base = float(delay_base)
        self.delay_jitter = float(delay_jitter)
        self.close_rate = float(close_rate)
        self.fail_code = int(fail_code or 0)
        self.fail_rate = float(fail_rate)
        self.token_limit = int(token_limit or 0)


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
            return _text_frames(step.get("reply") or "")

        tools = req.get("tools") or []
        by_name = {}
        for spec in tools or []:
            fn = spec.get("function") or {}
            nm = fn.get("name") or spec.get("name")
            if nm:
                by_name[nm] = spec
        # 首轮消息仅 system+user；之后轮次含工具步/历史往返。按轮次分流避免无限拉新。
        first = len(req.get("messages") or []) <= 2
        # PM 上下文：首轮按概率拉一个开发角色会话，后续轮次收口。
        if "role_spawn" in by_name:
            if first and random.random() < policy.spawn_rate:
                args = json.dumps({"role": "developer", "display": "Dev",
                                   "task": "按需求产出交付件到交付目录"},
                                  ensure_ascii=False)
                with stats.lock:
                    stats.tool_calls += 1
                return [_tool_frame("call_%d" % stats.calls, "role_spawn", args)]
            with stats.lock:
                stats.text += 1
            return _text_frames("（stub）PM 已分派并确认，工单进入执行阶段。")
        # 角色上下文：首轮按概率调写文件工具产出交付件，后续轮次收口。
        write_name = next((n for n in ("artifact_write", "ticket_note") if n in by_name), None)
        pick = write_name or next((n for n in by_name if n != "role_spawn"), None)
        if pick and first and random.random() < policy.tool_rate:
            if pick == "artifact_write":
                args = json.dumps({"layer": "ticket", "path": "docs/feature.md",
                                   "content": "压测交付件：功能实现说明与关键代码片段，"
                                              "不少于八十字以满足交付件最小体量校验。"},
                                  ensure_ascii=False)
            else:
                args = json.dumps({"text": "压测备注"}, ensure_ascii=False)
            with stats.lock:
                stats.tool_calls += 1
            return [_tool_frame("call_%d" % stats.calls, pick, args)]

        with stats.lock:
            stats.text += 1
        return _text_frames("（stub）本轮处理完成，交付结论如下：打桩输出。")


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
