"""极简持久化：原子写 JSON 文件 + 目录集合。

所有模块各自持有自己的 store 实例，互不越界读写别人的目录。
"""
from __future__ import annotations

import json
import os
import re
import threading
import time

_SAFE_ID = re.compile(r"[^A-Za-z0-9_.\-]")
_ID_RE = re.compile(r"^[A-Za-z0-9_\-\u4e00-\u9fff]{1,64}$")


def valid_id(value):
    """项目/工单/库 id 的严格白名单：不允许点号、斜杠，避免路径逃逸。"""
    s = str(value or "")
    return bool(_ID_RE.match(s)) and s not in (".", "..")


def safe_id(value):
    s = str(value)
    s = _SAFE_ID.sub("_", s)
    return s[:120] or "unnamed"


def ensure_dir(path):
    os.makedirs(path, exist_ok=True)
    return path


def inside(base, target):
    """判断 target 是否真的在 base 目录内（防止 `/a/b` 被 `/a/bc` 前缀绕过）。"""
    base = os.path.realpath(base)
    target = os.path.realpath(target)
    return target == base or target.startswith(base + os.sep)


def ts():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def now_epoch():
    return int(time.time())


def atomic_write_json(path, obj):
    ensure_dir(os.path.dirname(path))
    tmp = "%s.%d.tmp" % (path, int(time.time() * 1000) % 100000)
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def read_json(path, default=None):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return default
    except (ValueError, OSError):
        return default


class JsonDoc:
    """单文件 JSON 文档，带进程内锁。"""

    def __init__(self, path, default=None):
        self.path = path
        self._default = default if default is not None else {}
        self._lock = threading.RLock()
        ensure_dir(os.path.dirname(path))

    def read(self):
        with self._lock:
            data = read_json(self.path, None)
            if data is None:
                data = json.loads(json.dumps(self._default))
                atomic_write_json(self.path, data)
            return data

    def write(self, obj):
        with self._lock:
            atomic_write_json(self.path, obj)
            return obj

    def update(self, fn):
        with self._lock:
            data = self.read()
            fn(data)
            return self.write(data)


class Collection:
    """目录式集合：一个 id 一个 json 文件。"""

    def __init__(self, directory, default=None):
        self.dir = ensure_dir(directory)
        self._default = default if default is not None else {}
        # 同一集合的写操作串行化：HTTP 线程 / 空闲线程 / 工单线程可能同时写
        self._lock = threading.RLock()

    def path(self, item_id):
        return os.path.join(self.dir, safe_id(item_id) + ".json")

    def exists(self, item_id):
        return os.path.exists(self.path(item_id))

    def get(self, item_id, default=None):
        return read_json(self.path(item_id), default)

    def put(self, item_id, obj):
        with self._lock:
            atomic_write_json(self.path(item_id), obj)
        return obj

    def delete(self, item_id):
        with self._lock:
            try:
                os.remove(self.path(item_id))
                return True
            except FileNotFoundError:
                return False

    def list(self):
        out = []
        with self._lock:
            names = sorted(os.listdir(self.dir))
        for name in names:
            if not name.endswith(".json"):
                continue
            obj = read_json(os.path.join(self.dir, name), None)
            if isinstance(obj, dict):
                obj.setdefault("id", name[:-5])
                out.append(obj)
        return out

    def ids(self):
        return [n[:-5] for n in sorted(os.listdir(self.dir)) if n.endswith(".json")]


class AppendLog:
    """按行追加的 JSONL 日志，超过大小自动轮转一次。"""

    def __init__(self, path, max_bytes=64 * 1024 * 1024):
        self.path = path
        self.max_bytes = max_bytes
        ensure_dir(os.path.dirname(path))
        self._lock = threading.Lock()

    def append(self, obj):
        line = json.dumps(obj, ensure_ascii=False) + "\n"
        with self._lock:
            try:
                if self.max_bytes and os.path.exists(self.path) and os.path.getsize(self.path) > self.max_bytes:
                    os.replace(self.path, self.path + ".1")
            except OSError:
                pass
            with open(self.path, "a", encoding="utf-8") as f:
                f.write(line)
        return line

    def tail(self, limit=100, offset=0):
        if not os.path.exists(self.path):
            return []
        with self._lock:
            with open(self.path, "r", encoding="utf-8") as f:
                lines = f.readlines()
        items = []
        for line in reversed(lines):
            line = line.strip()
            if not line:
                continue
            try:
                items.append(json.loads(line))
            except ValueError:
                continue
            if len(items) >= limit + offset:
                break
        return items[offset:offset + limit]
