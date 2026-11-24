"""L4 韧性层：真实子进程 + 真实文件锁台账 + 真实 SIGKILL。

编排脚本 ``scripts/resilience_drill.py``，不在本层复制断言：
- kill -9 后台账可读、租约过期只接管一次、结算后复用；
- 6 个独立进程并发抢同一键，只允许一个 claimed；
- 租约过期 sweep 标 abandoned，后来者不自动接管；
- 在途恢复不双跑：第二个执行体被拒，杀掉后只接管一次。

底层台账是 ``store.claim / renew / settle / sweep``（store/private/_idem.py），
子进程使用独立 ``AI_NEW_DATA`` 临时目录，不碰源码树和线上数据。
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from report import LayerResult, Timer

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "assert"))
from recorder import Recorder  # noqa: E402

ROOT = Path(__file__).resolve().parents[3]
DRILL = ROOT / "scripts" / "resilience_drill.py"


def _run_drill(timeout: float) -> tuple[bool, list[dict], str]:
    proc = subprocess.run(
        [sys.executable, str(DRILL), "--json"],
        cwd=str(ROOT), capture_output=True, text=True,
        timeout=max(30.0, timeout))
    text = (proc.stdout or "") + (proc.stderr or "")
    try:
        report = json.loads(proc.stdout or "{}")
    except ValueError:
        return False, [], text[-1200:]
    checks = report.get("checks") or []
    return bool(report.get("ok")) and proc.returncode == 0, checks, text[-1200:]


def run(timeout: float = 300.0) -> LayerResult:
    rec = Recorder()
    output = []
    with Timer() as t:
        try:
            ok, checks, text = _run_drill(timeout)
            output.append(text)
            for c in checks:
                rec.check(str(c.get("name") or "韧性检查"), bool(c.get("ok")),
                          str(c.get("detail") or ""))
            if not checks:
                rec.check("L4 韧性演练产出", False, "演练脚本没有返回检查项")
        except Exception as exc:  # noqa: BLE001 — 层失败要留原因，不吞异常
            rec.check("L4 韧性演练", False, repr(exc))
    return LayerResult(
        layer="L4", title="韧性（中断恢复/租约/幂等/不双跑）",
        ok=rec.ok, duration=t.elapsed, checks=rec.checks, output="\n".join(output),
        note="真实子进程 + 真实文件锁台账：kill -9、6 进程并发、租约 sweep、恢复不双跑。",
    )
