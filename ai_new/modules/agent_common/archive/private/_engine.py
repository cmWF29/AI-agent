"""压缩执行引擎：扫描候选 → 策略判定 → 原子压缩 → 校验 → 登记索引 → 清理临时。

职责边界：
- 压缩是写盘业务动作，只能由需求编排调用本模块的压缩路由；模块不在后台隐式压；
- 原始字节读取 / 临时文件 / 原子改名在本能力内完成；摘要问 codec，时间问 clock；
- 中途失败不留半截文件：临时文件必清理；压缩流先落临时再原子替换，校验通过才删原文。
"""
from __future__ import annotations

import os
import tempfile
import time
from pathlib import Path

from . import _backend, _cache, _index, _lock, _metrics, _policy

# 进程内单例缓存：跨路由调用复用解压结果；上限由配置给定。
_cache_instance: "_cache.LRUCache | None" = None
# 进程内单例时延记录器：解压耗时样本跨路由复用；容量由配置给定。
_metrics_instance: "_metrics.LatencyRecorder | None" = None


def _unlink_retry(path, attempts=8):
    """Windows 杀软/索引器短暂持有句柄时退避重试；最终失败仍抛出，不静默丢错。"""
    delay = 0.005
    for i in range(attempts):
        try:
            Path(path).unlink()
            return
        except FileNotFoundError:
            return
        except PermissionError:
            if os.name != "nt" or i + 1 >= attempts:
                raise
            time.sleep(delay)
            delay = min(delay * 2, 0.2)


def _cache_singleton(cfg):
    global _cache_instance
    if _cache_instance is None:
        _cache_instance = _cache.LRUCache(
            max_bytes=cfg.get("cache_max_bytes", 4 * 1024 * 1024),
            max_entries=cfg.get("cache_max_entries", 64))
    _cache_instance.configure(
        max_bytes=cfg.get("cache_max_bytes"),
        max_entries=cfg.get("cache_max_entries"))
    return _cache_instance


def _metrics_singleton(cfg):
    global _metrics_instance
    if _metrics_instance is None:
        _metrics_instance = _metrics.LatencyRecorder(
            max_samples=cfg.get("metrics_max_samples", _metrics.DEFAULT_MAX_SAMPLES))
    _metrics_instance.configure(max_samples=cfg.get("metrics_max_samples"))
    return _metrics_instance


def _config(ctx):
    return dict((ctx.cfg.get("archive") or {}))


def _modules_root(anchor):
    for parent in Path(anchor).resolve().parents:
        if parent.name == "modules":
            return parent
    raise ValueError("找不到 modules 根")


def _dir_of(module):
    """模块数据目录：与 store 同一套镜像规则（AI_NEW_DATA 覆盖时按组/模块平铺）。"""
    module = (module or "").strip("/").replace("\\", "/")
    external = os.environ.get("AI_NEW_DATA")
    rel = Path(*module.split("/")) if module else Path()
    if external:
        return Path(external) / rel
    return _modules_root(__file__) / rel / "data"


class ArchiveCorrupt(Exception):
    """压缩流损坏、校验和不匹配或索引缺失：不许静默返回坏数据。

    ``code`` 取值：``archive_corrupt`` 流损坏 / 校验和不符；
    ``archive_companion_missing`` 索引在而压缩流文件缺失；
    ``archive_index_missing`` 压缩流在而索引记录缺失。
    """

    def __init__(self, message: str, code: str = "archive_corrupt"):
        super().__init__(message)
        self.code = code


def _checksum(ctx, raw: bytes) -> str:
    out = ctx.api.call("codec.digest", {"text": raw, "algorithm": "sha256"}, caller=None)
    if not out.get("ok"):
        raise ArchiveCorrupt("摘要计算失败: %s" % out.get("error"))
    return out["hex"]


