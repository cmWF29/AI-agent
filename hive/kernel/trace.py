"""全链路追踪（需求 19：对 agent 开发者/运维完全透明）。

记录四类东西，按“会话”落盘，网页按 session / ticket 过滤直接看：
  * llm.request   —— 发给大模型的完整请求结构（模型、消息、工具、参数；key 永不落盘）
  * llm.response  —— 回来的原文（content / tool_calls / usage / 延迟）
  * tool.call     —— 模型下发的工具调用参数
  * tool.result   —— agent 拼回上下文的内容（含落盘路径与字数）
  * api.call      —— 模块之间走对外 API 的通信（谁 -> 哪条路由 -> 入参出参摘要）
  * bus.event     —— 总线上广播了什么（topic/payload 摘要）
  * agent.message —— agent 之间（PM -> 角色）的消息原文

存储：data/traces/<session>.jsonl（单文件 8MB 上限，超了滚成 .1），另有 _global.jsonl。
内存里保留最近 800 条供网页“最近事件”秒开。
"""
from __future__ import annotations

import json
import os
import re
import threading
import time
from collections import deque

from .config import path_of
from .store import ensure_dir

MAX_FILE_BYTES = 8 * 1024 * 1024
TRUNC = 1200
_SECRET_KEY = re.compile(r"(?i)(api[_-]?key|authorization|token|secret|password|cookie)")
_SECRET_VAL = re.compile(r"(sk-[A-Za-z0-9_-]{12,}|Bearer\s+[A-Za-z0-9._-]{16,}|(?i:token=)[A-Za-z0-9._-]{12,})")


def _scrub(text):
    return _SECRET_VAL.sub("[redacted]", text)


def _clip(value, n=TRUNC):
    """把任意结构压成“可读、可存”的短形态，避免 trace 把磁盘吃光。"""
    def walk(v, depth=0):
        if depth > 4:
            return "..."
        if isinstance(v, str):
            v = _scrub(v)
            return v if len(v) <= n else v[:n] + "...(%d字)" % len(v)
        if isinstance(v, dict):
            return {(k if not _SECRET_KEY.search(str(k)) else str(k) + "_redacted"): "[redacted]"
                    if _SECRET_KEY.search(str(k)) else walk(val, depth + 1)
                    for k, val in list(v.items())[:24]}
        if isinstance(v, (list, tuple)):
            return [walk(x, depth + 1) for x in list(v)[:16]]
        return v
    try:
        return walk(value)
    except Exception:
        return repr(value)[:n]


class Trace:
    def __init__(self, cfg, log=None):
        self.root = ensure_dir(path_of(cfg, "trace.root", "data/traces"))
        self.enabled = bool((cfg.get("trace") or {}).get("enabled", True))
        self.lock = threading.Lock()
        self.ring = deque(maxlen=int((cfg.get("trace") or {}).get("ring", 800)))
        self.log = log
        self.counters = {}

    def record(self, kind, data, session="", ticket=""):
        if not self.enabled:
            return
        ev = {
            "t": round(time.time(), 3),
            "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "kind": kind,
            "session": session or "",
            "ticket": ticket or "",
            "data": _clip(data),
        }
        with self.lock:
            self.ring.append(ev)
            self.counters[kind] = self.counters.get(kind, 0) + 1
            name = ("_global" if not session else session) + ".jsonl"
            path = os.path.join(self.root, name)
            try:
                if os.path.exists(path) and os.path.getsize(path) > MAX_FILE_BYTES:
                    os.replace(path, path + ".1")
                with open(path, "a", encoding="utf-8") as f:
                    f.write(json.dumps(ev, ensure_ascii=False) + "\n")
            except OSError as exc:
                if self.log:
                    self.log.warn("trace.write.failed", error=repr(exc))

    # ---------------- 查询 ----------------
    def recent(self, session="", ticket="", kinds=None, limit=200):
        limit = min(int(limit or 200), 800)
        kinds = set(kinds or [])
        with self.lock:
            items = list(self.ring)
        out = []
        for ev in reversed(items):
            if session and ev.get("session") != session:
                continue
            if ticket and ev.get("ticket") != ticket:
                continue
            if kinds and ev.get("kind") not in kinds:
                continue
            out.append(ev)
            if len(out) >= limit:
                break
        return list(reversed(out))

    def read_file(self, session, limit=400, kinds=None):
        """从磁盘读某会话的完整链路（进程重启后内存 ring 没了，但文件还在）。"""
        path = os.path.join(self.root, (session or "_global") + ".jsonl")
        if not os.path.exists(path):
            return []
        kinds = set(kinds or [])
        items = []
        try:
            with open(path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        ev = json.loads(line)
                    except ValueError:
                        continue
                    if kinds and ev.get("kind") not in kinds:
                        continue
                    items.append(ev)
        except OSError:
            return []
        return items[-min(int(limit or 400), 2000):]

    def stats(self):
        files = 0
        bytes_total = 0
        try:
            for name in os.listdir(self.root):
                p = os.path.join(self.root, name)
                if os.path.isfile(p):
                    files += 1
                    bytes_total += os.path.getsize(p)
        except OSError:
            pass
        return {"root": self.root, "files": files, "bytes": bytes_total,
                "counters": dict(self.counters), "enabled": self.enabled}
