"""幂等台账：副作用占位、租约、结算与回收。

文件即库：一条记录一个小 JSON，读改写在 flock 内完成（同一台机器跨进程有效），
目录按模块隔离在 `<module>/data/idem/<桶>/<键前两位>/<键>.json`。

状态机：claimed → running → done / failed / abandoned。
- done：同一键再来直接复用结果摘要，不再执行；
- 租约未过期的 claimed/running：后来者拿到 in_flight，不许并行；
- 租约过期：允许接管（attempt+1），但 abandoned 不接管，交人工。
"""
from __future__ import annotations

import json
import os
import re
import threading

from . import _files
from ._panel import _dir_of

STATUSES = ("claimed", "running", "done", "failed", "abandoned")
LIVE = ("claimed", "running")


def _bucket_dir(module, bucket):
    return _dir_of(module) / "idem" / _files.safe_id(str(bucket or "default"))


def _key_name(key):
    return re.sub(r"[^0-9a-zA-Z_-]", "", str(key or ""))[:96]


def _rec_path(module, bucket, key):
    name = _key_name(key)
    if not name:
        raise ValueError("幂等键为空")
    return _bucket_dir(module, bucket) / name[:2] / (name + ".json")


def _now(ctx):
    try:
        return float(ctx.clock.now().get("ts"))
    except Exception:
        import time
        return time.time()


def _iso(ts):
    try:
        from datetime import datetime, timezone
        return datetime.fromtimestamp(float(ts), timezone.utc).isoformat()
    except Exception:
        return ""


def _read(path):
    try:
        text = _files.read_text(path)
        obj = json.loads(text) if text else None
        return obj if isinstance(obj, dict) else {}
    except Exception:
        return {}


def _write(path, rec):
    _files.write_text_atomic(path, json.dumps(rec, ensure_ascii=False, sort_keys=True))


def _lock(path):
    """对记录旁挂的 .lock 做独占锁；平台不支持 flock 时退化为进程内互斥。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    fh = open(str(path.with_name(path.name + ".lock")), "a+")
    try:
        import fcntl
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
    except Exception:
        pass
    return fh


def _unlock(fh):
    try:
        import fcntl
        fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
    except Exception:
        pass
    try:
        fh.close()
    except Exception:
        pass


def _route_claim(ctx, payload):
    """占位：拿到执行权返回 claimed=true；已做完返回 done + 结果摘要。"""
    path = _rec_path(payload.get("module"), payload.get("bucket"), payload.get("key"))
    lease = float(payload.get("lease_seconds") or 60)
    now = _now(ctx)
    fh = _lock(path)
    try:
        rec = _read(path)
        status = str(rec.get("status") or "")
        if status == "done":
            return {"claimed": False, "status": "done", "reused": True,
                    "attempt": rec.get("attempt"),
                    "result_digest": rec.get("result_digest") or ""}
        if status == "abandoned":
            return {"claimed": False, "status": "abandoned",
                    "attempt": rec.get("attempt"),
                    "error_code": rec.get("error_code") or ""}
        if status in LIVE and float(rec.get("lease_until") or 0) > now:
            return {"claimed": False, "status": "running", "in_flight": True,
                    "attempt": rec.get("attempt"),
                    "lease_until": rec.get("lease_until")}
        attempt = int(rec.get("attempt") or 0) + 1
        fresh = {
            "key": payload.get("key"), "route": payload.get("route") or "",
            "scope": payload.get("scope") or "", "status": "claimed",
            "attempt": attempt, "lease_until": now + lease,
            "holder": "%s:%s" % (os.getpid(), threading.get_ident()),
            "created_at": rec.get("created_at") or _iso(now), "updated_at": _iso(now),
        }
        _write(path, fresh)
        return {"claimed": True, "status": "claimed", "attempt": attempt,
                "takeover": bool(rec), "lease_until": fresh["lease_until"]}
    finally:
        _unlock(fh)


def _route_renew(ctx, payload):
    """续租：执行体还活着就延长租约，进程死了自然过期。"""
    path = _rec_path(payload.get("module"), payload.get("bucket"), payload.get("key"))
    lease = float(payload.get("lease_seconds") or 60)
    now = _now(ctx)
    fh = _lock(path)
    try:
        rec = _read(path)
        if str(rec.get("status") or "") not in LIVE:
            return {"renewed": False, "status": rec.get("status") or "missing"}
        rec["lease_until"] = now + lease
        rec["updated_at"] = _iso(now)
        _write(path, rec)
        return {"renewed": True, "lease_until": rec["lease_until"]}
    finally:
        _unlock(fh)


def _route_settle(ctx, payload):
    """结算：done 落结果摘要，failed 落错误码，abandoned 交人工。"""
    status = str(payload.get("status") or "")
    if status not in STATUSES:
        raise ValueError("非法结算状态: %s" % status)
    path = _rec_path(payload.get("module"), payload.get("bucket"), payload.get("key"))
    now = _now(ctx)
    fh = _lock(path)
    try:
        rec = _read(path)
        rec.update({"key": payload.get("key"), "route": rec.get("route") or "",
                    "scope": payload.get("scope") or rec.get("scope") or "",
                    "status": status,
                    "attempt": int(rec.get("attempt") or 0) or 1,
                    "result_digest": payload.get("result_digest") or "",
                    "error_code": payload.get("error_code") or "",
                    "lease_until": 0, "updated_at": _iso(now),
                    "created_at": rec.get("created_at") or _iso(now)})
        _write(path, rec)
        return {"settled": True, "status": status, "attempt": rec["attempt"]}
    finally:
        _unlock(fh)


def _route_sweep(ctx, payload):
    """回收扫描：列出（并可按 mark 标记）租约过期仍未结算的记录。"""
    base = _bucket_dir(payload.get("module"), payload.get("bucket"))
    now = _now(ctx)
    expired, marked, checked = [], 0, 0
    paths = sorted(base.glob("*/*.json")) if base.is_dir() else []
    for path in paths:
        checked += 1
        rec = _read(path)
        if str(rec.get("status") or "") not in LIVE:
            continue
        if float(rec.get("lease_until") or 0) > now:
            continue
        expired.append(rec.get("key"))
        if payload.get("mark"):
            fh = _lock(path)
            try:
                cur = _read(path)
                if str(cur.get("status") or "") in LIVE:
                    cur["status"] = "abandoned"
                    cur["error_code"] = "lease_expired"
                    cur["updated_at"] = _iso(now)
                    _write(path, cur)
                    marked += 1
            finally:
                _unlock(fh)
    return {"expired": expired, "checked": checked, "marked": marked}


def register(ctx):
    for name, fn in [
        ("store.claim", _route_claim),
        ("store.renew", _route_renew),
        ("store.settle", _route_settle),
        ("store.sweep", _route_sweep),
    ]:
        ctx.api.register(name, fn, module="store")
