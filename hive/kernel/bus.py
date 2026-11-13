"""事件总线：模块之间唯一的进程内通信通道。

约束（整个项目的架构铁律）：
  * 模块之间不互相 import，只通过 ①事件总线 ②HTTP API 通信。
  * 事件名用点号分层，例如 ticket.created / session.compacted / tool.end。
  * 订阅支持精确匹配与 `前缀.*` 通配。
"""
from __future__ import annotations

import threading
import time
from collections import defaultdict, deque
from concurrent.futures import ThreadPoolExecutor

from .store import AppendLog, ts


def topic_matches(pattern, topic):
    if pattern == "*" or pattern == topic:
        return True
    if pattern.endswith(".*"):
        prefix = pattern[:-1]           # 保留结尾的点
        return topic.startswith(prefix) or topic == pattern[:-2]
    return False


class Bus:
    def __init__(self, name="bus", workers=4, log_path=None, buffer=500, max_log_bytes=64 * 1024 * 1024):
        self.name = name
        self._lock = threading.RLock()
        self._subs = {}
        self._sub_seq = 0
        self._ev_seq = 0
        self._pool = ThreadPoolExecutor(max_workers=max(1, workers), thread_name_prefix="bus")
        self._pending = 0
        self._idle = threading.Condition(self._lock)
        self.recent = deque(maxlen=buffer)
        self.counters = defaultdict(int)
        self.log = AppendLog(log_path, max_log_bytes) if log_path else None
        self.error_handler = None      # 由 observability 模块注入
        self.trace = None              # 由 kernel 注入：总线事件也要可视化
        self.started_at = ts()

    # ---------------- 订阅 ----------------
    def subscribe(self, pattern, handler, name=""):
        with self._lock:
            self._sub_seq += 1
            sid = "sub-%d" % self._sub_seq
            self._subs[sid] = {"pattern": pattern, "handler": handler, "name": name}
            return sid

    def unsubscribe(self, sid):
        with self._lock:
            return self._subs.pop(sid, None) is not None

    def subscriptions(self):
        with self._lock:
            return [{"id": k, "pattern": v["pattern"], "name": v["name"]} for k, v in self._subs.items()]

    # ---------------- 发布 ----------------
    def _dispatch(self, ev):
        with self._lock:
            targets = [(sid, s) for sid, s in self._subs.items() if topic_matches(s["pattern"], ev["topic"])]
        for sid, sub in targets:
            yield sid, sub

    def publish(self, topic, payload=None, source="", sync=False):
        with self._lock:
            self._ev_seq += 1
            ev = {
                "id": self._ev_seq,
                "topic": topic,
                "payload": payload if payload is not None else {},
                "source": source,
                "ts": ts(),
                "t": round(time.time(), 3),
            }
            self.counters[topic] += 1
            self.recent.append(ev)
        if self.log:
            try:
                self.log.append(ev)
            except OSError:
                pass
        self._trace(ev)
        for sid, sub in self._dispatch(ev):
            if sync:
                self._run_handler(sub, ev, sid)
            else:
                with self._lock:
                    self._pending += 1
                self._pool.submit(self._run_handler_async, sub, ev, sid)
        return ev

    def _trace(self, ev):
        """总线上广播了什么，也进 trace（llm.delta 这种高频事件只记一条摘要，避免刷盘）。"""
        trace = self.trace
        if trace is None:
            return
        try:
            payload = ev.get("payload") or {}
            if ev["topic"] == "llm.delta":
                return
            trace.record("bus.event", {
                "topic": ev["topic"], "source": ev.get("source"),
                "payload": payload,
            }, session=payload.get("session") or "", ticket=payload.get("ticket") or "")
        except Exception:
            pass

    def _run_handler(self, sub, ev, sid):
        try:
            sub["handler"](ev)
        except Exception as exc:                      # 单个订阅者的异常不能拖垮总线
            if self.error_handler:
                try:
                    self.error_handler({"sub": sid, "pattern": sub["pattern"], "topic": ev["topic"], "error": repr(exc)})
                except Exception:
                    pass

    def _run_handler_async(self, sub, ev, sid):
        try:
            self._run_handler(sub, ev, sid)
        finally:
            with self._lock:
                self._pending -= 1
                if self._pending <= 0:
                    self._idle.notify_all()

    def wait_idle(self, timeout=5.0):
        """等本轮事件全部处理完（测试与优雅退出用）。"""
        end = time.time() + timeout
        with self._lock:
            while self._pending > 0 and time.time() < end:
                self._idle.wait(end - time.time())
            return self._pending == 0

    def stats(self):
        return {
            "name": self.name,
            "events": self._ev_seq,
            "pending": self._pending,
            "subscribers": len(self._subs),
            "top_topics": sorted(self.counters.items(), key=lambda kv: -kv[1])[:10],
            "started_at": self.started_at,
        }

    def shutdown(self):
        try:
            self._pool.shutdown(wait=False, cancel_futures=True)   # py3.9+
        except TypeError:                                          # py3.8 没有这个参数
            self._pool.shutdown(wait=False)
