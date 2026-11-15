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
