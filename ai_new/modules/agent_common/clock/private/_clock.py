"""时间能力实现：读时钟、睡觉、时间戳与文本互换。"""
from __future__ import annotations

import datetime
import time


def now():
    ts = time.time()
    return {"ts": ts, "iso": iso(ts)}


def iso(ts=None):
    value = time.time() if ts is None else float(ts)
    return datetime.datetime.fromtimestamp(value, datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse(text):
    """ISO 文本 → 秒级时间戳；解析不了就是失败结果。"""
    try:
        return {"ok": True, "ts": datetime.datetime.fromisoformat(str(text)).timestamp()}
    except (ValueError, TypeError) as exc:
        return {"ok": False, "error": str(exc), "code": "bad_time"}


def sleep(seconds):
    time.sleep(max(0.0, float(seconds or 0)))
    return {"slept": float(seconds or 0)}


def monotonic():
    return {"ts": time.monotonic()}


def setup(ctx):
    ctx.api.register("clock.now", lambda c, p: now(), "现在（epoch 秒 + ISO）", module="clock")
    ctx.api.register("clock.iso", lambda c, p: {"text": iso(p.get("ts"))},
                     "时间戳 → ISO 文本", module="clock")
    ctx.api.register("clock.parse", lambda c, p: parse(p.get("text")),
                     "ISO 文本 → 时间戳", module="clock")
    ctx.api.register("clock.sleep", lambda c, p: sleep(p.get("seconds")),
                     "等一会儿（秒）", module="clock")
    ctx.api.register("clock.monotonic", lambda c, p: monotonic(),
                     "单调时钟（算间隔用，不受系统改时间影响）", module="clock")
    ctx.api.register("clock.since", lambda c, p: since(p),
                     "某条 ISO 时间距今多少秒", module="clock")
    return True


def since(p):
    """某条 ISO 时间距今多少秒。解析时间归时钟，业务只拿数字。"""
    import datetime
    text = str(p.get("iso") or "")
    if not text:
        return {"seconds": 0, "ok": False}
    try:
        past = datetime.datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return {"seconds": 0, "ok": False}
    now = datetime.datetime.now(past.tzinfo) if past.tzinfo else datetime.datetime.now()
    return {"seconds": int((now - past).total_seconds()), "ok": True}
