#!/usr/bin/env python3
"""本地联调用的假 LLM（OpenAI 兼容，固定端口），供 watchdog 拉起的真 agent 使用。

用法：python3 tests/mock_server.py 9911
"""
import json
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        pass

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        try:
            req = json.loads(raw.decode("utf-8") or "{}")
        except ValueError:
            req = {}
        last = ""
        for m in reversed(req.get("messages") or []):
            if m.get("role") == "user":
                last = m.get("content") or ""
                break
        if "即将关闭" in last:
            content = "DONE"
        elif "请开始：先给出拆解" in last:
            content = "已拆解：架构 + 开发两个角色，开始分发。"
        else:
            content = "联调回复：收到「%s」。链路：网页 -> CLI -> 常驻秘书会话 -> OpenAI 兼容接口。" % last.strip()[:40]
        body = {
            "id": "chatcmpl-local",
            "object": "chat.completion",
            "created": int(time.time()),
            "model": req.get("model") or "mock",
            "choices": [{"index": 0, "message": {"role": "assistant", "content": content}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 80, "completion_tokens": 20, "total_tokens": 100},
        }
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 9911
    httpd = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    httpd.daemon_threads = True
    print("[mock] listening on http://127.0.0.1:%d" % port, flush=True)
    httpd.serve_forever()
