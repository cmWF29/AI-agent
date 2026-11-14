"""回归测试模块：把测试编排从命令行脚本收编为可寻址服务。

`/api/test/run` 只允许跑仓库内置套件，不接受任意命令；超时后返回失败，不阻塞内核。
"""
from __future__ import annotations

import os
import subprocess
import sys

from ...kernel.api import Module, ApiError

ALLOWED = {"all": "tests/run_all.py"}


class TestRunner(Module):
    name = "testrunner"

    def setup(self):
        self.api.route("GET", "/api/test/catalog", name="catalog")(self.catalog)
        self.api.route("POST", "/api/test/run", name="run")(self.run_suite)
        self.log.info("testrunner.ready")

    def catalog(self, payload):
        return {"items": [{"id": k, "path": v} for k, v in ALLOWED.items()]}

    def run_suite(self, payload):
        suite = (payload or {}).get("suite", "all")
        script = ALLOWED.get(suite)
        if not script:
            raise ApiError("未知测试套件: %s" % suite, 400, "bad_suite")
        root = self.ctx.cfg["root"]
        try:
            proc = subprocess.run(
                [sys.executable, script],
                cwd=root,
                capture_output=True,
                text=True,
                timeout=300,
            )
            return {
                "suite": suite,
                "code": proc.returncode,
                "ok": proc.returncode == 0,
                "stdout_tail": "\n".join((proc.stdout or "").splitlines()[-12:]),
                "stderr_tail": "\n".join((proc.stderr or "").splitlines()[-6:]),
            }
        except subprocess.TimeoutExpired:
            return {"suite": suite, "ok": False, "code": -1, "error": "测试超时（>300s）"}
