#!/usr/bin/env python3
"""Skip 门禁：只允许登记过的平台/外部依赖跳过，防止用例被静默 skip 掉。

默认只跑含平台分支的模块（约 20s），不重复跑全量：
- 解析每条 `... skipped 'reason'`；
- 当前平台下必须在 `scripts/skip_manifest.json` 有登记；
- 实际原因必须与登记一致；
- 登记项必须写明 `counterpart`（对端平台/桩覆盖），禁止“只跳不测”。

用法：
  python scripts/gate_skips.py
  python scripts/gate_skips.py --log /tmp/skips.log
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
PRIVATE = ROOT / "ai_new" / "modules" / "agent_test" / "private"
MANIFEST = ROOT / "scripts" / "skip_manifest.json"
MODULES = [
    "test_isolation", "test_isolation_tiers", "test_isolation_windows",
    "test_plat", "test_cloud_s3", "test_cloud_webdav",
]
SKIP_RE = re.compile(r"^.*\((?P<id>[^)]+)\) \.\.\. skipped(?: ['\"](?P<reason>.*)['\"])?$")


def platform_name():
    if sys.platform.startswith("win"):
        return "windows"
    if os.name == "posix":
        return "linux"
    return sys.platform


def load_manifest():
    data = json.loads(MANIFEST.read_text(encoding="utf-8"))
    allowed = {}
    for row in data.get("allowed") or []:
        tid = row.get("test")
        if not tid:
            raise SystemExit("skip_manifest 缺少 test: %s" % row)
        if not row.get("counterpart"):
            raise SystemExit("skip_manifest 缺少 counterpart: %s" % tid)
        if not row.get("reason"):
            raise SystemExit("skip_manifest 缺少 reason: %s" % tid)
        allowed[(tid, tuple(row.get("platforms") or []))] = row
    return data, allowed


def run(log_path=None):
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT) + os.pathsep + env.get("PYTHONPATH", "")
    env.setdefault("PYTHONIOENCODING", "utf-8")
    proc = subprocess.run(
        [sys.executable, "-m", "unittest", "-v", *MODULES],
        cwd=str(PRIVATE), env=env, text=True, encoding="utf-8",
        errors="replace", capture_output=True)
    out = proc.stdout + "\n" + proc.stderr
    if log_path:
        Path(log_path).write_text(out, encoding="utf-8")
    return proc.returncode, out


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--log", default="")
    args = ap.parse_args(argv)
    plat = platform_name()
    data, allowed = load_manifest()
    code, out = run(args.log or None)
    skips = []
    for line in out.splitlines():
        m = SKIP_RE.match(line.strip())
        if m:
            reason = (m.group("reason") or "").strip()
            skips.append((m.group("id").strip(), reason))

    problems = []
    for tid, reason in skips:
        matches = [row for (key, plats), row in allowed.items()
                   if key == tid and plat in plats]
        if not matches:
            problems.append("未登记 skip: %s (%s)" % (tid, reason))
            continue
        row = matches[0]
        if reason and row["reason"] != reason:
            problems.append("skip 原因漂移: %s 登记=%r 实际=%r"
                            % (tid, row["reason"], reason))

    if code:
        problems.append("skip 探测模块本身失败，退出码 %s" % code)

    print("skip 门禁：平台=%s 实际 skip=%d 登记允许=%d"
          % (plat, len(skips), len(allowed)))
    for tid, reason in skips:
        print("  - %s :: %s" % (tid, reason))
    if problems:
        print("\nskip 门禁失败：", file=sys.stderr)
        for item in problems:
            print("  - " + item, file=sys.stderr)
        return 1
    print("skip 门禁通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
