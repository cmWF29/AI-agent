"""HTTP(S) 出站实现（纯 stdlib）。失败是结果、不是异常：返回 {ok:false, error}。"""
from __future__ import annotations

import urllib.error
import urllib.request


def request(ctx, url, method="GET", headers=None, body=None, timeout=None):
    if not url:
        return {"ok": False, "error": "缺少 url", "code": "bad_request"}
    data = None
    hdrs = dict(headers or {})
    if body is not None:
        if not isinstance(body, str):
            return {"ok": False, "error": "body 必须是文本（对象先经 codec.json_encode）",
                    "code": "bad_body"}
        data = body.encode("utf-8")
    req = urllib.request.Request(str(url), data=data, headers=hdrs, method=str(method or "GET"))
    limit = float(timeout or 60)
    try:
        with urllib.request.urlopen(req, timeout=limit) as resp:
            raw = resp.read()
            return {"ok": True, "status": resp.status,
                    "headers": dict(resp.headers), "text": raw.decode("utf-8", "replace")}
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:600]
        return {"ok": False, "status": exc.code, "error": detail,
                "code": "http_%s" % exc.code}
    except urllib.error.URLError as exc:
        return {"ok": False, "status": 0, "error": str(exc.reason), "code": "unreachable"}
    except Exception as exc:  # noqa: BLE001 —— 能力层不外抛
        return {"ok": False, "status": 0, "error": str(exc), "code": "net_error"}


def request_stream(ctx, url, method="POST", headers=None, body=None, timeout=None,
                   stream_key=""):
    """SSE 流式出站：逐帧读响应，正文增量推入运行期草稿槽，事件对象汇总后返回。

    net 只做传输与帧切分；正文文本接入通用草稿槽（与 exec 把进程 stdout 行当正文同构），
    tool_calls / finish / usage 的语义归一仍由 llm.decode_sse 完成。
    """
    if not url:
        return {"ok": False, "error": "缺少 url", "code": "bad_request"}
    data = None
    hdrs = dict(headers or {})
    if body is not None:
        if not isinstance(body, str):
            return {"ok": False, "error": "body 必须是文本（对象先经 codec.json_encode）",
                    "code": "bad_body"}
        data = body.encode("utf-8")
    req = urllib.request.Request(str(url), data=data, headers=hdrs, method=str(method or "POST"))
    limit = float(timeout or 60)
    runtime = getattr(ctx, "runtime", None)
    items = []
    try:
        with urllib.request.urlopen(req, timeout=limit) as resp:
            for raw in iter(resp.readline, b""):
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
                delta = (obj.get("choices") or [{}])[0].get("delta") or {}
                piece = delta.get("content")
                if piece and stream_key and runtime is not None:
                    runtime.stream_put(stream_key, piece)
            return {"ok": True, "status": resp.status, "items": items}
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:600]
        return {"ok": False, "status": exc.code, "error": detail,
                "code": "http_%s" % exc.code}
    except urllib.error.URLError as exc:
        return {"ok": False, "status": 0, "error": str(exc.reason), "code": "unreachable"}
    except Exception as exc:  # noqa: BLE001 —— 能力层不外抛
        return {"ok": False, "status": 0, "error": str(exc), "code": "net_error"}
