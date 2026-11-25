"""HTTP(S) 出站实现（纯 stdlib，协程流）。失败是结果、不是异常：返回 {ok:false, error}。

阻塞的 urllib 不再使用：请求/连接经 asyncio 流收发，协程内真非阻塞等待；
连接类瞬时故障与 5xx 短退避重试，4xx 是请求本身问题不重试。
"""
from __future__ import annotations

import asyncio
import ssl
from urllib.parse import urlparse

# 连接类瞬时故障与 5xx 值得短退避重试；4xx 是请求本身问题，不重试。
_RETRYABLE_CODES = {"unreachable", "net_error"}


def _retryable(code, status):
    if code in _RETRYABLE_CODES:
        return True
    try:
        return int(status or 0) >= 500
    except (TypeError, ValueError):
        return False


def _backoff(attempt):
    return asyncio.sleep(min(2.0, 0.5 * (attempt + 1)))


def _split_url(url):
    pr = urlparse(str(url))
    host = pr.hostname or ""
    port = pr.port or (443 if pr.scheme == "https" else 80)
    path = pr.path or "/"
    if pr.query:
        path = path + "?" + pr.query
    return pr.scheme, host, port, path


def _raw_body(body):
    """请求体归一为字节：文本按 utf-8 编码；字节/字节透传（二进制对象通道用）。"""
    if body is None:
        return b""
    if isinstance(body, (bytes, bytearray)):
        return bytes(body)
    return str(body).encode("utf-8")


def _build_request(method, host, path, headers, body):
    hdrs = dict(headers or {})
    hdrs["Host"] = host
    raw = _raw_body(body)
    if body is not None:
        hdrs["Content-Length"] = str(len(raw))
    lines = ["%s %s HTTP/1.1" % (method, path)]
    for k, v in hdrs.items():
        lines.append("%s: %s" % (k, v))
    head = ("\r\n".join(lines) + "\r\n\r\n").encode("utf-8")
    if body is not None:
        head += raw
    return head


async def _open(scheme, host, port, timeout):
    ssl_ctx = ssl.create_default_context() if scheme == "https" else False
    return await asyncio.wait_for(
        asyncio.open_connection(host, port, ssl=ssl_ctx), timeout=timeout)


async def _read_status(reader):
    status_line = await reader.readline()
    if not status_line:
        raise IOError("连接被关闭")
    parts = status_line.decode("utf-8", "replace").split()
    status = int(parts[1]) if len(parts) > 1 else 0
    headers = {}
    while True:
        line = await reader.readline()
        if line in (b"\r\n", b"\n", b""):
            break
        k, _, v = line.decode("utf-8", "replace").partition(":")
        headers[k.strip().lower()] = v.strip()
    return status, headers


async def _read_chunked(reader):
    """按 HTTP/1.1 chunked 编码逐块解码，直到 0 长度块。"""
    chunks = []
    while True:
        line = await reader.readline()
        if not line:
            break
        size_text = line.decode("utf-8", "replace").strip().split(";")[0].strip()
        try:
            size = int(size_text, 16)
        except ValueError:
            size = 0
        if size == 0:
            break
        data = await reader.readexactly(size)
        chunks.append(data)
        await reader.readline()  # 块尾 CRLF
    return b"".join(chunks)


async def _read_body(reader, headers):
    te = (headers.get("transfer-encoding") or "").lower()
    if "chunked" in te:
        return await _read_chunked(reader)
    length = headers.get("content-length")
    if length and length.isdigit():
        return await reader.readexactly(int(length))
    # 无 Content-Length 且非 chunked：读到流结束。
    return await reader.read()


async def arequest(ctx, url, method="GET", headers=None, body=None, timeout=None, retries=2):
    if not url:
        return {"ok": False, "error": "缺少 url", "code": "bad_request"}
    if body is not None and not isinstance(body, (str, bytes, bytearray)):
        return {"ok": False, "error": "body 必须是文本或字节（二进制对象通道用字节透传）",
                "code": "bad_body"}
    scheme, host, port, path = _split_url(url)
    if not host:
        return {"ok": False, "error": "缺少 url", "code": "bad_request"}
    limit = float(timeout or 60)
    payload = _build_request(method, host, path, headers, body)
    last = None
    attempt = 0
    while True:
        reader = writer = None
        try:
            reader, writer = await _open(scheme, host, port, limit)
            writer.write(payload)
            await writer.drain()
            status, resp_headers = await _read_status(reader)
            raw = await asyncio.wait_for(_read_body(reader, resp_headers), timeout=limit)
            return {"ok": True, "status": status,
                    "headers": resp_headers,
                    "text": raw.decode("utf-8", "replace"), "body": raw}
        except Exception as exc:  # noqa: BLE001 —— 能力层不外抛
            code = "unreachable" if isinstance(exc, (IOError, OSError, asyncio.TimeoutError)) else "net_error"
            last = {"ok": False, "status": 0, "error": str(exc), "code": code}
            if not _retryable(code, 0) or attempt >= retries:
                return last
        finally:
            if writer is not None:
                try:
                    writer.close()
                    await writer.wait_closed()
                except Exception:  # noqa: BLE001
                    pass
        await _backoff(attempt)
        attempt += 1


