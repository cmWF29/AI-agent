"""L0 静态 / 架构 / 文档 / 映射层。

口径：老六道门禁 + 死代码扫描（另一 Agent 交付，这里只转调不改本体）。
每道门禁作为独立子进程可单独跑；本层只汇总退出码与输出，不重写判定逻辑。

接缝：代码-文档同步扫描器落盘后，在 ``GATES`` 追加一条即可接入；
共享解析能力统一走 ``scripts/lib/scan/``，不在本层另建一套。
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from report import Check, LayerResult, Timer

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "assert"))
from recorder import Recorder  # noqa: E402

ROOT = Path(__file__).resolve().parents[3]
SCRIPTS = ROOT / "scripts"

# id -> (标题, 脚本相对路径, 是否随缺省全量跑)
GATES: list[tuple[str, str, Path, bool]] = [
    ("controls", "控件状态机：每个按钮/事件都要有声明过的状态机",
     SCRIPTS / "gate_controls.py", True),
    ("ops", "运维指标：指标与取数源一一对应", SCRIPTS / "gate_ops.py", True),
    ("inventory", "可点实例：每条都有控件 id / 状态机 / 去向",
     SCRIPTS / "gate_inventory.py", True),
    ("screens", "界面状态图：页面/浮层节点、浮层可关、入口可达",
     SCRIPTS / "gate_screens.py", True),
    ("views", "视图层：条件表达式 / 只读覆盖 / 工具卡单一折叠出口",
     SCRIPTS / "gate_views.py", True),
    ("card_size", "卡片尺寸：同区卡片整宽同高、无序号/内联尺寸",
     SCRIPTS / "gate_card_size.py", True),
    ("demand_tests", "需求↔用例映射：每条需求绑到 check 且映射表不过期",
     SCRIPTS / "gate_demand_tests.py", True),
    ("deadcode", "死代码：未引用函数/import/孤儿路由与工具",
     SCRIPTS / "gate_deadcode.py", False),
    ("docsync", "代码-文档同步：源码哈希 / 符号 / 孤儿文档",
     SCRIPTS / "gate_docsync.py", True),
    ("copy", "界面文案：禁用句式 / 长度上限 / 术语一致 / 字段泄漏",
     SCRIPTS / "gate_copy.py", True),
    ("frontend", "界面信息预算：网格卡字段上限 / 说明长度 / 品牌无渐变",
     SCRIPTS / "gate_frontend.py", True),
    ("levels", "四级层级：能力 center/node 声明、互斥与证据真实",
     SCRIPTS / "gate_levels.py", True),
    ("wiring", "接线：表单提交→需求 with→API 入参逐项贯通",
     SCRIPTS / "gate_wiring.py", True),
]


def _run_gate(script: Path, timeout: float) -> tuple[int, str]:
    proc = subprocess.run(
        [sys.executable, str(script)],
        cwd=str(ROOT), capture_output=True, text=True, timeout=timeout,
    )
    out = (proc.stdout or "") + (proc.stderr or "")
    return proc.returncode, out.strip()


def run(selected: list[str] | None = None, timeout: float = 120.0) -> LayerResult:
    selected = selected or [g[0] for g in GATES]
    rec = Recorder()
    output_blocks: list[str] = []
    with Timer() as t:
        for gid, title, script, _default in GATES:
            if gid not in selected:
                continue
            if not script.is_file():
                rec.check("%s（脚本缺失）" % gid, False, str(script))
                continue
            try:
                code, out = _run_gate(script, timeout)
            except subprocess.TimeoutExpired:
                rec.check(gid, False, "超时 %.0fs 未退出" % timeout)
                continue
            ok = code == 0
            rec.check(gid, ok, ("通过" if ok else "退出码 %d" % code))
            if out:
                output_blocks.append("[%s]\n%s" % (gid, "\n".join("  " + l for l in out.splitlines())))
    note = "死代码扫描未列入缺省全量；代码-文档同步扫描器接入后在此追加条目。"
    return LayerResult(
        layer="L0", title="静态/架构/文档/映射", ok=rec.ok, duration=t.elapsed,
        checks=rec.checks, output="\n".join(output_blocks), note=note,
    )
