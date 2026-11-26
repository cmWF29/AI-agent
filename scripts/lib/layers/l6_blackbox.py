"""L6 HTTP 黑盒业务 E2E（ST）：真服务、真 RPC、真并发，不走进程内装配。

转调 ``scripts/verify_api_e2e.py``（24 个场景），本层不复制断言，只做两件事：
- 引导一份真装配（临时数据目录 + 真 HTTP 服务），把 base 与 token 传下去；
- 把脚本逐场景的 OK/FAIL 行翻成层内检查项，一个场景一条，失败带原文摘要。

覆盖口径（写死端口、跑在默认 8787 之外的装配里都是 bug，本层用引导出的端口跑）：
项目改名与工单引用改挂、知识库版本冲突/追加作用域、定时器增改删与守卫、
节点申领与错 token 释放、12 路并发建删、拆单上限、结单级联只读、鉴权关闭/拒绝、
越权与路径穿越、坏 YAML/405/404/ETag 304 的壳层协议。
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

from report import LayerResult, Timer

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "assert"))
from recorder import Recorder  # noqa: E402

from layers import _bootstrap  # noqa: E402

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "scripts" / "verify_api_e2e.py"
_LINE = re.compile(r"^  (OK|FAIL)\s+([^\s]+)")


def run(timeout: float = 300.0) -> LayerResult:
    rec = Recorder()
    output = []
    boot = None
    with Timer() as t:
        try:
            boot = _bootstrap.boot()
            env = os.environ.copy()
            env["HIVE_TOKEN"] = "t"
            proc = subprocess.run(
                [sys.executable, str(SCRIPT), "--scenario", "all",
                 "--base", "http://127.0.0.1:%d" % boot.port, "--token", "t"],
                cwd=str(ROOT), env=env, capture_output=True, text=True,
                timeout=max(30.0, timeout))
            text = (proc.stdout or "") + (proc.stderr or "")
            output.append(text)
            seen = 0
            tail = {}
            for line in (proc.stdout or "").splitlines():
                m = _LINE.match(line)
                if not m:
                    continue
                seen += 1
                status, name = m.group(1), m.group(2)
                rec.check("黑盒 %s" % name, status == "OK", line.strip()[:600])
                if status == "FAIL":
                    tail[name] = line
            if seen == 0:
                rec.check("黑盒场景产出", False, text[-1200:])
            if proc.returncode != 0 and not tail:
                rec.check("黑盒脚本退出码", False, text[-1200:])
        except Exception as exc:  # noqa: BLE001 — 层失败要留原因，不吞异常
            rec.check("HTTP 黑盒业务 E2E", False, repr(exc))
        finally:
            if boot is not None:
                boot.cleanup()
    return LayerResult(
        layer="L6", title="HTTP 黑盒业务 E2E（真服务 + 真 RPC + 真并发）",
        ok=rec.ok, duration=t.elapsed, checks=rec.checks, output="\n".join(output),
        note="24 场景：项目/工单/知识/定时/节点/并发/权限/交付件/壳层边界，"
             "全部经真实 HTTP 打真装配，端口取自引导结果。",
    )
