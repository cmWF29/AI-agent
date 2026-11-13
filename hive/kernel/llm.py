"""LLM 客户端（OpenAI 兼容协议，默认接 DeepSeek）。

只做三件事：发请求、重试、把响应归一化成 {content, tool_calls}。
不关心 agent 语义，也不碰会话存储。
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request


class LLMError(Exception):
    def __init__(self, message, status=None, body=None, retriable=False):
        super().__init__(message)
        self.message = message
        self.status = status
        self.body = body
        self.retriable = retriable


def _short(text, n=800):
    text = text or ""
    return text if len(text) <= n else text[:n] + "..."


class LLMClient:
    def __init__(self, cfg):
        c = cfg["llm"]
        self.base_url = (c["base_url"] or "").rstrip("/")
        if self.base_url.endswith("/chat/completions"):
            self.endpoint = self.base_url
        else:
            self.endpoint = self.base_url + "/chat/completions"
        self.api_key = c.get("api_key") or ""
        self.model = c.get("model") or "deepseek-chat"
        self.temperature = c.get("temperature", 0.2)
        self.timeout = c.get("timeout", 180)
        self.max_retries = c.get("max_retries", 3)
        self.max_tokens = c.get("max_tokens", 0)
        self.usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0, "calls": 0, "errors": 0}

    # ---------------- 基础请求 ----------------
    def _post(self, payload, timeout=None):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(self.endpoint, data=body, method="POST")
        req.add_header("Content-Type", "application/json")
        req.add_header("Accept", "application/json")
        if self.api_key:
            req.add_header("Authorization", "Bearer " + self.api_key)
        try:
            with urllib.request.urlopen(req, timeout=timeout or self.timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            raw = b""
            try:
                raw = e.read()
            except Exception:
                pass
            text = raw.decode("utf-8", "ignore")
            raise LLMError(
                "HTTP %s: %s" % (e.code, _short(text)),
                status=e.code,
                body=text,
                retriable=e.code in (408, 409, 429, 500, 502, 503, 504),
            )
        except urllib.error.URLError as e:
            raise LLMError("network error: %s" % e.reason, retriable=True)
        except json.JSONDecodeError as e:
            raise LLMError("bad json from llm: %s" % e, retriable=False)

    # ---------------- 对话 ----------------
    def chat(self, messages, tools=None, temperature=None, max_tokens=None):
        if not self.api_key:
            raise LLMError("llm.api_key 未配置（config/config.json 的 llm.api_key 或环境变量 HIVE_LLM_API_KEY）")
        payload = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "temperature": self.temperature if temperature is None else temperature,
        }
        mt = max_tokens if max_tokens is not None else self.max_tokens
        if mt:
            payload["max_tokens"] = int(mt)
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"

        attempt = 0
        last = None
        while attempt <= self.max_retries:
            t0 = time.time()
            try:
                data = self._post(payload)
                self.usage["calls"] += 1
                return self._normalize(data, time.time() - t0)
            except LLMError as e:
                self.usage["errors"] += 1
                last = e
                if not e.retriable or attempt >= self.max_retries:
                    raise
                time.sleep(min(2 ** attempt, 8))
                attempt += 1
        raise last or LLMError("llm call failed")

    def _normalize(self, data, latency):
        choices = data.get("choices") or []
        if not choices:
            raise LLMError("llm response has no choices: %s" % _short(json.dumps(data, ensure_ascii=False)))
        msg = choices[0].get("message") or {}
        content = msg.get("content") or ""
        raw_calls = msg.get("tool_calls") or []
        tool_calls = []
        for i, tc in enumerate(raw_calls):
            fn = tc.get("function") or {}
            args_raw = fn.get("arguments")
            args, parse_error = {}, None
            if isinstance(args_raw, dict):
                args = args_raw
            elif isinstance(args_raw, str) and args_raw.strip():
                try:
                    args = json.loads(args_raw)
                except ValueError:
                    parse_error = "arguments 不是合法 JSON: %s" % _short(args_raw, 300)
                    args = {"_raw": args_raw}
            tool_calls.append({
                "id": tc.get("id") or "call_%d_%d" % (int(latency * 1000), i),
                "name": fn.get("name") or "unknown",
                "arguments": args,
                "parse_error": parse_error,
            })
        usage = data.get("usage") or {}
        self.usage["prompt_tokens"] += usage.get("prompt_tokens", 0) or 0
        self.usage["completion_tokens"] += usage.get("completion_tokens", 0) or 0
        self.usage["total_tokens"] += usage.get("total_tokens", 0) or 0
        return {
            "content": content,
            "tool_calls": tool_calls,
            "finish_reason": choices[0].get("finish_reason"),
            "usage": usage,
            "latency_ms": int(latency * 1000),
            "model": data.get("model") or self.model,
            "raw_id": data.get("id"),
        }

    def complete_text(self, system, user, max_tokens=None):
        """纯文本补全，用于摘要/压缩这类不挂工具的场景。"""
        res = self.chat(
            [{"role": "system", "content": system}, {"role": "user", "content": user}],
            tools=None,
            max_tokens=max_tokens,
        )
        return res["content"] or ""

    def ping(self):
        t0 = time.time()
        try:
            res = self.chat([{"role": "user", "content": "ping，只回 pong"}], tools=None, max_tokens=8, temperature=0)
            return {"ok": True, "model": res["model"], "latency_ms": int((time.time() - t0) * 1000), "text": _short(res["content"], 60)}
        except LLMError as e:
            return {"ok": False, "error": e.message, "status": e.status, "latency_ms": int((time.time() - t0) * 1000)}