def scan(ctx, payload):
    """只读扫描：列出候选并给出冷热判定，不写盘。"""
    cfg = _config(ctx)
    now = ctx.api.call("clock.now", {}, caller=None)
    ts = now["ts"]
    entries = cfg.get("scan") or []
    categories = cfg.get("categories") or {}
    min_global = int(cfg.get("min_file_bytes") or 0)
    grace_default = float(cfg.get("grace_seconds") or 3600)

    candidates = []
    for entry in entries:
        module = entry.get("module") or ""
        category = entry.get("category") or ""
        pattern = entry.get("glob") or "**/*"
        root = _dir_of(module)
        if not root.is_dir():
            continue
        for item in sorted(root.rglob(pattern)):
            if not item.is_file() or policy_is_skipped(item.name):
                continue
            size = item.stat().st_size
            mtime = item.stat().st_mtime
            age = _policy.age_seconds(ts, mtime)
            threshold = dict(categories.get(category) or {})
            threshold.setdefault("grace_seconds", grace_default)
            ev = _policy.evaluate(
                {"size_bytes": size, "age_seconds": age, "category": category}, threshold)
            cold = ev["cold"]
            reason = ev["reason"]
            if size < min_global:
                cold, reason = False, "size_below"
            rel = item.relative_to(root).as_posix()
            candidates.append({
                "module": module,
                "rel": rel,
                "abs": str(item),
                "category": category,
                "layer": _layer(rel),
                "size_bytes": size,
                "age_seconds": round(age, 3),
                "cold": cold,
                "reason": reason,
            })

    cold = [c for c in candidates if c["cold"]]
    summary = {
        "scanned": len(candidates),
        "cold": len(cold),
        "cold_bytes": sum(c["size_bytes"] for c in cold),
    }
    return {"candidates": candidates, "summary": summary}


def policy_is_skipped(name):
    return _policy.is_skipped(name)


def _layer(rel: str) -> str:
    """归属层：public / project / ticket；按路径首段判定，缺省 public。"""
    parts = rel.split("/")
    if parts and parts[0] == "projects":
        return "project"
    if parts and parts[0] == "tickets":
        return "ticket"
    return "public"


def _cleanup_temp(parent: Path, stem: str):
    """清理同目录下本次压缩留下的临时文件；半截临时文件不许留存。"""
    for tmp in parent.glob(stem + ".*.tmp"):
        try:
            tmp.unlink()
        except OSError:
            pass


def _compress_one(ctx, abs_path: str, category: str, cfg: dict) -> dict:
    md = ctx.storage.own(__file__)
    index = _index.load(md)
    algo = cfg.get("algorithm") or "gzip"
    level = cfg.get("compress_level", 6)
    comp_path = abs_path + _backend.suffix_for(algo)

    rec0 = _index.get(index, abs_path)
    if rec0 and Path(rec0["compressed"]).is_file():
        return {"status": "skipped", "reason": "already_archived", "original": abs_path,
                "category": category}

    attempts = int(cfg.get("max_attempts") or 2)
    last_error = None
    for attempt in range(1, attempts + 1):
        tmp = None
        try:
            with _lock.source_lock(abs_path):
                raw = Path(abs_path).read_bytes()
                digest = _checksum(ctx, raw)
                comp = _backend.compress_bytes(raw, level=level, algorithm=algo)

                parent = Path(abs_path).parent
                fd, tmp = tempfile.mkstemp(dir=str(parent),
                                           prefix=Path(abs_path).name + ".", suffix=".tmp")
                try:
                    with os.fdopen(fd, "wb") as fh:
                        fh.write(comp["data"])
                    os.replace(tmp, comp_path)
                except BaseException:
                    if tmp and os.path.exists(tmp):
                        os.unlink(tmp)
                    raise

                # 校验：解压回原文一致 + 校验和匹配；不过就不留压缩流、不删原文。
                raw2 = _backend.decompress_bytes(Path(comp_path).read_bytes(), algo)
                if raw2 != raw:
                    raise ArchiveCorrupt("压缩回读与原文不一致")
                if _checksum(ctx, raw2) != digest:
                    raise ArchiveCorrupt("校验和不匹配")

            now = ctx.api.call("clock.now", {}, caller=None)
            record = {
                "original": abs_path,
                "compressed": comp_path,
                "module": _module_of(abs_path),
                "category": category,
                "layer": _layer(_rel_of(abs_path)),
                "orig_size": len(raw),
                "comp_size": len(comp["data"]),
                "algorithm": algo,
                "checksum": digest,
                "status": "archived",
                "created": now.get("iso", ""),
                "created_ts": now.get("ts", 0),
                "orig_mtime": Path(abs_path).stat().st_mtime,
            }
            _index.upsert(md, record)
            _unlink_retry(abs_path)
            _cleanup_temp(Path(abs_path).parent, Path(abs_path).name)
            return {"status": "compressed", "original": abs_path, "category": category,
                    "orig_size": record["orig_size"], "comp_size": record["comp_size"],
                    "algorithm": algo}
        except OSError as exc:
            last_error = exc
            if attempt < attempts:
                continue
        except Exception as exc:  # 损坏类错误不重试
            last_error = exc
            break
    return {"status": "failed", "original": abs_path, "category": category,
            "error": str(last_error)}


