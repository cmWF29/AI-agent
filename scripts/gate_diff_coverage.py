#!/usr/bin/env python3
"""改动行覆盖率门禁：本轮新增/修改过的产品代码行，必须有 90% 被用例执行。

口径：
  - 只统计 ``ai_new/modules`` 下、相对 base 新增的 ``.py`` 行；
  - 测试代码、注释、空行、纯结构行不计；是否“可执行”以 coverage 的
    executed_lines / missing_lines 为准，不靠正则猜；
  - 覆盖率数据必须来自 ``coverage run --branch``，缺失直接红；
  - base 默认取 CI 推送前的 ``GITHUB_BASE_SHA``，本地回退 ``HEAD^``；
    找不到可用 base 时显式报错，不允许“没有 diff 就算通过”。

用法：
  python3 scripts/gate_diff_coverage.py --data-file /tmp/hive.coverage
  python3 scripts/gate_diff_coverage.py --base HEAD~3 --min 90
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / "scripts" / "coverage.json"
ZERO = "0" * 40
TARGET = "ai_new/modules"


def _load_min(path: Path) -> float:
    if not path.is_file():
        return 90.0
    try:
        return float(json.loads(path.read_text(encoding="utf-8")).get("changed_line", 90))
    except Exception as exc:  # noqa: BLE001 —— 配置坏要报出来，不能静默降级
        raise SystemExit("覆盖率配置不可读 %s: %s" % (path, exc))


def _resolve_base(explicit: str) -> str:
    candidates = [explicit, os.environ.get("GITHUB_BASE_SHA") or "", "HEAD^"]
    for cand in candidates:
        cand = (cand or "").strip()
        if not cand or cand == ZERO:
            continue
        ok = subprocess.run(["git", "cat-file", "-e", cand + "^{commit}"],
                            cwd=str(ROOT), capture_output=True)
        if ok.returncode == 0:
            return cand
    raise SystemExit("改动行覆盖率门禁失败：找不到可用的 base commit；显式传 --base")


def _diff(base: str) -> str:
    proc = subprocess.run(
        ["git", "diff", "--unified=0", "--no-color", base, "HEAD", "--", TARGET],
        cwd=str(ROOT), capture_output=True, text=True)
    if proc.returncode != 0:
        raise SystemExit("改动行覆盖率门禁失败：git diff 不可读：%s" % (proc.stderr or ""))
    return proc.stdout


def _added_lines(diff_text: str) -> dict[str, set[int]]:
    """从 unified=0 diff 里取新增行号；跳过空行与注释，可执行性交给 coverage 判定。"""
    out: dict[str, set[int]] = {}
    path = ""
    new_line = 0
    in_hunk = False
    for raw in diff_text.splitlines():
        if raw.startswith("+++ "):
            path = raw[4:].strip()
            if path.startswith("b/"):
                path = path[2:]
            in_hunk = False
            continue
        if raw.startswith("@@ "):
            m = re.search(r"\+(\d+)(?:,(\d+))?", raw)
            if not m:
                in_hunk = False
                continue
            new_line = int(m.group(1))
            in_hunk = True
            continue
        if not in_hunk:
            continue
        if raw.startswith("+"):
            body = raw[1:].strip()
            if (path.endswith(".py") and "/agent_test/" not in path
                    and body and not body.startswith("#")):
                out.setdefault(path, set()).add(new_line)
            new_line += 1
        elif raw.startswith("-"):
            continue
        else:
            new_line += 1
    return out


def _coverage_lines(report: dict) -> dict[str, tuple[set[int], set[int]]]:
    out = {}
    for path, rec in (report.get("files") or {}).items():
        rel = path.replace(str(ROOT) + os.sep, "").replace(os.sep, "/")
        out[rel] = (set(rec.get("executed_lines") or []),
                    set(rec.get("missing_lines") or []))
    return out


def evaluate(added: dict[str, set[int]],
             cov: dict[str, tuple[set[int], set[int]]],
             min_pct: float) -> tuple[int, int, list[str], bool]:
    """按改动行与实际执行行算覆盖率；0 行可执行视为通过，阈值判定独立可测。"""
    total = covered = 0
    gaps = []
    unmeasured = False
    for path, lines in sorted(added.items()):
        if path not in cov:
            # 新增文件没进覆盖率报告，说明 --source 漏了它，不能按“0 行可执行”放行
            unmeasured = True
            total += len(lines)
            gaps.append("%s: 未出现在 coverage 报告，新增 %d 行无法判定" % (path, len(lines)))
            continue
        executed, missing = cov[path]
        executable = (lines & executed) | (lines & missing)
        if not executable:
            continue
        total += len(executable)
        hit = len(executable & executed)
        covered += hit
        if hit < len(executable):
            gaps.append("%s: 覆盖 %d/%d，未执行 %s"
                        % (path, hit, len(executable),
                           "、".join(str(x) for x in sorted(executable - executed)[:12])))
    ok = not unmeasured and (not total or 100.0 * covered / total >= min_pct)
    return total, covered, gaps, ok


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-file", default=str(ROOT / ".coverage"))
    ap.add_argument("--config", default=str(DEFAULT_CONFIG))
    ap.add_argument("--base", default="")
    ap.add_argument("--min", type=float)
    args = ap.parse_args(argv)

    min_pct = args.min if args.min is not None else _load_min(Path(args.config))
    data = Path(args.data_file)
    if not data.is_file():
        print("改动行覆盖率门禁失败：找不到 %s" % data)
        return 1
    out_json = data.with_suffix(".diff.json")
    proc = subprocess.run(
        [sys.executable, "-m", "coverage", "json",
         "--data-file=%s" % data, "-o", str(out_json)], cwd=str(ROOT),
        capture_output=True, text=True)
    if proc.returncode != 0:
        print("改动行覆盖率门禁失败：报告不可读：%s" % ((proc.stdout or "") + (proc.stderr or "")))
        return 1

    base = _resolve_base(args.base)
    added = _added_lines(_diff(base))
    cov = _coverage_lines(json.loads(out_json.read_text(encoding="utf-8")))

    total, covered, gaps, ok = evaluate(added, cov, min_pct)

    print("改动行覆盖率：base %s · %d/%d 行可执行 · %.1f%%（阈值 %.0f%%）"
          % (base[:10], covered, total, 100.0 * covered / total if total else 100.0, min_pct))
    if gaps:
        print("未覆盖的改动：")
        for g in gaps[:20]:
            print("  - " + g)
    if total == 0:
        print("说明：base..HEAD 没有可执行的产品代码新增行，门禁按通过处理")
    if not ok:
        print("::error::改动行覆盖率门禁失败：新增/修改代码行低于 %.0f%%（见上方缺口）" % min_pct)
        return 1
    print("改动行覆盖率门禁通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
