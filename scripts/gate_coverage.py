#!/usr/bin/env python3
"""覆盖率门禁：测试必须真的跑过，并且覆盖率达到写死的阈值。

口径：
  - 数据来自 ``coverage run --branch`` 生成的 data 文件；
  - 只统计 ``ai_new/modules`` 产品代码，测试代码本身不计入（避免自己覆盖自己）；
  - 行覆盖与分支覆盖分别判定，任一低于阈值即红；
  - 关键机制模块（agent_common/react、agent/sessions、agent/todos、agent/library）
    单独设最低线，防止“整体达标、核心裸奔”。

用法：
  python3 scripts/gate_coverage.py [--data-file .coverage] [--config scripts/coverage.json]
  python3 scripts/gate_coverage.py --min-line 70 --min-branch 55

退出码：0 达标；1 缺数据/低于阈值/报告不可读。门禁失败必须阻断 CI，不允许告警放行。
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / "scripts" / "coverage.json"
DEFAULT_DATA = ROOT / ".coverage"
OMIT = "*/agent_test/*,*/web/data/console/assets/*"


def _load_config(path: Path) -> dict:
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001 —— 配置坏必须显式报错，不能静默用默认值
        raise SystemExit("覆盖率配置不可读 %s: %s" % (path, exc))


def _report(data_file: Path, out_json: Path) -> dict:
    cmd = [sys.executable, "-m", "coverage", "json",
           "--data-file=%s" % data_file, "--omit=%s" % OMIT,
           "-o", str(out_json)]
    proc = subprocess.run(cmd, cwd=str(ROOT), capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError((proc.stdout or "") + (proc.stderr or ""))
    return json.loads(out_json.read_text(encoding="utf-8"))


def _pct(num: int, den: int) -> float:
    return 100.0 * num / den if den else 100.0


def _module_totals(files: dict) -> dict:
    """按模块前缀聚合，返回 {module: {line, branch, ...}}，只统计产品代码。"""
    out: dict[str, dict] = {}
    for path, rec in files.items():
        rel = path.replace(str(ROOT) + os.sep, "").replace(os.sep, "/")
        if "agent_test/" in rel or "/assets/" in rel:
            continue
        parts = rel.split("/")
        # ai_new/modules/<组>/<模块>/...
        key = "/".join(parts[:4]) if len(parts) >= 4 else rel
        row = out.setdefault(key, {"lines": 0, "covered": 0,
                                   "branches": 0, "branches_covered": 0})
        row["lines"] += int(rec.get("summary", {}).get("num_statements") or 0)
        row["covered"] += int(rec.get("summary", {}).get("covered_lines") or 0)
        row["branches"] += int(rec.get("summary", {}).get("num_branches") or 0)
        row["branches_covered"] += int(rec.get("summary", {}).get("covered_branches") or 0)
    return out


def _critical(files: dict, critical: list[str], min_pct: float,
              min_branch_pct: float | None = None) -> list[str]:
    branch_floor = min_pct if min_branch_pct is None else min_branch_pct
    bad = []
    for prefix in critical:
        line = branch = 0
        for path, rec in files.items():
            rel = path.replace(str(ROOT) + os.sep, "")
            if not rel.startswith(prefix):
                continue
            s = rec.get("summary", {})
            line += int(s.get("num_statements") or 0)
            branch += int(s.get("num_branches") or 0)
            cov_l = int(s.get("covered_lines") or 0)
            cov_b = int(s.get("covered_branches") or 0)
        # 聚合后重新算
        cov_l = cov_b = 0
        for path, rec in files.items():
            rel = path.replace(str(ROOT) + os.sep, "")
            if not rel.startswith(prefix):
                continue
            s = rec.get("summary", {})
            cov_l += int(s.get("covered_lines") or 0)
            cov_b += int(s.get("covered_branches") or 0)
        lp = _pct(cov_l, line)
        bp = _pct(cov_b, branch)
        if lp < min_pct or (branch and bp < branch_floor):
            bad.append("%s: 行 %.1f%% / 分支 %.1f%% < %.0f%%/%.0f%%"
                       % (prefix, lp, bp, min_pct, branch_floor))
    return bad


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-file", default=str(DEFAULT_DATA))
    ap.add_argument("--config", default=str(DEFAULT_CONFIG))
    ap.add_argument("--min-line", type=float)
    ap.add_argument("--min-branch", type=float)
    ap.add_argument("--min-critical", type=float)
    ap.add_argument("--min-critical-branch", type=float)
    args = ap.parse_args(argv)

    cfg = _load_config(Path(args.config))
    min_line = args.min_line if args.min_line is not None else float(cfg.get("line", 65))
    min_branch = args.min_branch if args.min_branch is not None else float(cfg.get("branch", 50))
    min_critical = args.min_critical if args.min_critical is not None else float(cfg.get("critical", 80))
    min_critical_branch = (args.min_critical_branch if args.min_critical_branch is not None
                           else float(cfg.get("critical_branch", min_critical)))
    critical = cfg.get("critical_modules") or [
        "ai_new/modules/agent_common/react/",
        "ai_new/modules/agent/sessions/",
        "ai_new/modules/agent/todos/",
        "ai_new/modules/agent/library/",
    ]

    data_file = Path(args.data_file)
    if not data_file.is_file():
        print("覆盖率门禁失败：找不到 %s；先跑 coverage run --branch ... 再执行本门禁" % data_file)
        return 1
    out_json = data_file.with_suffix(".json")
    try:
        report = _report(data_file, out_json)
    except Exception as exc:  # noqa: BLE001
        print("覆盖率门禁失败：报告不可读：%s" % exc)
        return 1

    totals = report.get("totals") or {}
    line = _pct(int(totals.get("covered_lines") or 0), int(totals.get("num_statements") or 0))
    branch = _pct(int(totals.get("covered_branches") or 0), int(totals.get("num_branches") or 0))
    modules = _module_totals(report.get("files") or {})
    bad = []
    if line < min_line:
        bad.append("整体行覆盖 %.1f%% < %.1f%%" % (line, min_line))
    if branch < min_branch:
        bad.append("整体分支覆盖 %.1f%% < %.1f%%" % (branch, min_branch))
    if min_branch > 0 and int(totals.get("num_branches") or 0) == 0:
        bad.append("没有分支数据：coverage 必须以 --branch 启动")
    if critical:
        bad.extend(_critical(report.get("files") or {}, critical, min_critical,
                             min_critical_branch))

    print("覆盖率：行 %.1f%%（阈值 %.1f%%）· 分支 %.1f%%（阈值 %.1f%%）"
          % (line, min_line, branch, min_branch))
    print("关键模块阈值：行 %.1f%% / 分支 %.1f%%：%s"
          % (min_critical, min_critical_branch,
             "、".join(c.split("modules/")[-1] for c in critical)))
    worst = sorted(modules.items(), key=lambda kv: _pct(kv[1]["covered"], kv[1]["lines"]))[:5]
    if worst:
        print("覆盖率最低模块：" + "；".join(
            "%s %.1f%%" % (k.split("modules/")[-1], _pct(v["covered"], v["lines"]))
            for k, v in worst))
    if bad:
        print("覆盖率门禁未通过：")
        for x in bad:
            print("  - " + x)
        return 1
    print("覆盖率门禁通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
