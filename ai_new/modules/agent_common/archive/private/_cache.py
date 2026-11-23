"""解压缓存：内存字节上限 + 条目上限 + LRU 淘汰。

键为 ``(module, rel)``；值为解压后的原始字节。缓存只放已解压内容，
不缓存压缩流。淘汰按最近访问顺序：最久未访问的先出。
"""
from __future__ import annotations

import threading
from collections import OrderedDict


class LRUCache:
    def __init__(self, max_bytes=4 * 1024 * 1024, max_entries=64):
        self._max_bytes = int(max_bytes or 0)
        self._max_entries = int(max_entries or 0)
        self._data: "OrderedDict[tuple, dict]" = OrderedDict()
        self._bytes = 0
        self._lock = threading.Lock()
        self._stats = {"hits": 0, "misses": 0, "evictions": 0,
                       "bytes": 0, "entries": 0}

    def get(self, key, mtime=None, size=None):
        with self._lock:
            entry = self._data.get(key)
            if entry is None:
                self._stats["misses"] += 1
                return None
            # 一致性：文件 mtime 变了，缓存条目作废，不算命中（尺寸仅作条目记账）。
            if mtime is not None and entry["mtime"] != mtime:
                self._data.pop(key)
                self._bytes -= entry["size"]
                self._stats["misses"] += 1
                self._stats["evictions"] += 1
                return None
            self._data.move_to_end(key)
            self._stats["hits"] += 1
            return entry["data"]

    def put(self, key, data: bytes, mtime=None, size=None):
        data = bytes(data)
        with self._lock:
            if key in self._data:
                self._bytes -= self._data[key]["size"]
                self._data.pop(key)
            self._data[key] = {"mtime": mtime, "size": len(data), "data": data}
            self._bytes += len(data)
            self._evict()
            self._refresh_stats()

    def _evict(self):
        """按 LRU 淘汰到两条上限之内；调用方持锁。"""
        while self._data and self._over_capacity():
            _, old = self._data.popitem(last=False)
            self._bytes -= old["size"]
            self._stats["evictions"] += 1

    def _over_capacity(self) -> bool:
        if self._max_entries and len(self._data) > self._max_entries:
            return True
        if self._max_bytes and self._bytes > self._max_bytes:
            return True
        return False

    def _refresh_stats(self):
        self._stats["bytes"] = self._bytes
        self._stats["entries"] = len(self._data)

    def stats(self):
        with self._lock:
            return dict(self._stats)

    def capacity(self):
        """容量档位上报：条目上限与字节上限，供观测面展示命中率分母。"""
        with self._lock:
            return {"max_entries": self._max_entries, "max_bytes": self._max_bytes}

    def configure(self, max_bytes=None, max_entries=None):
        with self._lock:
            if max_bytes is not None:
                self._max_bytes = int(max_bytes)
            if max_entries is not None:
                self._max_entries = int(max_entries)
            self._evict()
            self._refresh_stats()
