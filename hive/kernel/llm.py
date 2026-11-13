"""LLM 客户端（OpenAI 兼容协议，默认接 DeepSeek）。

只做三件事：发请求（支持流式）、重试、把响应归一化成 {content, tool_calls}。
不关心 agent 语义，也不碰会话存储。

流式（需求 16）：on_delta 非空时用 SSE 读，逐段回调文本增量；
工具调用也会在流里分片返回，这里按 index 累加后统一解析。
trace 回调（需求 19）把“真正发出去的请求”原样交出去，网页可以看请求结构。
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
        self.stream = bool(c.get("stream", True))
        self.usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0, "calls": 0,
                      "errors": 0, "streams": 0}

    # ---------------- 基础请求 ----------------
    def _request(self, payload, stream):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(self.endpoint, data=body, method="POST")
        req.add_header("Content-Type", "application/json")
        req.add_header("Accept", "text/event-stream" if stream else "application/json")
        if self.api_key:
            req.add_header("Authorization", "Bearer " + self.api_key)
        return req

    def _post(self, payload, timeout=None):
        req = self._request(payload, stream=False)
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

    def _post_stream(self, payload, on_delta, timeout=None):
        """SSE 流式读取，边收边回调；返回与 _normalize 同构的结果。"""
        req = self._request(payload, stream=True)
        content_parts = []
        calls = []          # [{"id","name","arguments_str"}]
        finish_reason = None
        raw_id = None
        model = None
        usage = {}
        t0 = time.time()
        try:
            with urllib.request.urlopen(req, timeout=timeout or self.timeout) as resp:
                for raw in resp:
                    line = raw.decode("utf-8", "ignore").strip()
                    if not line or line.startswith(":"):
                        continue
                    if not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if data == "[DONE]":
                        break
                    try:
                        chunk = json.loads(data)
                    except ValueError:
                        continue
                    raw_id = raw_id or chunk.get("id")
                    model = model or chunk.get("model")
                    if chunk.get("usage"):
                        usage = chunk["usage"]
                    for choice in chunk.get("choices") or []:
                        delta = choice.get("delta") or {}
                        piece = delta.get("content")
                        if piece:
                            content_parts.append(piece)
                            try:
                                on_delta(piece)
                            except Exception:
                                pass
                        for tc in delta.get("tool_calls") or []:
                            idx = int(tc.get("index") or 0)
                            while len(calls) <= idx:
                                calls.append({"id": "", "name": "", "arguments": ""})
                            slot = calls[idx]
                            if tc.get("id"):
                                slot["id"] = tc["id"]
                            fn = tc.get("function") or {}
                            if fn.get("name"):
                                slot["name"] = fn["name"]
                            if fn.get("arguments"):
                                slot["arguments"] += fn["arguments"]
                        if choice.get("finish_reason"):
                            finish_reason = choice["finish_reason"]
                    if finish_reason:
                        # 有些实现把 usage 放在最后一个 chunk，继续读到 DONE 也没关系
                        pass
        except urllib.error.HTTPError as e:
            text = ""
            try:
                text = e.read().decode("utf-8", "ignore")
            except Exception:
                pass
            raise LLMError("HTTP %s: %s" % (e.code, _short(text)), status=e.code, body=text,
                           retriable=e.code in (408, 409, 429, 500, 502, 503, 504))
        except urllib.error.URLError as e:
            raise LLMError("network error: %s" % e.reason, retriable=True)

        tool_calls = []
        for i, c in enumerate(calls):
            args, parse_error = {}, None
            raw_args = c.get("arguments") or ""
            if raw_args.strip():
                try:
                    args = json.loads(raw_args)
                except ValueError:
                    parse_error = "arguments 不是合法 JSON: %s" % _short(raw_args, 300)
                    args = {"_raw": raw_args}
            tool_calls.append({"id": c.get("id") or "call_%d_%d" % (int(time.time() * 1000), i),
                               "name": c.get("name") or "unknown",
                               "arguments": args, "parse_error": parse_error})
        self.usage["prompt_tokens"] += usage.get("prompt_tokens", 0) or 0
        self.usage["completion_tokens"] += usage.get("completion_tokens", 0) or 0
        self.usage["total_tokens"] += usage.get("total_tokens", 0) or 0
        return {
            "content": "".join(content_parts),
            "tool_calls": tool_calls,
            "finish_reason": finish_reason,
            "usage": usage,
            "latency_ms": int((time.time() - t0) * 1000),
            "model": model or self.model,
            "raw_id": raw_id,
            "streamed": True,
        }

    # ---------------- 对话 ----------------
    def chat(self, messages, tools=None, temperature=None, max_tokens=None,
             on_delta=None, trace=None, stream=None):
        if not self.api_key:
            raise LLMError("llm.api_key 未配置（config/config.json 的 llm.api_key 或环境变量 HIVE_LLM_API_KEY）")
        use_stream = self.stream if stream is None else bool(stream)
        use_stream = use_stream and on_delta is not None
        payload = {
            "model": self.model,
            "messages": messages,
            "stream": use_stream,
            "temperature": self.temperature if temperature is None else temperature,
        }
        mt = max_tokens if max_tokens is not None else self.max_tokens
        if mt:
            payload["max_tokens"] = int(mt)
        if use_stream:
            payload["stream_options"] = {"include_usage": True}
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"

        if callable(trace):
            trace("llm.request", {
                "endpoint": self.endpoint,
                "model": self.model,
                "stream": use_stream,
                "temperature": payload["temperature"],
                "max_tokens": payload.get("max_tokens"),
                "message_count": len(messages),
                "tool_count": len(tools or []),
                "messages": messages,
                "tools": tools or [],
            })

        attempt = 0
        last = None
        while attempt <= self.max_retries:
            t0 = time.time()
            try:
                if use_stream:
                    data = self._post_stream(payload, on_delta)
                    self.usage["calls"] += 1
                    self.usage["streams"] += 1
                    res = data
                else:
                    data = self._post(payload)
                    self.usage["calls"] += 1
                    res = self._normalize(data, time.time() - t0)
                if callable(trace):
                    trace("llm.response", {
                        "model": res.get("model"),
                        "id": res.get("raw_id"),
                        "latency_ms": res.get("latency_ms"),
                        "finish_reason": res.get("finish_reason"),
                        "streamed": bool(res.get("streamed")),
                        "usage": res.get("usage"),
                        "content": res.get("content"),
                        "tool_calls": res.get("tool_calls"),
                    })
                return res
            except LLMError as e:
                self.usage["errors"] += 1
                last = e
                if callable(trace):
                    trace("llm.error", {"status": e.status, "error": e.message, "attempt": attempt})
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
            "streamed": False,
        }

    def complete_text(self, system, user, max_tokens=None):
        """纯文本补全，用于摘要/压缩这类不挂工具的场景。"""
        res = self.chat(
            [{"role": "system", "content": system}, {"role": "user", "content": user}],
            tools=None,
            max_tokens=max_tokens,
            stream=False,
        )
        return res["content"] or ""

    def ping(self):
        t0 = time.time()
        try:
            res = self.chat([{"role": "user", "content": "ping，只回 pong"}], tools=None, max_tokens=8,
                            temperature=0, stream=False)
            return {"ok": True, "model": res["model"], "latency_ms": int((time.time() - t0) * 1000),
                    "text": _short(res["content"], 60)}
        except LLMError as e:
            return {"ok": False, "error": e.message, "status": e.status, "latency_ms": int((time.time() - t0) * 1000)}
