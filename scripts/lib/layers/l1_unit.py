"""L1 后端单元（UT）层。

不新建一套用例：把 agent_test/private 下 36 个 unittest 模块按单元测试口径转调跑一遍。
每个模块独立子进程 + 独立 AI_NEW_DATA（jobs=4 分片），既隔离模块间全局状态，也把
串行 250s 压到 ~85s。既有 ``python test_start.py`` 与本层并行存在，互不吞掉；本层只多一个分层入口。
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

from report import LayerResult, Timer

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "assert"))
from recorder import Recorder  # noqa: E402

ROOT = Path(__file__).resolve().parents[3]
PRIVATE = ROOT / "ai_new" / "modules" / "agent_test" / "private"

if str(PRIVATE) not in sys.path:
    sys.path.insert(0, str(PRIVATE))

BASELINE_MODULES = [
    "test_core",
    "test_architecture",
    "test_demands",
    "test_demand_engine",
    "test_boot_graph",
    "test_transport",
    "test_idem",
    "test_stub_proto",
]

EXTRA_MODULES = [
    "test_graph_patterns",
    "test_isolation",
    "test_knowledge_concurrency",
    "test_node_profile",
    "test_nodes",
    "test_distributed",
    "test_isolation_tiers",
    "test_archive",
    "test_secretary",
    "test_timer",
    "test_role_gates",
    "test_skill_decompose",
    "test_levels",
    "test_react_mechanisms",
    "test_gate_diff_coverage",
    "test_security_boundaries",
    "test_demand_engine_routes",
    "test_plat",
    "test_isolation_windows",
    "test_cloud",
    "test_cloud_guard",
    "test_cloud_seal",
    "test_cloud_sync",
    "test_cloud_s3",
    "test_cloud_webdav",
    "test_api",
    "test_deadcode",
    "test_docsync",
]

MODULES = BASELINE_MODULES + EXTRA_MODULES


def run(selected: list[str] | None = None, timeout: float = 300.0) -> LayerResult:
    selected = selected or MODULES
    rec = Recorder()
    output_blocks: list[str] = []
    with Timer() as t:
        # 分片跑：每个模块独立子进程 + 独立 AI_NEW_DATA，模块间不共享全局状态。
        # 同一进程串行会互相污染（timer/archive 共享 data），也慢 3 倍。
        with tempfile.TemporaryDirectory(prefix="hive-l1-") as tmp:
            report = Path(tmp) / "run.json"
            cmd = [sys.executable, str(ROOT / "scripts" / "run_tests.py"),
                   "--jobs", "4", "--modules", ",".join(selected),
                   "--timeout", str(int(timeout)), "--json-out", str(report)]
            proc = subprocess.run(cmd, cwd=str(ROOT), text=True,
                                  capture_output=True, timeout=timeout)
            stdout = (proc.stdout or "") + (proc.stderr or "")
            rows = []
            if report.exists():
                rows = json.loads(report.read_text(encoding="utf-8")).get("runs", [])
            if not rows:
                rec.check("L1-runner", False, "并行 runner 未产出报告（exit=%s）" % proc.returncode)
                output_blocks.append(stdout.strip()[-2000:])
            for row in sorted(rows, key=lambda r: r["module"]):
                rec.check(row["module"], bool(row["ok"]),
                          "%.2fs；exit=%s" % (row["seconds"], row["code"]))
                if not row["ok"]:
                    output_blocks.append("[%s]\n%s" % (row["module"], row.get("tail", "")))
            total_run = sum(1 for r in rows if r.get("ok"))
            if stdout.strip():
                output_blocks.append("runner 尾部：\n" + "\n".join(stdout.strip().splitlines()[-8:]))
    note = ("L1 并行转调 %d 个模块（jobs=4，独立 AI_NEW_DATA 分片）；通过 %d。"
            "用例仍在 agent_test/private，本层不复制断言。") % (len(selected), total_run)
    return LayerResult(
        layer="L1", title="后端单元（纯函数/状态机/并发/幂等/边界）",
        ok=rec.ok, duration=t.elapsed, checks=rec.checks,
        output="\n".join(output_blocks),
        note=note,
    )
