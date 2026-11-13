"""健康检查模块：给 watchdog 一个“敢不敢信你”的依据。

/api/health      轻量存活（供外部探活）
/api/health/self 深度自检（供 watchdog 判定是否要重启/回退）
"""
from __future__ import annotations

import os
import shutil
import time

from ..kernel.api import Module
from ..kernel.store import ensure_dir
from ..version import __version__

REQUIRED_MODULES = ["obs", "knowledge", "memory", "toolpack", "sessions", "tickets", "webchat", "ops"]


class Health(Module):
    name = "health"

    def setup(self):
        self.boot_ts = time.time()
        self.heartbeat = 0
        self.api.route("GET", "/api/health", auth=False)(self.health)
        self.api.route("GET", "/api/health/self", auth=False)(self.self_check)
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
        for route in ("sessions.list", "tickets.list", "knowledge.overview"):
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

        # 6) LLM 配置（缺 key 只降级，不算致命：网页仍可打开）
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
            "failed": [c["name"] for c in critical_failed],
        }