async def arequest_stream(ctx, url, method="POST", headers=None, body=None, timeout=None,
                          stream_key="", retries=2):
    """SSE 流式出站：逐帧读响应，正文增量推入运行期草稿槽，事件对象汇总后返回。

    net 只做传输与帧切分；正文文本接入通用草稿槽（与 exec 把进程 stdout 行当正文同构），
    tool_calls / finish / usage 的语义归一仍由 llm.decode_sse 完成。
    仅连接阶段的瞬时故障/5xx 短退避重试；流一旦开始读帧就不再重试，避免草稿槽重复累积。
    """
    # 原文保留条数属于传输策略，不在代码里写死：读不到配置就按 0 处理（不保留原文）
    line_cap = int(ctx.api.call("config.get", {"key": "net.stream_lines"},
                                caller=None).get("value") or 0)
    if not url:
        return {"ok": False, "error": "缺少 url", "code": "bad_request"}
    if body is not None and not isinstance(body, (str, bytes, bytearray)):
        return {"ok": False, "error": "body 必须是文本或字节（二进制对象通道用字节透传）",
                "code": "bad_body"}
    scheme, host, port, path = _split_url(url)
    if not host:
        return {"ok": False, "error": "缺少 url", "code": "bad_request"}
    payload = _build_request(method, host, path, headers, body)
    limit = float(timeout or 60)
    runtime = getattr(ctx, "runtime", None)
    items = []
    raw_lines = []
    last = None
    attempt = 0
    while True:
        reader = writer = None
        connected = False
        try:
            reader, writer = await _open(scheme, host, port, limit)
            writer.write(payload)
            await writer.drain()
            status, _ = await _read_status(reader)
            connected = True
            while True:
                raw = await asyncio.wait_for(reader.readline(), timeout=limit)
                if not raw:
                    break
                line = raw.decode("utf-8", "replace").strip()
                if not line or not line.startswith("data:"):
                    continue
                chunk = line[5:].strip()
                if chunk == "[DONE]":
                    break
                dec = ctx.api.call("codec.json_decode", {"text": chunk}, caller=None)
                if not dec.get("ok"):
                    continue
                obj = dec.get("value")
                if not isinstance(obj, dict):
                    continue
                items.append(obj)
                if line_cap > 0 and len(raw_lines) < line_cap:
                    raw_lines.append(line)
                delta = (obj.get("choices") or [{}])[0].get("delta") or {}
                piece = delta.get("content")
                if piece and stream_key and runtime is not None:
                    runtime.stream_put(stream_key, piece)
            return {"ok": True, "status": status, "items": items,
                    "raw": "\n".join(raw_lines)}
        except Exception as exc:  # noqa: BLE001 —— 读帧阶段失败不外抛
            code = "unreachable" if isinstance(exc, (IOError, OSError, asyncio.TimeoutError)) else "net_error"
            last = {"ok": False, "status": 0, "error": str(exc), "code": code}
            if connected or attempt >= retries or not _retryable(code, 0):
                return last
        finally:
            if writer is not None:
                try:
                    writer.close()
                    await writer.wait_closed()
                except Exception:  # noqa: BLE001
                    pass
        await _backoff(attempt)
        attempt += 1


def request(ctx, url, method="GET", headers=None, body=None, timeout=None, retries=2):
    """同步壳：桥接异步核心到进程级事件循环，供同步内部调用与测试直调。"""
    loop = ctx.api._ensure_loop()
    return asyncio.run_coroutine_threadsafe(
        arequest(ctx, url, method=method, headers=headers, body=body,
                 timeout=timeout, retries=retries), loop).result()


def request_stream(ctx, url, method="POST", headers=None, body=None, timeout=None,
                   stream_key="", retries=2):
    """同步壳：桥接异步核心到进程级事件循环，供同步内部调用与测试直调。"""
    loop = ctx.api._ensure_loop()
    return asyncio.run_coroutine_threadsafe(
        arequest_stream(ctx, url, method=method, headers=headers, body=body,
                        timeout=timeout, stream_key=stream_key, retries=retries),
        loop).result()

