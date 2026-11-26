"""L3 系统级 E2E（ST）：真前端 + 真后端 + 真浏览器。

四条业务闭环（``verify_e2e.py`` 的全部场景都必须进闸，写好了不接等于没写）：
- project      ：新建项目 → 改名 → 归档 → 删除；
- ticket       ：新建工单 → 发消息 → 岗位接收 → 模型回复 → 结单 → 归档 → 删除；
- ticket-multi ：同一工单连续两轮追问，逐轮回到 idle 且消息数单调增长；
- archive-guard：归档项目的新建工单入口必须不可用（前端灰按钮不能绕过只读）。

四条都点真实 DOM、走真实 RPC；专门覆盖“UT/接口绿但按钮点不动、消息发不出”
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

# 写好的场景必须全部进闸：写而不接等于没有 E2E。
SCENARIOS = (
    ("project", "浏览器项目 E2E"),
    ("ticket", "浏览器工单 E2E"),
    ("ticket-multi", "浏览器多轮工单 E2E"),
    ("archive-guard", "浏览器归档只读 E2E"),
)


def _run_scenario(boot, scenario: str, timeout: float) -> tuple[bool, str]:
    env = os.environ.copy()
    env["HIVE_TOKEN"] = "t"       # bootstrap 的服务鉴权 token
    proc = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "verify_e2e.py"),
         "--scenario", scenario, "http://127.0.0.1:%d" % boot.port],
        cwd=str(ROOT), env=env, capture_output=True, text=True,
        timeout=max(30.0, timeout - 10.0))
    return proc.returncode == 0, (proc.stdout or "") + (proc.stderr or "")


def _run_pages(boot, timeout: float) -> tuple[bool, str]:
    env = os.environ.copy()
    env["HIVE_TOKEN"] = "t"
    proc = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "verify_pages.py"),
         "http://127.0.0.1:%d" % boot.port],
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
            # 场景预算：页面巡检留三分之一，其余按场景均分（不再写死 /2 这种会被
            # 场景数量悄悄吃掉的时长）。
            per = max(30.0, (timeout * 2.0 / 3.0) / len(SCENARIOS))
            for scenario, label in SCENARIOS:
                ok, text = _run_scenario(boot, scenario, per)
                output.append(text)
                rec.check(label, ok, text[-800:])
            ok, text = _run_pages(boot, timeout / 3)
            output.append(text)
            rec.check("全量页面/表单巡检", ok, text[-800:])
        except Exception as exc:  # noqa: BLE001 — 层失败要留原因，不吞异常
            rec.check("浏览器业务 E2E", False, repr(exc))
        finally:
            if boot is not None:
                boot.cleanup()
    return LayerResult(
        layer="L3", title="系统级 E2E（真前端 + 真后端）",
        ok=rec.ok, duration=t.elapsed, checks=rec.checks, output="\n".join(output),
        note="项目：建→改名→归档→删除；工单：建→发消息→回复→结单→归档→删除；"
             "多轮追问逐轮收口；归档后只读拦截；另巡全部视图与弹窗表单。",
    )
