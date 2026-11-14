"""健康检查模块：给 watchdog 一个“敢不敢信你”的依据。

/api/health      轻量存活（供外部探活）
/api/health/self 深度自检（供 watchdog 判定是否要重启/回退）
"""
from __future__ import annotations

import os
import shutil
import time

from ...kernel.api import Module
from ...kernel.store import ensure_dir
from ...version import __version__

REQUIRED_MODULES = ["obs", "knowledge", "memory", "library", "artifacts", "projects",
                    "toolpack", "sessions", "gitflow", "tickets", "webchat"]


def _human(n):
    n = int(n or 0)
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return ("%d %s" % (n, unit)) if unit == "B" else ("%.1f %s" % (n, unit))
        n /= 1024.0
    return "%d B" % n


class Health(Module):
    name = "health"

    def setup(self):
        self.boot_ts = time.time()
        self.heartbeat = 0
        self.api.route("GET", "/api/health", auth=False)(self.health)
        self.api.route("GET", "/api/health/self", auth=False)(self.self_check)
        self.api.route("GET", "/api/health/traffic", name="traffic")(self.traffic_api)
        self.api.route("GET", "/api/health/logs", name="logs")(self.logs_api)
        self.bus.subscribe("*", lambda ev: None, name="health.heartbeat")
        self.log.info("health.ready")

    def health(self, payload):
        return {
            "status": "ok",
            "version": __version__,
            "pid": os.getpid(),
            "uptime_sec": int(time.time() - self.boot_ts),
        }

    def self_check(self, payload):
        checks = []

        def add(name, ok, critical=True, detail=""):
            checks.append({"name": name, "ok": bool(ok), "critical": bool(critical), "detail": detail})

        # 1) 数据目录可写
        try:
            d = ensure_dir(os.path.join(self.cfg["root"], "data", "health"))
            probe = os.path.join(d, "probe-%d.tmp" % int(time.time() * 1000))
            with open(probe, "w", encoding="utf-8") as f:
                f.write("ok")
            os.remove(probe)
            add("data_writable", True, True, d)
        except OSError as exc:
            add("data_writable", False, True, repr(exc))

        # 2) 模块齐全
        missing = [m for m in REQUIRED_MODULES if m not in self.ctx.modules]
        add("modules_loaded", not missing, True, "missing=" + ",".join(missing) if missing else "all")

        # 3) 三个核心 API 可响应
        for route in ("sessions.list", "tickets.list", "knowledge.overview",
                      "library.summary", "artifacts.stats", "projects.list"):
            try:
                self.ctx.api(route)
                add("api_" + route.replace(".", "_"), True, True, route)
            except Exception as exc:
                add("api_" + route.replace(".", "_"), False, True, repr(exc))

        # 4) 总线可用
        try:
            stats = self.bus.stats()
            add("bus", True, True, "subs=%s pending=%s" % (stats["subscribers"], stats["pending"]))
        except Exception as exc:
            add("bus", False, True, repr(exc))

        # 5) 磁盘余量
        try:
            free = shutil.disk_usage(self.cfg["root"]).free
            add("disk_free", free > 200 * 1024 * 1024, False, "%dMB" % (free // (1024 * 1024)))
        except OSError as exc:
            add("disk_free", False, False, repr(exc))

        # 6) 交付件体积 + 压缩情况（需求 20）
        try:
            art = self.ctx.api("artifacts.stats")
            total = art.get("total_bytes", 0)
            add("artifacts_size", True, False, "%s（压缩 %d 个工单）" % (art.get("total_human"), art.get("compressed", 0)))
            add("artifacts_disk_headroom", total < 200 * 1024 * 1024, False,
                "交付件 %dMB；超过 200MB 建议开压缩" % (total // (1024 * 1024)))
            self._artifacts = art
        except Exception as exc:
            add("artifacts_size", False, False, repr(exc))

        # 7) trace 落盘情况（透明化要能查）
        try:
            tr = self.ctx.state["trace"].stats()
            add("trace", True, False, "%d 文件 / %dKB" % (tr["files"], tr["bytes"] // 1024))
        except Exception as exc:
            add("trace", False, False, repr(exc))

        # 7.5) 网页流量 + 消息链路日志
        try:
            http = self.ctx.state.get("http")
            counters = dict(http.counters) if http else {}
            add("http_traffic", True, False,
                "请求 %d（API %d / 静态 %d）· 收 %s / 发 %s" % (
                    counters.get("requests", 0), counters.get("api_requests", 0),
                    counters.get("static_requests", 0),
                    _human(counters.get("bytes_in", 0)), _human(counters.get("bytes_out", 0))))
            self._counters = counters
        except Exception as exc:
            add("http_traffic", False, False, repr(exc))

        # 8) LLM 配置（缺 key 只降级，不算致命：网页仍可打开）
        llm = self.ctx.state.get("llm")
        add("llm_key", bool(llm and llm.api_key), False, "model=%s" % (llm.model if llm else "-"))

        critical_failed = [c for c in checks if c["critical"] and not c["ok"]]
        healthy = not critical_failed
        return {
            "healthy": healthy,
            "status": "ok" if healthy else "degraded",
            "version": __version__,
            "pid": os.getpid(),
            "uptime_sec": int(time.time() - self.boot_ts),
            "checks": checks,
            "artifacts": getattr(self, "_artifacts", {}),
            "tls": bool(self.ctx.state.get("http") and self.ctx.state["http"].scheme == "https"),
            "traffic": getattr(self, "_counters", {}),
            "failed": [c["name"] for c in critical_failed],
        }


    def traffic_api(self, payload):
        http = self.ctx.state.get("http")
        counters = dict(http.counters) if http else {}
        return {"traffic": counters, "scheme": getattr(http, "scheme", ""), "port": getattr(http, "port", 0),
                "human": {"in": _human(counters.get("bytes_in", 0)),
                          "out": _human(counters.get("bytes_out", 0))}}

    def logs_api(self, payload):
        limit = max(10, min(int(payload.get("limit") or 80), 300))
        items = self.ctx.log.recent(limit=limit)
        bus_items = []
        try:
            skip = ("llm.delta", "session.hook", "react.step")
            for ev in list(getattr(self.bus, "recent", []))[-limit * 3:]:
                topic = str(ev.get("topic") or "")
                if any(topic.startswith(x) for x in skip):
                    continue
                bus_items.append({"t": ev.get("t") or 0, "ts": ev.get("ts") or "",
                                  "level": "info", "event": "bus." + topic,
                                  "source": ev.get("source") or ""})
        except Exception:
            pass
        return {"items": items, "bus_items": bus_items, "stats": self.ctx.log.stats(),
                "bus": self.bus.stats() if hasattr(self.bus, "stats") else {}}
