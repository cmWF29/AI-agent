"""时间能力实现：读时钟、睡觉、时间戳与文本互换；定时调度的时刻推算也归这里。"""
from __future__ import annotations

import datetime
import time

try:
    from zoneinfo import ZoneInfo
except ModuleNotFoundError:  # Python 3.8 及更早没有标准库 zoneinfo
    try:
        from backports.zoneinfo import ZoneInfo
    except ModuleNotFoundError:
        ZoneInfo = None

# 无 zoneinfo 时按固定偏移兜底（无夏令时的常用区域）；有夏令时的区域仍要求 zoneinfo。
_FIXED_OFFSET_HOURS = {
    "UTC": 0, "GMT": 0, "Etc/UTC": 0,
    "Asia/Shanghai": 8, "Asia/Chongqing": 8, "Asia/Hong_Kong": 8,
    "Asia/Taipei": 8, "Asia/Singapore": 8, "Asia/Macau": 8,
    "Asia/Tokyo": 9, "Asia/Seoul": 9,
    "Asia/Kolkata": 5.5, "Asia/Dubai": 4,
    "Europe/London": 0, "Europe/Moscow": 3,
}


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
    ctx.api.register("clock.sleep", lambda c, p: sleep(p.get("seconds")),
                     "等一会儿（秒）", module="clock")
    ctx.api.register("clock.since", lambda c, p: since(p),
                     "某条 ISO 时间距今多少秒", module="clock")
    # schedule_next / due_slots 是纯调度推算函数，不注册为 API；
    # 调用方（timer）经 ctx.clock 模块内直调，不走注册表。
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


# ---------------------------------------------------------------- 定时调度推算

def _load_tz(name):
    """时区名 → tzinfo；解析不了返回 None。

    优先 zoneinfo（含 backports 兜底）；解释器没有 zoneinfo 时，
    退到 _FIXED_OFFSET_HOURS 里的固定偏移，保证老版本 Python 也能跑起服务。
    """
    key = str(name or "").strip()
    if not key:
        return None
    if ZoneInfo is not None:
        try:
            return ZoneInfo(key)
        except (KeyError, ValueError, TypeError):
            pass
    hours = _FIXED_OFFSET_HOURS.get(key)
    if hours is None:
        return None
    return datetime.timezone(datetime.timedelta(hours=hours), key)


def _cron_field(spec, lo, hi):
    """解析单个 cron 字段：`*` / 列表 / 区间 / 步长；非法返回 None。"""
    values = set()
    for part in str(spec or "").split(","):
        if not part:
            return None
        step = 1
        if "/" in part:
            rng, step_s = part.split("/", 1)
            try:
                step = int(step_s)
            except ValueError:
                return None
        else:
            rng = part
        if rng == "*":
            start, end = lo, hi
        elif "-" in rng:
            a, b = rng.split("-", 1)
            try:
                start, end = int(a), int(b)
            except ValueError:
                return None
        else:
            try:
                start = end = int(rng)
            except ValueError:
                return None
        if start < lo or end > hi or start > end or step <= 0:
            return None
        values.update(range(start, end + 1, step))
    return values or None


def _parse_cron(expr):
    """五段表达式 → {minute, hour, dom, month, dow}；非法返回 None。"""
    parts = str(expr or "").split()
    if len(parts) != 5:
        return None
    minute = _cron_field(parts[0], 0, 59)
    hour = _cron_field(parts[1], 0, 23)
    dom = _cron_field(parts[2], 1, 31)
    month = _cron_field(parts[3], 1, 12)
    dow = _cron_field(parts[4], 0, 6)
    if None in (minute, hour, dom, month, dow):
        return None
    return {"minute": minute, "hour": hour, "dom": dom, "month": month, "dow": dow}


def _cron_match(fields, dt):
    """aware 时刻是否命中 cron 五段；dow 0=周日（Python weekday+1 取模）。"""
    if dt.minute not in fields["minute"]:
        return False
    if dt.hour not in fields["hour"]:
        return False
    if dt.day not in fields["dom"]:
        return False
    if dt.month not in fields["month"]:
        return False
    dow_py = (dt.weekday() + 1) % 7
    return dow_py in fields["dow"]


