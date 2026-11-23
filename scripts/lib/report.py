"""分层防护的人读 / 机读汇总。

每层跑完交回一个 :class:`LayerResult`；本模块只做格式化，不做判定。
- 人读：绿/红 + 每层失败摘要 + 耗时；
- 机读：``--json`` 输出结构化结果，供 CI 接线采集。
"""
from __future__ import annotations

import dataclasses
import json
import time
from typing import List, Optional


@dataclasses.dataclass
class Check:
    """单层内的一条检查。``detail`` 存失败依据链，成功时可留空。"""

    name: str
    ok: bool
    detail: str = ""


@dataclasses.dataclass
class LayerResult:
    layer: str
    title: str
    ok: bool
    duration: float
    checks: List[Check]
    output: str = ""
    note: str = ""

    def failed_checks(self) -> List[Check]:
        return [c for c in self.checks if not c.ok]


class Timer:
    """薄计时上下文：``with Timer() as t: ...; result.duration = t.elapsed``。"""

    def __init__(self) -> None:
        self._start = 0.0
        self.elapsed = 0.0

    def __enter__(self) -> "Timer":
        self._start = time.monotonic()
        return self

    def __exit__(self, *exc) -> None:
        self.elapsed = time.monotonic() - self._start


def _bar(ok: bool) -> str:
    return "PASS" if ok else "FAIL"


def render_text(results: List[LayerResult]) -> str:
    """人读汇总：逐层打印通过/失败与失败摘要，末尾给总览。"""
    lines: List[str] = []
    total_ok = True
    for r in results:
        total_ok = total_ok and r.ok
        head = "[%s] %s · %s · %.2fs" % (_bar(r.ok), r.layer, r.title, r.duration)
        lines.append(head)
        if r.output.strip():
            for ln in r.output.strip().splitlines():
                lines.append("    | " + ln)
        for c in r.failed_checks():
            lines.append("    !! %s%s" % (c.name, (" · " + c.detail) if c.detail else ""))
        if r.note:
            lines.append("    ~ " + r.note)
        lines.append("")
    passed = sum(1 for r in results if r.ok)
    lines.append("汇总：%d/%d 层通过，总体 %s" % (passed, len(results), _bar(total_ok)))
    return "\n".join(lines)


def render_json(results: List[LayerResult]) -> str:
    """机读输出：每层状态、检查明细、耗时与原始输出。"""
    payload = {
        "ok": all(r.ok for r in results),
        "layers": [
            {
                "layer": r.layer,
                "title": r.title,
                "ok": r.ok,
                "duration": round(r.duration, 4),
                "note": r.note,
                "checks": [
                    {"name": c.name, "ok": c.ok, "detail": c.detail} for c in r.checks
                ],
                "output": r.output,
            }
            for r in results
        ],
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def exit_code(results: List[LayerResult]) -> int:
    return 0 if all(r.ok for r in results) else 1
