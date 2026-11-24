"""L3 系统级 E2E（ST）：真前端 + 真后端 + 真浏览器。

当前落地的是最小业务闭环：打开项目页 → 点「新建项目」→ 弹窗出现 →
填名称 → 提交 → 列表出现 → 清理。它专门覆盖“UT/接口都绿，但按钮点不动”
这类前后端接线断裂；不是截图冒烟。

岗位分派→状态机迁移→交付件产出的全链路仍走既有 `test_secretary`/
`test_core` 后端用例，尚未搬进本层。
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from report import LayerResult, Timer

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "assert"))
from recorder import Recorder  # noqa: E402

from layers import _bootstrap  # noqa: E402

ROOT = Path(__file__).resolve().parents[3]


def run(timeout: float = 300.0) -> LayerResult:
    rec = Recorder()
    output = ""
    boot = None
    with Timer() as t:
        try:
            boot = _bootstrap.boot()
            env = os.environ.copy()
            env["HIVE_TOKEN"] = "t"       # bootstrap 的服务鉴权 token
            proc = subprocess.run(
                [sys.executable, str(ROOT / "scripts" / "verify_e2e.py"),
                 "http://127.0.0.1:%d" % boot.port],
                cwd=str(ROOT), env=env, capture_output=True, text=True,
                timeout=max(30.0, timeout - 10.0))
            output = (proc.stdout or "") + (proc.stderr or "")
            rec.check("浏览器新建项目 E2E", proc.returncode == 0, output[-800:])
        except Exception as exc:  # noqa: BLE001 — 层失败要留原因，不吞异常
            rec.check("浏览器新建项目 E2E", False, repr(exc))
        finally:
            if boot is not None:
                boot.cleanup()
    return LayerResult(
        layer="L3", title="系统级 E2E（真前端 + 真后端）",
        ok=rec.ok, duration=t.elapsed, checks=rec.checks, output=output,
        note="打开项目页→新建项目→提交→列表可见→清理；覆盖前后端接线断裂。",
    )
