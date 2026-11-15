"""资源守门：读数全部来自 host 能力（本模块不碰 /proc、不碰磁盘 API）。"""
from __future__ import annotations


def check(ctx):
    cfg = ctx.cfg.get("agents", {}).get("guard", {}) or {}
    host = ctx.host.info(ctx) or {}
    reasons = []

    load = host.get("load1")
    limit = float(cfg.get("max_load_ratio", 1.5))
    if load is not None and limit > 0 and load > limit:
        reasons.append({"what": "load", "value": load, "limit": limit})

    mem = int(host.get("free_mb") or 0)
    limit = int(cfg.get("min_free_mem_mb", 1024))
    if mem and mem < limit:
        reasons.append({"what": "mem", "value": mem, "limit": limit})

    free_mb = int((host.get("free_gb") or 0) * 1024)
    limit = int(cfg.get("min_free_disk_mb", 512))
    if free_mb and free_mb < limit:
        reasons.append({"what": "disk", "value": free_mb, "limit": limit})

    ok = not reasons
    action = "accept" if ok else (cfg.get("on_insufficient") or "reject")
    return {"ok": ok, "reasons": reasons, "action": action}
