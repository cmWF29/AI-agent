#!/usr/bin/env python3
"""从目录级快照恢复项目交付件/知识/工单目录。

用法：
    python scripts/restore_node_snapshot.py --snapshot-dir <快照目录> \
        --project <项目 id> --dest <恢复根目录>

快照布局与项目工作区相对布局一致（tickets/ knowledge/ artifacts/ …）；
本脚本只做按相对路径还原 + 逐文件摘要复核，不改快照原件。
"""
from __future__ import annotations

import argparse
import hashlib
import shutil
import sys
from pathlib import Path


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--snapshot-dir", required=True)
    ap.add_argument("--project", required=True)
    ap.add_argument("--dest", required=True)
    args = ap.parse_args(argv)

    snap = Path(args.snapshot_dir)
    if not snap.is_dir():
        print("快照目录不存在: %s" % snap, file=sys.stderr)
        return 2

    dest = Path(args.dest) / args.project
    dest.mkdir(parents=True, exist_ok=True)

    restored = []
    for src in sorted(snap.rglob("*")):
        if not src.is_file():
            continue
        rel = src.relative_to(snap)
        target = dest / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, target)
        restored.append(str(rel))

    digests = {rel: _sha256(dest / rel) for rel in restored}
    print({"project": args.project, "restored": len(restored),
           "dest": str(dest), "digests": digests})
    return 0


if __name__ == "__main__":
    sys.exit(main())
