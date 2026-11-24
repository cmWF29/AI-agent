"""L3 系统级 E2E（ST）：真前端 + 真后端 + 真浏览器。

两条业务闭环：
- project：新建项目 → 列表出现 → 清理；
- ticket ：新建项目 → 新建工单 → 给 PM 发消息 → 岗位派发/模型回复 → 回 idle → 清理。

两条都点真实 DOM、走真实 RPC；专门覆盖“UT/接口绿但按钮点不动、消息发不出”
这类前后端接线断裂。不是截图冒烟。
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


def _run_scenario(boot, scenario: str, timeout: float) -> tuple[bool, str]:
    env = os.environ.copy()
    env["HIVE_TOKEN"] = "t"       # bootstrap 的服务鉴权 token
    proc = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "verify_e2e.py"),
         "--scenario", scenario, "http://127.0.0.1:%d" % boot.port],
        cwd=str(ROOT), env=env, capture_output=True, text=True,
        timeout=max(30.0, timeout - 10.0))
    return proc.returncode == 0, (proc.stdout or "") + (proc.stderr or "")


def run(timeout: float = 300.0) -> LayerResult:
    rec = Recorder()
    output = []
    boot = None
    with Timer() as t:
        try:
            boot = _bootstrap.boot()
            for scenario, label in (("project", "浏览器项目 E2E"),
                                    ("ticket", "浏览器工单 E2E")):
                ok, text = _run_scenario(boot, scenario, timeout / 2)
                output.append(text)
                rec.check(label, ok, text[-800:])
        except Exception as exc:  # noqa: BLE001 — 层失败要留原因，不吞异常
            rec.check("浏览器业务 E2E", False, repr(exc))
        finally:
            if boot is not None:
                boot.cleanup()
    return LayerResult(
        layer="L3", title="系统级 E2E（真前端 + 真后端）",
        ok=rec.ok, duration=t.elapsed, checks=rec.checks, output="\n".join(output),
        note="项目：建项目→列表→清理；工单：建单→发消息→PM 回复→回 idle→清理。",
    )
