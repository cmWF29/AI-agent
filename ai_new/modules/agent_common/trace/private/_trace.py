"""链路追踪：一条外部请求 / 一次事件 = 一个 trace，一次调用 = 一个 span。

本模块只做三件事：开 span、关 span、按 trace 读回调用树。
写盘在后台线程批量追加，不阻塞业务；采样与开关走配置。
"""
from __future__ import annotations

import contextvars
import itertools
import json
import queue
import threading
import time

_CUR = contextvars.ContextVar("trace_cur", default=None)
_SEQ = itertools.count(1)
_PEND = {}
_LOCK = threading.Lock()
_Q = queue.Queue(maxsize=50000)
_S = {"tag": "", "st": None, "enabled": True, "sample": 1.0, "dropped": 0, "thread": None}


def _now():
    return time.time()


def _new_id():
    return "%x-%s-%x" % (int(_now() * 1000), _S["tag"], next(_SEQ))


def _day(ts):
    return time.strftime("%Y%m%d", time.localtime(ts))


def _hour(ts):
    return time.strftime("%H", time.localtime(ts))


def _rel_for(ts):
    return "trace/%s/%s.jsonl" % (_day(ts), _hour(ts))


def _flush_loop():
    while True:
        batch = []
        try:
            line = _Q.get(timeout=0.5)
            batch.append(line)
            while len(batch) < 500:
                batch.append(_Q.get_nowait())
        except queue.Empty:
            pass
        if not batch:
            continue
        try:
            st = _S["st"]
            if st is None:
                continue
            rel = _rel_for(_now())
            st.dir("trace/" + _day(_now()))
            st.append_text(rel, "\n".join(batch) + "\n")
        except Exception:
            pass


def _ensure_thread():
    if _S["thread"] is not None:
        return
    th = threading.Thread(target=_flush_loop, name="trace-writer", daemon=True)
    th.start()
    _S["thread"] = th


def _fetch(hook):
    _ensure_thread()
    try:
        _Q.put_nowait(hook)
        return True
    except queue.Full:
        _S["dropped"] += 1
        return False


def _trace_ctx():
    return _CUR.get() or {}


def _route_attach(ctx, payload):
    """把外部带进来的 trace 身份装进当前上下文（HTTP 入口/跨通道注入用）。"""
    tid = str(payload.get("trace") or "")
    if tid:
        cur = _trace_ctx()
        _CUR.set({"trace": tid, "span": cur.get("span") or "",
                  "parent": cur.get("parent") or ""})
    return {"trace": tid}


def _route_open(ctx, payload):
    if not _S["enabled"]:
        return {"trace": "", "span": "", "parent": "", "off": True}
    cur = _trace_ctx()
    tid = str(payload.get("trace") or cur.get("trace") or _new_id())
    parent = str(payload.get("parent") or cur.get("span") or "")
    span = "%s-%d" % (_S["tag"], next(_SEQ))
    rec = {"trace": tid, "span": span, "parent": parent,
           "name": str(payload.get("name") or "")[:120],
           "caller": str(payload.get("caller") or cur.get("caller") or "")[:80],
           "start": _now(), "attrs": payload.get("attrs") or {}}
    with _LOCK:
        _PEND[span] = rec
    _CUR.set({"trace": tid, "span": span, "parent": parent,
              "caller": rec["caller"]})
    return {"trace": tid, "span": span, "parent": parent}


def _route_close(ctx, payload):
    if not _S["enabled"]:
        return {"written": False, "off": True}
    span = str(payload.get("span") or "")
    with _LOCK:
        rec = _PEND.pop(span, None)
    if not rec:
        return {"written": False, "missing": True}
    rec["status"] = str(payload.get("status") or "ok")[:24]
    rec["code"] = str(payload.get("code") or "")[:60]
    rec["dur_ms"] = round((_now() - float(rec.get("start") or 0)) * 1000.0, 2)
    extra = payload.get("attrs") or {}
    if isinstance(extra, dict) and extra:
        rec.setdefault("attrs", {})
        for k, v in list(extra.items())[:12]:
            rec["attrs"][str(k)[:40]] = (v if isinstance(v, (int, float, bool)) else str(v)[:200])
    _CUR.set({"trace": rec["trace"], "span": rec["parent"], "parent": ""})
    if _sampled(rec):
        lines = json.dumps(rec, ensure_ascii=False, sort_keys=True)
        _fetch(lines)
    return {"written": True, "dur_ms": rec["dur_ms"]}


