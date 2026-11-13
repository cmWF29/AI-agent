"""结构化日志：一行一个 JSON，便于 grep / 事后定位。

只写自己的日志目录，不做轮转分析（那是 observability 模块的事）。
"""
from __future__ import annotations

import json
import os
import threading
import time
import traceback
from collections import deque

LEVELS = {"debug": 10, "info": 20, "warning": 30, "error": 40}


class Logger:
    def __init__(self, log_dir, level="info", name="hive", buffer=300):
        self.dir = log_dir
        self.name = name
        self.level_value = LEVELS.get(level, 20)
        self._lock = threading.Lock()
        self._buf = deque(maxlen=buffer)
        os.makedirs(log_dir, exist_ok=True)

    def _path(self):
        return os.path.join(self.dir, "agent-%s.jsonl" % time.strftime("%Y%m%d"))

    def _write(self, level, event, fields):
        if LEVELS.get(level, 20) < self.level_value:
            return
        rec = {
            "t": round(time.time(), 3),
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime()),
            "level": level,
            "event": event,
        }
        if fields:
            rec.update(fields)
        with self._lock:
            self._buf.append(rec)
            try:
                with open(self._path(), "a", encoding="utf-8") as f:
                    f.write(json.dumps(rec, ensure_ascii=False, default=str) + "\n")
            except OSError:
                pass

    def debug(self, event, **fields):
        self._write("debug", event, fields)

    def info(self, event, **fields):
        self._write("info", event, fields)

    def warn(self, event, **fields):
        self._write("warning", event, fields)

    def error(self, event, **fields):
        self._write("error", event, fields)

    def exc(self, event, **fields):
        fields.setdefault("traceback", traceback.format_exc())
        self._write("error", event, fields)

    def recent(self, limit=100, level=None, contains=None):
        with self._lock:
            items = list(self._buf)
        if level:
            minv = LEVELS.get(level, 0)
            items = [i for i in items if LEVELS.get(i.get("level"), 0) >= minv]
        if contains:
            items = [i for i in items if contains in json.dumps(i, ensure_ascii=False)]
        return list(reversed(items))[:limit]

    def stats(self):
        return {"file": self._path(), "buffered": len(self._buf), "level": self.level_value}
