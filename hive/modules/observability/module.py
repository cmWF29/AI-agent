"""日志维测模块：日志查询、事件流、指标计数。

它是只读观察者：订阅 `*` 做统计，不参与任何业务决策。
任何模块出问题，都能在这里看到“谁在什么时候发了什么事件、报了什么错”。
"""
from __future__ import annotations

import os
import time
from collections import Counter, deque

from ...kernel.api import Module
from ...kernel.config import path_of


class Observability(Module):
    name = "obs"

    def setup(self):
        self.topics = Counter()
        self.errors = deque(maxlen=200)
        self.samples = deque(maxlen=400)
        self.dirs = {
            "log": path_of(self.cfg, "observability.log_dir", "data/logs"),
            "events": os.path.join(path_of(self.cfg, "observability.log_dir", "data/logs"), "events.jsonl"),
        }
        self.bus.subscribe("*", self._on_event, name="obs.metrics")
        self.log.info("obs.ready", event_log=self.dirs["events"])

        self.api.route("GET", "/api/obs/logs")(self.logs)
        self.api.route("GET", "/api/obs/events")(self.events)
        self.api.route("GET", "/api/obs/metrics")(self.metrics)
        self.api.route("GET", "/api/obs/info")(self.info)
        self.api.route("POST", "/api/bus/publish")(self.publish)

    # ---------------- 事件统计 ----------------
    def _on_event(self, ev):
        topic = ev.get("topic", "-")
        self.topics[topic] += 1
        self.samples.append({"id": ev.get("id"), "topic": topic, "source": ev.get("source"), "t": ev.get("t")})
        payload = ev.get("payload") or {}
        if isinstance(payload, dict):
            if "error" in payload or topic.endswith(".error") or topic.endswith(".exception"):
                self.errors.append({"t": ev.get("t"), "topic": topic, "error": str(payload.get("error"))[:300],
                                    "session": payload.get("session")})

    # ---------------- API ----------------
    def logs(self, payload):
        limit = min(int(payload.get("limit") or 100), 500)
        level = payload.get("level") or None
        contains = payload.get("contains") or None
        return {"items": self.log.recent(limit=limit, level=level, contains=contains), "stats": self.log.stats()}

    def events(self, payload):
        limit = min(int(payload.get("limit") or 100), 500)
        topic = payload.get("topic")
        items = list(self.bus.recent)
        if topic:
            items = [i for i in items if topic in (i.get("topic") or "")]
        return {"items": list(reversed(items))[:limit], "total": len(self.bus.recent)}

    def metrics(self, payload):
        return {
            "topics": self.topics.most_common(30),
            "errors": list(self.errors)[-20:],
            "bus": self.bus.stats(),
            "llm": dict(self.ctx.state["llm"].usage, model=self.ctx.state["llm"].model),
            "uptime_sec": int(time.time() - (self.ctx.state["http"].started_at or time.time())) if self.ctx.state.get("http") else 0,
        }

    def publish(self, payload):
        topic = payload.get("topic")
        if not topic:
            from ...kernel.api import ApiError
            raise ApiError("topic 必填", code="missing_topic")
        ev = self.bus.publish(topic, payload.get("payload") or {}, source=payload.get("source") or "http")
        return {"event": ev}

    def info(self, payload):
        kernel = self.ctx.state.get("kernel")
        return {
            "modules": self.ctx.router.module_names(),
            "routes": self.ctx.router.list(),
            "subscriptions": self.bus.subscriptions(),
            "status": kernel.status() if kernel else {},
        }
