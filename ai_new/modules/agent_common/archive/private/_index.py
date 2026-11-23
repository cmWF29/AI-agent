"""压缩索引：原大小 / 压缩后大小 / 算法 / 时间 / 校验和台账。

索引落在 archive 自己的数据目录（``index.json``），不塞进别人的 data。
键为原始文件的绝对路径；重复压缩先查索引，已登记即跳过（幂等）。

索引可重建：正文仍是各数据目录里的压缩流；索引只做台账与观测。
"""
from __future__ import annotations

from . import _policy

INDEX_FILE = "index.json"
VERSION = 1


def _empty():
    return {"version": VERSION, "records": {}}


def load(md):
    """读索引；文件缺失 / 损坏时按空台账收口，不把坏盘静默当成空库之外的状态。"""
    if not md.exists(INDEX_FILE):
        return _empty()
    raw = md.read_text(INDEX_FILE)
    out = md.ctx.codec.json_decode(raw or "{}")
    if not out.get("ok"):
        raise ValueError("压缩索引损坏: %s" % out.get("error"))
    body = out["value"] or {}
    records = body.get("records")
    if not isinstance(records, dict):
        return _empty()
    return {"version": body.get("version") or VERSION, "records": records}


def save(md, index):
    md.json_write(INDEX_FILE, {"version": index.get("version") or VERSION,
                                "records": index.get("records") or {}})


def upsert(md, record):
    """登记一条压缩记录；返回写入后的整份索引。"""
    index = load(md)
    index["records"][record["original"]] = record
    save(md, index)
    return index


def get(index, original):
    return (index.get("records") or {}).get(original)


def all_records(index):
    return list((index.get("records") or {}).values())


def remove(md, original):
    index = load(md)
    if index["records"].pop(original, None) is not None:
        save(md, index)
    return index


def query(index, category=None, older_than=None, limit=None, now_ts=None):
    """只读查询：按类别 / 年龄过滤，按压缩时间倒序，截断 limit。

    older_than 单位为天；返回条目带 ``status``：``archived`` 已压缩、``raw`` 未压缩。
    """
    records = all_records(index)
    days = float(older_than) if older_than is not None else None
    rows = []
    for rec in records:
        if category and rec.get("category") != category:
            continue
        if days is not None and now_ts is not None:
            created_ts = float(rec.get("created_ts") or 0)
            if created_ts and now_ts - created_ts < days * _policy.SECONDS_PER_DAY:
                continue
        rows.append(rec)
    rows.sort(key=lambda r: r.get("created") or "", reverse=True)
    if limit is not None:
        rows = rows[:int(limit)]
    return rows


def stats(index):
    """聚合观测：条数、原始 / 压缩字节、节省空间、按类别拆分。"""
    records = all_records(index)
    by_category: dict = {}
    orig_total = comp_total = 0
    for rec in records:
        cat = rec.get("category") or "unknown"
        bucket = by_category.setdefault(cat, {"count": 0, "orig_bytes": 0, "comp_bytes": 0})
        bucket["count"] += 1
        bucket["orig_bytes"] += int(rec.get("orig_size") or 0)
        bucket["comp_bytes"] += int(rec.get("comp_size") or 0)
        orig_total += int(rec.get("orig_size") or 0)
        comp_total += int(rec.get("comp_size") or 0)
    saved = orig_total - comp_total
    ratio = (comp_total / orig_total) if orig_total else 0.0
    return {
        "count": len(records),
        "orig_bytes": orig_total,
        "comp_bytes": comp_total,
        "saved_bytes": saved,
        "compression_ratio": round(ratio, 4),
        "by_category": by_category,
    }
