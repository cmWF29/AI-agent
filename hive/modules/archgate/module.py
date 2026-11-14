"""架构门禁模块：对外提供唯一门禁入口。

CLI `python -m hive.archscan` 仍然保留给 pre-receive 兜底；
运行中的 agent 通过 `/api/gate/arch` 走同一套扫描器。
"""
from __future__ import annotations

from ...kernel.api import Module


class ArchGate(Module):
    name = "archgate"

    def setup(self):
        self.api.route("GET", "/api/gate/arch", name="arch")(self.arch)
        self.log.info("archgate.ready")

    def arch(self, payload):
        from ...archscan import scan
        result = scan(strict_api=True)
        graph = result.get("module_graph") or {}
        return {
            "ok": bool(result.get("ok")),
            "modules": len(result.get("modules") or []),
            "api_edges": sum(len(v) for v in graph.values()),
            "api_cycles": result.get("api_cycles") or [],
            "import_cycles": result.get("import_cycles") or [],
            "errors": result.get("errors") or [],
            "warnings": result.get("warnings") or [],
        }