def _rel_of(abs_path: str) -> str:
    """绝对路径 → 相对 modules 根的路径（去掉 group/module/data 前缀）。"""
    root = _modules_root(__file__)
    try:
        rel = Path(abs_path).resolve().relative_to(root)
        parts = rel.parts
        return "/".join(parts[3:]) if len(parts) > 3 else ""
    except ValueError:
        return ""


def _module_of(abs_path: str) -> str:
    """从绝对路径反推 module 名（agent/logs 这种），供索引记录归属。"""
    root = _modules_root(__file__)
    try:
        rel = Path(abs_path).resolve().relative_to(root)
        return "/".join(rel.parts[:2])
    except ValueError:
        return ""


def _register_raw(md, candidate: dict):
    """把未压缩候选登记进索引（status=raw）；已归档条目不覆盖。"""
    abs_path = candidate.get("abs")
    if not abs_path:
        return
    index = _index.load(md)
    existing = _index.get(index, abs_path)
    if existing and existing.get("status") == "archived":
        return
    now = ctx_now(md)
    record = {
        "original": abs_path,
        "compressed": "",
        "module": candidate.get("module") or "",
        "category": candidate.get("category") or "unknown",
        "layer": candidate.get("layer") or "public",
        "orig_size": int(candidate.get("size_bytes") or 0),
        "comp_size": 0,
        "algorithm": "",
        "checksum": "",
        "status": "raw",
        "created": now["iso"],
        "created_ts": now["ts"],
        "orig_mtime": 0,
    }
    _index.upsert(md, record)


def ctx_now(md):
    now = md.ctx.api.call("clock.now", {}, caller=None)
    return {"ts": now["ts"], "iso": now["iso"]}


def compress(ctx, payload):
    """编排压缩：显式 paths 优先；否则压缩扫描判定为冷的全部候选。"""
    cfg = _config(ctx)
    scan_res = scan(ctx, payload)
    by_abs = {c["abs"]: c for c in scan_res["candidates"]}
    wanted = payload.get("paths") or [c["abs"] for c in scan_res["candidates"] if c["cold"]]
    md = ctx.storage.own(__file__)

    items, agg = [], {"orig": 0, "comp": 0}
    for abs_path in wanted:
        candidate = by_abs.get(abs_path, {})
        category = candidate.get("category") or payload.get("category") or "unknown"
        _register_raw(md, candidate)
        res = _compress_one(ctx, abs_path, category, cfg)
        items.append(res)
        if res["status"] == "compressed":
            agg["orig"] += int(res["orig_size"])
            agg["comp"] += int(res["comp_size"])

    summary = {
        "compressed": sum(1 for i in items if i["status"] == "compressed"),
        "skipped": sum(1 for i in items if i["status"] == "skipped"),
        "failed": sum(1 for i in items if i["status"] == "failed"),
        "orig_bytes": agg["orig"],
        "comp_bytes": agg["comp"],
        "saved_bytes": agg["orig"] - agg["comp"],
    }
    return {"items": items, "summary": summary}