def _sampled(rec):
    try:
        if _S["sample"] >= 1:
            return True
        return (int(str(rec.get("span") or "0").rsplit("-", 1)[-1]) % 1000) < int(_S["sample"] * 1000)
    except Exception:
        return True


def _read_day(date):
    rows = []
    st = _S["st"]
    if st is None:
        return rows
    rel = "trace/" + str(date)
    if not st.is_dir(rel):
        return rows
    for name in st.list_dir(rel):
        if not name.endswith(".jsonl"):
            continue
        try:
            text = st.read_text(rel + "/" + name) or ""
        except Exception:
            continue
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except Exception:
                continue
    return rows


def _route_get(ctx, payload):
    """按 trace 读回整棵树：先拿 span 清单，再由前端/调用方按 parent 组装。"""
    tid = str(payload.get("trace") or "")
    date = str(payload.get("date") or _day(_now()))
    rows = [r for r in _read_day(date) if r.get("trace") == tid]
    if not rows and not payload.get("date"):
        rows = [r for r in _read_day(_day(_now() - 86400)) if r.get("trace") == tid]
    rows.sort(key=lambda r: float(r.get("start") or 0))
    total = sum(float(r.get("dur_ms") or 0) for r in rows if not r.get("parent"))
    return {"trace": tid, "spans": rows, "count": len(rows),
            "total_ms": round(total, 2)}


def _route_list(ctx, payload):
    date = str(payload.get("date") or _day(_now()))
    rows = _read_day(date)
    by = {}
    for r in rows:
        t = r.get("trace") or ""
        if not t:
            continue
        item = by.setdefault(t, {"trace": t, "spans": 0, "start": 1e18, "dur_ms": 0.0,
                                 "err": 0})
        item["spans"] += 1
        item["start"] = min(item["start"], float(r.get("start") or 0))
        if not r.get("parent"):
            item["dur_ms"] = float(r.get("dur_ms") or 0)
        if str(r.get("status") or "") not in ("ok", ""):
            item["err"] += 1
    items = sorted(by.values(), key=lambda x: x["start"], reverse=True)
    limit = int(payload.get("limit") or 50)
    return {"date": date, "total": len(items), "items": items[:limit]}


def _route_slow(ctx, payload):
    date = str(payload.get("date") or _day(_now()))
    rows = _read_day(date)
    agg = {}
    for r in rows:
        name = r.get("name") or ""
        if not name:
            continue
        a = agg.setdefault(name, {"name": name, "n": 0, "sum": 0.0, "max": 0.0,
                                  "err": 0, "vals": []})
        dur = float(r.get("dur_ms") or 0)
        a["n"] += 1
        a["sum"] += dur
        a["max"] = max(a["max"], dur)
        if str(r.get("status") or "") not in ("ok", ""):
            a["err"] += 1
        a["vals"].append(dur)
    items = []
    for a in agg.values():
        vals = sorted(a["vals"])
        n = len(vals)
        items.append({"name": a["name"], "n": n,
                      "avg_ms": round(a["sum"] / n, 2), "max_ms": round(a["max"], 2),
                      "p50_ms": round(vals[int(n * 0.5) - 1] if n >= 2 else vals[0], 2),
                      "p95_ms": round(vals[min(n - 1, int(n * 0.95))], 2),
                      "err": a["err"]})
    items.sort(key=lambda x: x["p95_ms"], reverse=True)
    return {"date": date, "items": items[:int(payload.get("limit") or 20)],
            "spans": len(rows)}


def setup(ctx):
    _S["tag"] = str(id(_S) % 99991)
    _S["st"] = ctx.storage.own(__file__)
    cfg = {}
    try:
        cfg = ctx.cfg.get("trace") or {}
    except Exception:
        cfg = {}
    _S["enabled"] = bool(cfg.get("enabled", True))
    try:
        _S["sample"] = float(cfg.get("sample") or 1.0)
    except Exception:
        _S["sample"] = 1.0
    _ensure_thread()
    ctx.api.register("trace.attach", _route_attach, module="trace")
    ctx.api.register("trace.open", _route_open, module="trace")
    ctx.api.register("trace.close", _route_close, module="trace")
    ctx.api.register("trace.get", _route_get, module="trace")
    ctx.api.register("trace.list", _route_list, module="trace")
    ctx.api.register("trace.slow", _route_slow, module="trace")
    return True
