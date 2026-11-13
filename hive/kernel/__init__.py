"""Hive 内核：把各个独立部件装配成一个可运行的服务。

装配顺序 = 依赖注入，不是依赖关系：
  config -> logger -> bus -> tools/output/llm/react -> modules -> http
模块只拿到 Context，彼此之间不允许直接引用。
"""
from __future__ import annotations

import os
import signal
import sys
import time

from .api import Context
from .bus import Bus
from .config import load_config, path_of, resolve
from .http import HttpService
from .llm import LLMClient
from .logger import Logger
from .output import OutputPolicy
from .react import ReactLoop
from .store import ensure_dir, ts
from .tools import ToolRegistry
from .trace import Trace


class Kernel:
    def __init__(self, config_path=None, cfg=None, web_dir=None):
        self.cfg = cfg or load_config(config_path)
        self.root = self.cfg["root"]
        self._stopping = False

        log_dir = resolve(self.cfg, "observability.log_dir")
        ensure_dir(log_dir)
        self.log = Logger(
            log_dir,
            level=self.cfg["observability"].get("level", "info")
            if isinstance(self.cfg["observability"], dict) else "info",
            name="hive",
            buffer=int(self.cfg["observability"].get("event_buffer", 500)),
        )

        self.bus = Bus(
            name="hive",
            workers=int(self.cfg["bus"].get("workers", 4)),
            log_path=os.path.join(log_dir, "events.jsonl"),
            buffer=int(self.cfg["observability"].get("event_buffer", 500)),
        )
        self.bus.error_handler = self._on_bus_error

        self.tools = ToolRegistry(self.cfg)
        self.output = OutputPolicy(self.cfg)
        self.llm = LLMClient(self.cfg)
        self.trace = Trace(self.cfg, log=self.log)
        self.bus.trace = self.trace
        self.ctx = Context(self.cfg, self.bus, self.log)
        self.ctx.tools = self.tools
        self.ctx.trace = self.trace
        self.ctx.started_at = ts()

        self.react = ReactLoop(self.cfg, self.bus, self.log, self.llm, self.tools, self.output,
                               api=self.ctx.api, trace=self.trace)
        self.ctx.state.update({
            "react": self.react,
            "llm": self.llm,
            "output": self.output,
            "tools": self.tools,
            "trace": self.trace,
            "kernel": self,
        })

        self.http = HttpService(self.cfg, self.ctx.router, self.log, web_dir=web_dir)
        self.ctx.state["http"] = self.http
        self._modules = []

    def _on_bus_error(self, info):
        self.log.error("bus.handler.error", **info)

    # ---------------- 生命周期 ----------------
    def boot(self):
        from hive.modules import build_modules
        for module in build_modules(self.ctx):
            self.ctx.register(module)
            self._modules.append(module)
        self.log.info("kernel.boot", root=self.root, modules=[m.name for m in self._modules])
        self.bus.publish("kernel.boot", {"modules": [m.name for m in self._modules]}, source="kernel")
        return self

    def start_http(self):
        self.http.start_background()
        self.log.info("kernel.http.started", url=self.http.url(), token_hint="见 config.server.token")
        return self

    def run_forever(self, block=True):
        if block:
            self.log.info("kernel.running", pid=os.getpid(), url=self.http.url())
            try:
                while not self._stopping:
                    time.sleep(0.5)
            except KeyboardInterrupt:
                self.log.info("kernel.keyboard_interrupt")
        return self

    def stop(self):
        if self._stopping:
            return
        self._stopping = True
        self.log.info("kernel.stop.begin")
        try:
            self.http.stop()
        except Exception:
            pass
        self.ctx.shutdown()
        self.tools.shutdown()
        self.bus.publish("kernel.stop", {}, source="kernel")
        self.bus.wait_idle(2.0)
        self.bus.shutdown()
        self.log.info("kernel.stop.done")

    def install_signals(self):
        def _handler(signum, frame):
            self.log.info("kernel.signal", signum=signum)
            self.stop()
            sys.exit(0)
        for sig in (signal.SIGTERM, signal.SIGINT):
            try:
                signal.signal(sig, _handler)
            except (ValueError, OSError):
                pass

    # ---------------- 状态 ----------------
    def status(self):
        return {
            "pid": os.getpid(),
            "root": self.root,
            "config": self.cfg.get("config_path"),
            "started_at": self.ctx.started_at,
            "uptime_sec": int(time.time() - self.http.started_at) if self.http.started_at else 0,
            "modules": [m.name for m in self._modules],
            "routes": len(self.ctx.router.list()),
            "bus": self.bus.stats(),
            "llm": dict(self.llm.usage, model=self.llm.model, base_url=self.llm.base_url, has_key=bool(self.llm.api_key)),
            "tool_output": self.output.stats(),
        }
