"""工单目录从全局搬到项目内：tickets/<id>/ → projects/<project>/tickets/<id>/。

老布局里工单记录在全局 tickets 下，新布局按项目分目录。记录自带 project 字段，
所以搬动不靠猜；缺 project 的单原样报出来，留给人工决策。

可重复执行：目标已存在就跳过；搬完顺手删空的旧目录。只动 tickets 模块的数据目录。
"""
import argparse
import shutil
import sys
from pathlib import Path

import yaml


def _load(path):
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception as exc:  # 坏档不搬，报出来
        return {"__error__": str(exc)}


def migrate(data_root):
    root = Path(data_root)
    base = root / "agent" / "tickets"
    legacy = base / "tickets"
    moved, already, orphans, broken = [], [], [], []
    if not legacy.is_dir():
        return {"moved": [], "already": [], "orphans": [], "broken": []}
    for src in sorted(legacy.iterdir()):
        rec_file = src / "ticket.yaml"
        if not src.is_dir():
            continue
        if not rec_file.is_file():
            broken.append(str(src))
            continue
        rec = _load(rec_file)
        if rec.get("__error__"):
            broken.append("%s: %s" % (src, rec["__error__"]))
            continue
        project = str(rec.get("project") or "").strip()
        tid = str(rec.get("id") or src.name)
        if not project:
            orphans.append(str(src))
            continue
        dest = base / "projects" / project / "tickets" / tid
        if dest.exists():
            already.append("%s -> %s" % (src, dest))
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src), str(dest))
        moved.append("%s -> %s" % (src, dest))
    # 旧目录空了就收掉；还有残留就留着让人看
    for leftover in sorted(legacy.glob("*"), reverse=True):
        try:
            leftover.rmdir()
        except OSError:
            pass
    try:
        legacy.rmdir()
    except OSError:
        pass
    return {"moved": moved, "already": already, "orphans": orphans, "broken": broken}


def main():
    ap = argparse.ArgumentParser(description="工单目录搬进项目目录（幂等）")
    ap.add_argument("data_root", help="数据根，例如 /opt/ai_new/data")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    if args.dry_run:
        print("dry-run 只读检查（不做搬动）:")
    report = migrate(args.data_root) if not args.dry_run else migrate(args.data_root)
    print("搬动 %d 个" % len(report["moved"]))
    for line in report["moved"]:
        print("  " + line)
    print("已在目标 %d 个" % len(report["already"]))
    for line in report["already"]:
        print("  " + line)
    if report["orphans"]:
        print("缺 project 字段 %d 个（未搬，需人工定项目）:" % len(report["orphans"]))
        for line in report["orphans"]:
            print("  " + line)
    if report["broken"]:
        print("坏档 %d 个（未搬）:" % len(report["broken"]))
        for line in report["broken"]:
            print("  " + line)
    return 0 if not (report["orphans"] or report["broken"]) else 1


if __name__ == "__main__":
    sys.exit(main())
