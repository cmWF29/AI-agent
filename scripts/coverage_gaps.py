#!/usr/bin/env python3
"""覆盖率缺口清单：从 coverage JSON 生成逐文件/逐模块缺口，供批量补测排期。

用法：
  python3 scripts/coverage_gaps.py --coverage-json /tmp/coverage.json \
      --out docs/reports/coverage-gaps.md
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def rows(files: dict, root: Path) -> list[dict]:
    out = []
    for path, rec in files.items():
        rel = path.replace(str(root) + "/", "").replace("\\", "/")
        if "agent_test/" in rel or "/assets/" in rel:
            continue
        s = rec.get("summary") or {}
        ml, mb = int(s.get("missing_lines") or 0), int(s.get("missing_branches") or 0)
        if not ml and not mb:
            continue
        out.append({
            "file": rel, "line_total": int(s.get("num_statements") or 0),
            "branch_total": int(s.get("num_branches") or 0),
            "missing_lines": ml, "missing_branches": mb,
            "percent": float(s.get("percent_covered") or 0),
            "module": "/".join(rel.split("/")[:4]),
        })
    return sorted(out, key=lambda r: (-(r["missing_lines"] + r["missing_branches"]), r["file"]))


def render(data: dict, root: Path, top: int = 0) -> str:
    rs = rows(data.get("files") or {}, root)
    total_files = len(rs)
    if top:
        rs = rs[:top]
    totals = data.get("totals") or {}
    lines = [
        "# 覆盖率缺口清单",
        "",
        "基线：行 %.2f%%（%d/%d），分支 %.2f%%（%d/%d），共 %d 个产品文件有缺口。"
        % (float(totals.get("percent_covered") or 0),
           int(totals.get("covered_lines") or 0), int(totals.get("num_statements") or 0),
           float(totals.get("percent_branches_covered") or 0),
           int(totals.get("covered_branches") or 0), int(totals.get("num_branches") or 0),
           total_files),
        "",
        "| 模块 | 文件 | 缺行 | 缺分支 | 行覆盖 |",
        "|---|---|---:|---:|---:|",
    ]
    for r in rs:
        lines.append("| %s | %s | %d | %d | %.1f%% |"
                     % (r["module"].replace("ai_new/modules/", ""), r["file"],
                        r["missing_lines"], r["missing_branches"], r["percent"]))
    lines.append("")
    groups: dict[str, list[int]] = {}
    for r in rs:
        g = groups.setdefault(r["module"], [0, 0])
        g[0] += r["missing_lines"]
        g[1] += r["missing_branches"]
    lines += ["## 按模块聚合", "", "| 模块 | 缺行 | 缺分支 |", "|---|---:|---:|"]
    for mod in sorted(groups, key=lambda m: -(groups[m][0] + groups[m][1])):
        lines.append("| %s | %d | %d |"
                     % (mod.replace("ai_new/modules/", ""), groups[mod][0], groups[mod][1]))
    lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--coverage-json", required=True)
    ap.add_argument("--out")
    ap.add_argument("--top", type=int, default=0, help="只输出缺口最大的前 N 个文件")
    args = ap.parse_args(argv)
    text = render(load(Path(args.coverage_json)), ROOT, args.top)
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
        print("写入 %s" % args.out)
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
