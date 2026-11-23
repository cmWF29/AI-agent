#!/usr/bin/env python3
"""清理无项目承载的孤儿工单：登记进清单、但工单档案里查不到项目归属的工单条目与目录。

背景：日志 / 知识 / 产物三个模块按「公共 / 项目 / 工单」三级分组，工单条目必须挂在
所属项目节点下；工单档案（tickets 模块）里查不到 project 的条目是孤儿，不允许挂顶层
冒充项目层，统一从数据里摘除。

幂等、可审计：
  - plan(agent_root) 只盘点，返回孤儿清单（模块 / 工单 id / 清单文件 / 磁盘目录），不写盘；
  - apply(plan) 先把待删文件与目录整棵备份到 <模块>/data/_archive_orphans/<时间戳>/，
    再删除原始文件/目录，并从 index.yaml 摘除对应条目；备份目录里留 manifest.json；
  - 重复执行：第二次盘点为空，不重复备份、不重复删除。

用法：
  python3 scripts/purge_orphan_tickets.py              # 默认 dry-run，只打印清单
  python3 scripts/purge_orphan_tickets.py --apply       # 备份后实际清理
  python3 scripts/purge_orphan_tickets.py --apply <repo_root>
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from pathlib import Path

import yaml

MODULES = ["logs", "knowledge", "artifacts"]
ARCHIVE_DIR = "_archive_orphans"


def _records(agent_root: Path) -> dict:
    """工单档案：tid(小写) -> project；档案缺失或 project 为空都视为无承载。"""
    recs: dict[str, str] = {}
    base = agent_root / "tickets" / "data" / "projects"
    if base.is_dir():
        for f in base.glob("*/tickets/*/ticket.yaml"):
            try:
                row = yaml.safe_load(f.read_text(encoding="utf-8")) or {}
            except Exception:
                continue
            tid = str(row.get("id") or f.parent.name)
            if tid:
                recs[tid.lower()] = str(row.get("project") or "")
    return recs


def _index_entries(data: Path) -> list:
    idx = data / "index.yaml"
    if not idx.is_file():
        return []
    doc = yaml.safe_load(idx.read_text(encoding="utf-8")) or {}
    return [e for e in (doc.get("entries") or []) if isinstance(e, dict)]


def plan(agent_root: Path) -> dict:
    """盘点孤儿工单：不写盘。返回 {records, orphans:[{module, tids, files, dirs}]}。"""
    recs = _records(agent_root)
    orphans = []
    for mod in MODULES:
        data = agent_root / mod / "data"
        if not data.is_dir():
            continue
        entries = _index_entries(data)

        def _orphan(tid: str) -> bool:
            tid = tid.lower()
            return bool(tid) and (tid not in recs or not recs[tid])

        # 候选工单：清单登记的 ticket 层条目 + 磁盘上的工单目录（老布局全局 tickets/，
        # 新布局 projects/<pid>/tickets/<tid>/）；档案里查不到项目承载的才算孤儿。
        candidate = {str(e.get("ticket") or "").lower() for e in entries
                     if str(e.get("layer") or "") == "ticket"}
        legacy = data / "tickets"
        legacy_dirs = []
        if legacy.is_dir():
            legacy_dirs = [d for d in legacy.iterdir() if d.is_dir()]
            candidate |= {d.name.lower() for d in legacy_dirs}
        projects = data / "projects"
        project_dirs = []
        if projects.is_dir():
            project_dirs = [d for d in projects.glob("*/tickets/*") if d.is_dir()]
            candidate |= {d.name.lower() for d in project_dirs}
        orphan_tids = {tid for tid in candidate if _orphan(tid)}
        orphan_tids.discard("")
        if not orphan_tids:
            continue
        files = sorted(
            str(e.get("path")) for e in entries
            if str(e.get("ticket") or "").lower() in orphan_tids and e.get("path"))
        dirs = sorted(
            str(d.relative_to(data)) for d in legacy_dirs + project_dirs
            if d.name.lower() in orphan_tids)
        orphans.append({"module": mod, "tids": sorted(orphan_tids),
                        "files": files, "dirs": dirs})
    return {"agent_root": str(agent_root), "records": recs, "orphans": orphans}


def apply(plan: dict, timestamp: str | None = None) -> dict:
    """备份后实际清理。返回执行报告；备份目录与 manifest 留档可回溯。"""
    ts = timestamp or time.strftime("%Y%m%d-%H%M%S")
    agent_root = Path(plan["agent_root"])
    report = {"timestamp": ts, "purged": []}
    for group in plan["orphans"]:
        mod = group["module"]
        data = agent_root / mod / "data"
        archive = data / ARCHIVE_DIR / ts
        archive.mkdir(parents=True, exist_ok=True)
        # 1) 备份清单登记的文件
        for rel in group["files"]:
            src = data / rel
            if src.is_file():
                dst = archive / "files" / rel
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dst)
        # 2) 备份孤儿工单目录（整棵）
        for rel in group["dirs"]:
            src = data / rel
            if src.is_dir():
                shutil.copytree(src, archive / "dirs" / rel)
        # 3) 删除原始文件与目录
        for rel in group["files"]:
            src = data / rel
            if src.is_file():
                src.unlink()
        for rel in group["dirs"]:
            shutil.rmtree(data / rel, ignore_errors=True)
        # 4) 从 index.yaml 摘除孤儿条目
        idx = data / "index.yaml"
        if idx.is_file():
            doc = yaml.safe_load(idx.read_text(encoding="utf-8")) or {}
            keep = [e for e in (doc.get("entries") or [])
                    if str(e.get("ticket") or "").lower() not in set(group["tids"])]
            doc["entries"] = keep
            idx.write_text(yaml.safe_dump(doc, allow_unicode=True, sort_keys=False),
                           encoding="utf-8")
        report["purged"].append(group)
        # 每个模块归档目录各留一份 manifest，独立可回溯
        (archive / "manifest.json").write_text(
            json.dumps({"timestamp": ts, "purged": [group]}, ensure_ascii=False, indent=2),
            encoding="utf-8")
    manifest = archive_manifest(agent_root, report)
    return {"report": report, "manifest": manifest}


def archive_manifest(agent_root: Path, report: dict) -> str:
    """在最早的备份目录写 manifest.json，记录本轮摘除的全部条目。"""
    ts = report["timestamp"]
    for group in report["purged"]:
        archive = agent_root / group["module"] / "data" / ARCHIVE_DIR / ts
        manifest = archive / "manifest.json"
        manifest.write_text(json.dumps(report, ensure_ascii=False, indent=2),
                            encoding="utf-8")
        return str(manifest)
    return ""


def _print_plan(plan: dict) -> None:
    orphans = plan["orphans"]
    total = sum(len(g["tids"]) for g in orphans)
    print("盘点完成：%d 个模块命中 %d 个孤儿工单" % (len(orphans), total))
    for g in orphans:
        print("  [%s] 工单 %s" % (g["module"], ", ".join(g["tids"])))
        for rel in g["files"]:
            print("    文件 %s" % rel)
        for rel in g["dirs"]:
            print("    目录 %s/" % rel)
    if not orphans:
        print("没有孤儿工单：所有工单条目都挂在所属项目下。")


def main() -> int:
    ap = argparse.ArgumentParser(description="清理无项目承载的孤儿工单（幂等，先备份）")
    ap.add_argument("repo_root", nargs="?", default=str(Path(__file__).resolve().parents[1]),
                    help="仓库根（默认脚本所在仓库）")
    ap.add_argument("--apply", action="store_true", help="备份后实际清理；缺省只 dry-run")
    ap.add_argument("--timestamp", help=argparse.SUPPRESS)
    args = ap.parse_args()
    agent_root = Path(args.repo_root) / "ai_new" / "modules" / "agent"
    plan_doc = plan(agent_root)
    _print_plan(plan_doc)
    if not args.apply:
        print("\ndry-run：未写盘。加 --apply 备份后清理。")
        return 0
    result = apply(plan_doc, timestamp=args.timestamp)
    print("\n已清理：备份目录见各模块 data/%s/<时间戳>/，manifest: %s"
          % (ARCHIVE_DIR, result["manifest"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