# ---- 透明读：原始与压缩两种格式统一出口 ----

def _record_for(md, abs_path: str):
    index = _index.load(md)
    return _index.get(index, abs_path)


def resolve_abs(ctx, payload):
    """按绝对路径读原始字节：原文在就读原文；不在则按索引读压缩流并校验。

    返回 ``{exists, raw, cached}``；校验和不匹配 / 流损坏抛 ``ArchiveCorrupt``。
    """
    abs_path = Path(payload.get("abs") or "")
    if not str(abs_path):
        return {"exists": False, "raw": b"", "cached": False}
    cache = _cache_singleton(_config(ctx))
    key = str(abs_path)

    if abs_path.is_file():
        mtime = abs_path.stat().st_mtime
        cached = cache.get(key, mtime=mtime)
        if cached is not None:
            return {"exists": True, "raw": cached, "cached": True}
        raw = abs_path.read_bytes()
        cache.put(key, raw, mtime=mtime, size=len(raw))
        return {"exists": True, "raw": raw, "cached": False}

    md = ctx.storage.own(__file__)
    rec = _record_for(md, str(abs_path))
    comp_path = Path(rec["compressed"]) if rec else None
    if rec:
        if not (comp_path and comp_path.is_file()):
            # 索引在、压缩流不在：台账与磁盘脱节，按损坏类错误抛出，不静默当未归档。
            raise ArchiveCorrupt(
                "索引记录的压缩流缺失: %s" % str(abs_path),
                code="archive_companion_missing")
        mtime = comp_path.stat().st_mtime
        cached = cache.get(key, mtime=mtime)
        if cached is not None:
            return {"exists": True, "raw": cached, "cached": True}
        started = time.perf_counter()
        try:
            raw = _backend.decompress_bytes(comp_path.read_bytes(), rec["algorithm"])
        except Exception as exc:  # 流损坏 / 算法不符：包装成校验类错误，不静默返回
            raise ArchiveCorrupt("压缩流损坏: %s" % str(exc),
                                 code="archive_corrupt") from exc
        _metrics_singleton(_config(ctx)).record(time.perf_counter() - started)
        if _checksum(ctx, raw) != rec["checksum"]:
            raise ArchiveCorrupt("校验和不匹配: %s" % str(abs_path),
                                 code="archive_corrupt")
        cache.put(key, raw, mtime=mtime, size=len(raw))
        return {"exists": True, "raw": raw, "cached": False}

    # 索引无记录：若磁盘上仍挂着压缩流，说明索引缺失，按错误抛出而非静默返空。
    for suffix in (".gz", ".zst"):
        sibling = Path(str(abs_path) + suffix)
        if sibling.is_file():
            raise ArchiveCorrupt(
                "索引缺失：压缩流仍在磁盘上: %s" % str(sibling),
                code="archive_index_missing")
    return {"exists": False, "raw": b"", "cached": False}


def resolve_raw(ctx, module: str, rel: str):
    """按 (module, rel) 解析，转发到绝对路径出口。"""
    return resolve_abs(ctx, {"abs": str(_dir_of(module) / rel)})


def read_text(ctx, payload):
    res = resolve_raw(ctx, payload.get("module") or "", payload.get("path") or "")
    if not res["exists"]:
        return {"exists": False, "value": ""}
    return {"exists": True, "value": res["raw"].decode("utf-8", errors="replace"),
            "cached": res["cached"]}


def read_bytes(ctx, payload):
    res = resolve_raw(ctx, payload.get("module") or "", payload.get("path") or "")
    if not res["exists"]:
        return {"exists": False, "size": 0, "value": ""}
    import base64
    return {"exists": True, "size": len(res["raw"]),
            "value": base64.b64encode(res["raw"]).decode(), "cached": res["cached"]}