def _slot_of(ts, tz):
    """槽位标识：目标时区下的分钟桶（YYYY-MM-DDTHH:MM）。"""
    dt = datetime.datetime.fromtimestamp(ts, tz)
    return dt.strftime("%Y-%m-%dT%H:%M")


def _parse_once(expr, tz):
    """once 表达式（ISO）→ 时间戳；naive 按时区解释。失败回 bad_time/bad_tz。"""
    text = str(expr or "").strip()
    if not text:
        return {"code": "bad_time"}
    try:
        dt = datetime.datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return {"code": "bad_time"}
    if dt.tzinfo is None:
        if tz is None:
            return {"code": "bad_tz"}
        dt = dt.replace(tzinfo=tz)
    return {"ts": dt.timestamp()}


def schedule_next(p):
    """推算下一次触发：once 取指定时刻；cron 取 after 之后首个命中分钟。"""
    kind = p.get("kind")
    expr = p.get("expr")
    tz_name = p.get("tz") or ""
    after = float(p.get("after") or 0)
    min_interval = int(p.get("min_interval_s") or 0)
    tz = _load_tz(tz_name) if tz_name else datetime.timezone.utc
    if kind == "once":
        once = _parse_once(expr, tz)
        if once.get("code"):
            return {"ok": False, "code": once["code"]}
        ts = once["ts"]
        if ts < after + min_interval:
            return {"ok": False, "code": "interval_too_short"}
        return {"ok": True, "ts": ts, "iso": iso(ts), "slot": _slot_of(ts, tz)}
    if kind == "cron":
        fields = _parse_cron(expr)
        if fields is None:
            return {"ok": False, "code": "bad_cron"}
        if tz_name and tz is None:
            return {"ok": False, "code": "bad_tz"}
        minute0 = after - (after % 60)
        for step in range(366 * 1440):
            ts = minute0 + step * 60
            # 严格晚于 after：正好等于 after 的整分不算「下一次」，否则触发完
            # 重排会原地不动（next_at 停在过去，界面显示过期、下一拍又撞同一槽位）。
            if ts <= after:
                continue
            dt = datetime.datetime.fromtimestamp(ts, tz)
            if _cron_match(fields, dt):
                return {"ok": True, "ts": ts, "iso": iso(ts), "slot": _slot_of(ts, tz)}
        return {"ok": False, "code": "bad_cron"}
    return {"ok": False, "code": "bad_kind"}


def due_slots(p):
    """枚举 after 到 now 之间到期的槽位；once 至多一个，cron 按分钟命中，受 limit 截断。"""
    kind = p.get("kind")
    expr = p.get("expr")
    tz_name = p.get("tz") or ""
    after = float(p.get("after") or 0)
    now = float(p.get("now") or 0)
    limit = int(p.get("limit") or 0)
    tz = _load_tz(tz_name) if tz_name else datetime.timezone.utc
    slots = []
    if kind == "once":
        once = _parse_once(expr, tz)
        if once.get("code"):
            return {"ok": False, "code": once["code"], "slots": []}
        # 漏跑补触发：到点即算到期，是否已执行由 fired 去重兜底
        if once["ts"] <= now:
            slots.append(_slot_of(once["ts"], tz))
        return {"ok": True, "slots": slots}
    if kind != "cron":
        return {"ok": False, "code": "bad_kind", "slots": []}
    fields = _parse_cron(expr)
    if fields is None:
        return {"ok": False, "code": "bad_cron", "slots": []}
    if tz_name and tz is None:
        return {"ok": False, "code": "bad_tz", "slots": []}
    minute0 = after - (after % 60)
    for step in range(366 * 1440):
        ts = minute0 + step * 60
        if ts > now:
            break
        dt = datetime.datetime.fromtimestamp(ts, tz)
        if _cron_match(fields, dt):
            slots.append(_slot_of(ts, tz))
            if limit and len(slots) >= limit:
                break
    return {"ok": True, "slots": slots}
