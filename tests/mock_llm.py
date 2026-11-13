#!/usr/bin/env python3
"""测试用假 LLM：OpenAI 兼容 /chat/completions，按脚本返回。

用法：
    mock = MockLLM().start()
    mock.set([{...}, {...}])
    cfg["llm"]["base_url"] = mock.base_url
"""
from __future__ import annotations

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class MockLLM:
    def __init__(self):
        self.scripts = []
        self.requests = []
        self.lock = threading.Lock()
        self.httpd = None
        self.thread = None
        self.call_count = 0

    # ---------------- 控制 ----------------
    def set(self, scripts):
        with self.lock:
            self.scripts = list(scripts)
            self.call_count = 0

    def push(self, script):
        with self.lock:
            self.scripts.append(script)

    def default(self):
        return {"content": "（mock）ok", "tool_calls": []}

    def start(self):
        mock = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, fmt, *args):
                pass

            def do_POST(self):
                length = int(self.headers.get("Content-Length") or 0)
                raw = self.rfile.read(length) if length else b"{}"
                try:
                    req = json.loads(raw.decode("utf-8"))
                except ValueError:
                    req = {}
                with mock.lock:
                    mock.requests.append({"path": self.path, "body": req, "t": time.time()})
                    idx = mock.call_count
                    mock.call_count += 1
                    script = mock.scripts[idx] if idx < len(mock.scripts) else mock.default()
                content = script.get("content") or ""
                calls = script.get("tool_calls") or []
                msg = {"role": "assistant", "content": content}
                if calls:
                    msg["tool_calls"] = [
                        {
                            "id": c.get("id") or "call_%d_%d" % (idx, i),
                            "type": "function",
                            "function": {"name": c["name"],
                                         "arguments": json.dumps(c.get("arguments") or {}, ensure_ascii=False)},
                        }
                        for i, c in enumerate(calls)
                    ]
                body = {
                    "id": "chatcmpl-mock-%d" % idx,
                    "object": "chat.completion",
                    "created": int(time.time()),
                    "model": req.get("model") or "mock",
                    "choices": [{
                        "index": 0,
                        "message": msg,
                        "finish_reason": "tool_calls" if calls else "stop",
                    }],
                    "usage": {"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120},
                }
                if req.get("stream"):
                    return self._stream(body, msg, calls)
                data = json.dumps(body, ensure_ascii=False).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def _stream(self, body, msg, calls):
                """按 OpenAI SSE 分片回放：正文按词切开，工具调用按参数切片。"""
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Cache-Control", "no-cache")
                self.send_header("Connection", "close")
                self.end_headers()

                def emit(obj):
                    line = "data: " + json.dumps(obj, ensure_ascii=False) + "\n\n"
                    self.wfile.write(line.encode("utf-8"))
                    self.wfile.flush()

                base = {"id": body["id"], "object": "chat.completion.chunk", "created": body["created"],
                        "model": body["model"]}
                content = msg.get("content") or ""
                for i in range(0, len(content), 8):
                    emit(dict(base, choices=[{"index": 0, "delta": {"content": content[i:i + 8]},
                                              "finish_reason": None}]))
                for ti, tc in enumerate(msg.get("tool_calls") or []):
                    fn = tc.get("function") or {}
                    emit(dict(base, choices=[{"index": 0, "delta": {"tool_calls": [
                        {"index": ti, "id": tc["id"], "type": "function",
                         "function": {"name": fn.get("name"), "arguments": ""}}]},
                        "finish_reason": None}]))
                    args = fn.get("arguments") or ""
                    for k in range(0, len(args), 16):
                        emit(dict(base, choices=[{"index": 0, "delta": {"tool_calls": [
                            {"index": ti, "function": {"arguments": args[k:k + 16]}}]},
                            "finish_reason": None}]))
                emit(dict(base, choices=[{"index": 0, "delta": {},
                                          "finish_reason": "tool_calls" if calls else "stop"}],
                          usage=body["usage"]))
                self.wfile.write(b"data: [DONE]\n\n")
                self.wfile.flush()

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.httpd.daemon_threads = True
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()
        port = self.httpd.server_address[1]
        return self

    @property
    def base_url(self):
        return "http://127.0.0.1:%d" % self.httpd.server_address[1]

    def stop(self):
        if self.httpd:
            self.httpd.shutdown()
            self.httpd.server_close()
            self.httpd = None