def read_lines(ctx, payload):
    """按行区间读：start/end/limit 裁剪；不解压整文件进多行列表之外的副本。"""
    res = resolve_raw(ctx, payload.get("module") or "", payload.get("path") or "")
    if not res["exists"]:
        return {"exists": False, "lines": [], "total": 0}
    lines = res["raw"].decode("utf-8", errors="replace").splitlines()
    start = payload.get("start")
    end = payload.get("end")
    limit = payload.get("limit")
    lo = int(start) if start is not None else 0
    window = lines[lo:]
    if end is not None:
        window = window[:int(end) - lo]
    if limit is not None:
        window = window[:int(limit)]
    return {"exists": True, "lines": window, "total": len(lines),
            "cached": res["cached"]}


def stats(ctx, payload=None):
    md = ctx.storage.own(__file__)
    index = _index.load(md)
    cache = _cache_singleton(_config(ctx))
    return {
        "index": _index.stats(index),
        "cache": cache.stats(),
        "backend": _backend.backend_info(),
        "lock": _lock.lock_capability(),
    }


def _messages(ctx):
    """模块文案台账：读不到就退化成空表，不阻断观测。"""
    md = ctx.storage.own(__file__)
    return md.yaml_read("messages.yaml", default={}) or {}


def metrics(ctx, payload=None):
    """观测面汇总：压缩台账 + 解压时延分位 + 缓存命中，全部由真实样本 / 台账计算。

    压缩量与节省空间来自索引台账（持久化真源）；解压 P50/P95 来自进程内
    真实计时样本；命中率来自 LRU 命中 / 未命中计数。样本不足时解压段显式
    标 ``insufficient_samples``，分位置空。
    """
    md = ctx.storage.own(__file__)
    index = _index.load(md)
    cache = _cache_singleton(_config(ctx))
    recorder = _metrics_singleton(_config(ctx))
    cap = cache.capacity()
    c = cache.stats()
    total = int(c["hits"]) + int(c["misses"])
    storage = _index.archived_summary(index)
    decompress = recorder.snapshot()
    msgs = _messages(ctx)
    if decompress["status"] == "insufficient_samples":
        decompress_note = (msgs.get("decompress_insufficient") or "").format(
            samples=decompress["samples"])
    else:
        decompress_note = msgs.get("decompress_ok") or ""
    labels = {
        "storage_empty": msgs.get("storage_empty") or "",
        "decompress_status": decompress_note,
        "hit_rate": msgs.get("hit_rate_none") or "" if total == 0 else "",
    }
    return {
        "storage": storage,
        "decompress": decompress,
        "cache": {
            "hits": int(c["hits"]),
            "misses": int(c["misses"]),
            "hit_rate": round(int(c["hits"]) / total, 4) if total else 0.0,
            "entries": int(c["entries"]),
            "max_entries": int(cap["max_entries"]),
            "bytes": int(c["bytes"]),
            "max_bytes": int(cap["max_bytes"]),
        },
        "labels": labels,
    }


def index_query(ctx, payload):
    """索引只读查询：按类别 / 年龄过滤，返回已压缩与未压缩两类条目。

    索引是同步清单的唯一真源；不在此另存云端清单。
    """
    md = ctx.storage.own(__file__)
    index = _index.load(md)
    now = ctx.api.call("clock.now", {}, caller=None)
    rows = _index.query(
        index,
        category=payload.get("category"),
        older_than=payload.get("older_than"),
        limit=payload.get("limit"),
        now_ts=now["ts"])
    out = []
    for rec in rows:
        out.append({
            "path": rec.get("original") or "",
            "module": rec.get("module") or "",
            "layer": rec.get("layer") or "public",
            "category": rec.get("category") or "",
            "status": rec.get("status") or "archived",
            "size_orig": int(rec.get("orig_size") or 0),
            "size_comp": int(rec.get("comp_size") or 0),
            "algorithm": rec.get("algorithm") or "",
            "checksum": rec.get("checksum") or "",
            "compressed_at": rec.get("created") or "",
        })
    return {"rows": out}
