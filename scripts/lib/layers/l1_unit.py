"""L1 后端单元（UT）层。

不新建一套用例：把既有 unittest 模块按单元测试口径转调跑一遍。
既有 ``python test_start.py`` 与本层并行存在，互不吞掉；本层只多一个分层入口。

覆盖口径（与既有模块一致，不重复造断言）：
- 纯函数 / 状态机迁移 / 并发 / 幂等 / 边界，分别落在
  test_core · test_architecture · test_demands · test_demand_engine ·
  test_boot_graph · test_transport · test_idem · test_stub_proto，
  以及合流新增的 test_graph_patterns · test_isolation ·
  test_knowledge_concurrency · test_node_profile · test_nodes ·
  test_isolation_tiers · test_archive · test_secretary · test_timer ·
  test_role_gates · test_skill_decompose（与 CI 单测清单一致）。
"""
from __future__ import annotations

import io
import sys
import unittest
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
    "test_isolation_tiers",
    "test_archive",
    "test_secretary",
    "test_timer",
    "test_role_gates",
    "test_skill_decompose",
    "test_levels",
    "test_react_mechanisms",
    "test_gate_diff_coverage",
]

MODULES = BASELINE_MODULES + EXTRA_MODULES


def _run_module(name: str) -> tuple[bool, int, list[str], str]:
    suite = unittest.defaultTestLoader.loadTestsFromName(name)
    stream = io.StringIO()
    runner = unittest.TextTestRunner(stream=stream, verbosity=1)
    result = runner.run(suite)
    problems = [str(x) for x in result.failures] + [str(x) for x in result.errors]
    return result.wasSuccessful(), result.testsRun, problems, stream.getvalue()


def run(selected: list[str] | None = None, timeout: float = 300.0) -> LayerResult:
    selected = selected or MODULES
    rec = Recorder()
    output_blocks: list[str] = []
    total_run = 0
    with Timer() as t:
        for name in selected:
            ok, ran, problems, out = _run_module(name)
            total_run += ran
            rec.check(name, ok, "Ran %d；失败/错误 %d" % (ran, len(problems)))
            if out.strip():
                tail = "\n".join(out.strip().splitlines()[-15:])
                output_blocks.append("[%s]\n%s" % (name, "\n".join("  " + l for l in tail.splitlines())))
    note = "L1 转调 %d 个模块（基线 8 + 合流新增 %d）；后端用例按模块放进 agent_test/private，不在此层复制断言。" % (len(MODULES), len(EXTRA_MODULES))
    return LayerResult(
        layer="L1", title="后端单元（纯函数/状态机/并发/幂等/边界）",
        ok=rec.ok, duration=t.elapsed, checks=rec.checks,
        output="\n".join(output_blocks),
        note=note,
    )
