#!/usr/bin/env python3
"""历史数据归类整改：知识 / 文档 / 日志三分，并回填各模块统一索引清单。

分类口径（与 agent_common/config 分类法一致，勿回退）：
- knowledge：仅 LLM 主动总结沉淀，source=llm，doc_kind=None。
- document：交付件 artifact / 非交付件 non_artifact；历史来源无据时回填 system。
- log：仅系统动作落盘，source=system，kind 标 channel/session/tool/...。

物理搬迁：
- 出厂内置规范模板（public 层、文件名见 BUILTIN_NON_ARTIFACT）从 knowledge 迁到
  artifacts，归文档/非交付件/system。
- 旧频道消息 channel/data/channels/*.jsonl 迁到 logs/data/channels/。
- 其余正文原位保留，只按落点解析归属并回填清单。

用法：
  python3 migrate_taxonomy.py --root <agent 模块目录> [--apply]
  不传 --apply 为 dry-run，只打印归类与搬迁计划，不落盘、不移动文件。

root 目录布局（镜像 modules/agent）：
  root/knowledge/data   root/artifacts/data   root/logs/data
  root/channel/data/channels   root/tickets/data
"""
from __future__ import annotations

import argparse
import datetime
import os
import shutil

import yaml


# 出厂内置规范模板：public 层、非交付件、系统内置；从 knowledge 迁出到 artifacts。
BUILTIN_NON_ARTIFACT = {"plan-structure.md"}

# 各模块 data 子目录相对 root 的位置。
KNOWLEDGE_DIR = os.path.join("knowledge", "data")
ARTIFACTS_DIR = os.path.join("artifacts", "data")
LOGS_DIR = os.path.join("logs", "data")
CHANNEL_DIR = os.path.join("channel", "data", "channels")
TICKETS_DIR = os.path.join("tickets", "data")

INDEX_NAME = "index.yaml"


def _iso(ts):
    return datetime.datetime.fromtimestamp(ts).isoformat(timespec="seconds")


def _rel(path, root):
    return os.path.relpath(path, root).replace(os.sep, "/")


def _load_yaml(path, default):
    if not os.path.exists(path):
        return default
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return data if isinstance(data, dict) else default


def _load_index(path):
    data = _load_yaml(path, {"entries": []})
    entries = data.get("entries") or []
    return [e for e in entries if isinstance(e, dict)]


def _dump_index(path, entries):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        yaml.safe_dump({"entries": entries}, f, allow_unicode=True,
                       default_flow_style=False, sort_keys=False)


def _upsert(entries, entry):
    rel = entry.get("path") or ""
    for i, row in enumerate(entries):
        if row.get("path") == rel:
            merged = dict(row)
            # 归类字段以本次扫描为准纠正；created 保留，updated/name 刷新。
            for key in ("category", "doc_kind", "source", "layer", "project", "ticket", "kind"):
                if key in entry:
                    merged[key] = entry[key]
            merged["updated"] = entry.get("updated") or merged.get("updated")
            merged["name"] = entry.get("name") or merged.get("name")
            entries[i] = merged
            return entries
    entries.append(entry)
    return entries


def _load_tickets(tickets_dir):
    """工单档案：id(小写) → {id, project, title}，供工单层条目回填项目归属。"""
    out = {}
    if not os.path.isdir(tickets_dir):
        return out
    for dirpath, _, names in os.walk(tickets_dir):
        for name in names:
            if name != "ticket.yaml":
                continue
            path = os.path.join(dirpath, name)
            try:
                row = _load_yaml(path, {})
            except yaml.YAMLError:
                continue
            tid = row.get("id") or ""
            if tid:
                out[tid.lower()] = {
                    "id": tid,
                    "project": row.get("project") or "",
                    "title": row.get("title") or "",
                }
    return out


def _parse_artifacts(rel):
    """artifacts 路径 → layer/project/ticket。"""
    parts = rel.split("/")
    if rel.startswith("projects/") and len(parts) >= 2:
        if "tickets" in parts:
            i = parts.index("tickets")
            ticket = parts[i + 1] if i + 1 < len(parts) else ""
            return "ticket", parts[1], ticket
        return "project", parts[1], ""
    return "public", "", ""


def _parse_knowledge(rel, tickets):
    """knowledge 路径 → layer/project/ticket；工单层项目由工单档案回填。"""
    parts = rel.split("/")
    if rel.startswith("projects/") and len(parts) >= 3:
        return "project", parts[1], ""
    if rel.startswith("tickets/") and len(parts) >= 3:
        tid = parts[1]
        ticket = tickets.get(tid.lower()) or {}
        return "ticket", ticket.get("project") or "", tid
    return "public", "", ""


def _iter_md(data_dir):
    if not os.path.isdir(data_dir):
        return
    for dirpath, _, names in os.walk(data_dir):
        for name in names:
            if not name.endswith(".md"):
                continue
            if name == "messages.yaml":
                continue
            yield os.path.join(dirpath, name)


def plan(root, apply):
    tickets_dir = os.path.join(root, TICKETS_DIR)
    tickets = _load_tickets(tickets_dir)

    knowledge_dir = os.path.join(root, KNOWLEDGE_DIR)
    artifacts_dir = os.path.join(root, ARTIFACTS_DIR)
    logs_dir = os.path.join(root, LOGS_DIR)
    channel_dir = os.path.join(root, CHANNEL_DIR)

    knowledge_entries, artifact_entries, log_entries = [], [], []
    moves = []  # (src_abs, dst_abs, note)

    # 1) knowledge 旧落点：内置模板迁出，其余归知识。
    for path in _iter_md(knowledge_dir):
        rel = _rel(path, knowledge_dir)
        name = rel.rsplit("/", 1)[-1]
        mtime = os.path.getmtime(path)
        stamp = _iso(mtime)
        layer, project, ticket = _parse_knowledge(rel, tickets)
        if layer == "public" and name in BUILTIN_NON_ARTIFACT:
            # 迁 artifacts：文档/非交付件/system/public。
            dst_rel = "public/" + name
            dst_abs = os.path.join(artifacts_dir, dst_rel)
            moves.append((path, dst_abs, "内置规范模板：knowledge → artifacts/non_artifact/system"))
            artifact_entries.append({
                "path": dst_rel, "category": "document", "doc_kind": "non_artifact",
                "source": "system", "layer": "public", "project": "", "ticket": "",
                "name": name, "created": stamp, "updated": stamp,
            })
        else:
            knowledge_entries.append({
                "path": rel, "category": "knowledge", "doc_kind": None,
                "source": "llm", "layer": layer, "project": project, "ticket": ticket,
                "name": name, "created": stamp, "updated": stamp,
            })

    # 2) artifacts 落点：文档/交付件；出厂内置规范模板为非交付件；来源无据回填 system。
    for path in _iter_md(artifacts_dir):
        rel = _rel(path, artifacts_dir)
        name = rel.rsplit("/", 1)[-1]
        mtime = os.path.getmtime(path)
        stamp = _iso(mtime)
        layer, project, ticket = _parse_artifacts(rel)
        builtin = layer == "public" and name in BUILTIN_NON_ARTIFACT
        doc_kind = "non_artifact" if builtin else "artifact"
        artifact_entries.append({
            "path": rel, "category": "document", "doc_kind": doc_kind,
            "source": "system", "layer": layer, "project": project, "ticket": ticket,
            "name": name, "created": stamp, "updated": stamp,
        })

    # 3) 旧频道消息：迁 logs/channels，日志/channel/system/public。
    if os.path.isdir(channel_dir):
        for name in sorted(os.listdir(channel_dir)):
            if not name.endswith(".jsonl"):
                continue
            src = os.path.join(channel_dir, name)
            if not os.path.isfile(src):
                continue
            rel = "channels/" + name
            dst_abs = os.path.join(logs_dir, rel)
            moves.append((src, dst_abs, "旧频道消息：channel → logs/channel/system"))
            mtime = os.path.getmtime(src)
            stamp = _iso(mtime)
            log_entries.append({
                "path": rel, "category": "log", "doc_kind": None, "source": "system",
                "layer": "public", "project": "", "ticket": "", "kind": "channel",
                "name": name, "created": stamp, "updated": stamp,
            })

    # 4) 合并既有清单（按 path 去重，保留已有 created）。
    knowledge_index = os.path.join(knowledge_dir, INDEX_NAME)
    artifact_index = os.path.join(artifacts_dir, INDEX_NAME)
    logs_index = os.path.join(logs_dir, INDEX_NAME)

    if apply:
        merged_knowledge = list(_load_index(knowledge_index))
        merged_artifact = list(_load_index(artifact_index))
        merged_log = list(_load_index(logs_index))
        for entry in knowledge_entries:
            _upsert(merged_knowledge, entry)
        for entry in artifact_entries:
            _upsert(merged_artifact, entry)
        for entry in log_entries:
            _upsert(merged_log, entry)
    else:
        merged_knowledge = knowledge_entries
        merged_artifact = artifact_entries
        merged_log = log_entries

    report = {
        "knowledge": merged_knowledge,
        "artifacts": merged_artifact,
        "logs": merged_log,
        "moves": moves,
    }

    if apply:
        for src, dst, _note in moves:
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.move(src, dst)
        _dump_index(knowledge_index, merged_knowledge)
        _dump_index(artifact_index, merged_artifact)
        _dump_index(logs_index, merged_log)

    return report


def main():
    parser = argparse.ArgumentParser(description="历史数据归类整改与清单回填")
    parser.add_argument("--root", required=True, help="agent 模块目录（镜像 modules/agent）")
    parser.add_argument("--apply", action="store_true", help="实写清单并执行搬迁；默认 dry-run")
    args = parser.parse_args()

    report = plan(args.root, args.apply)
    mode = "APPLY" if args.apply else "DRY-RUN"
    print("== %s 归类计划 ==" % mode)
    print("知识条目 %d；文档条目 %d；日志条目 %d；搬迁 %d 个文件" % (
        len(report["knowledge"]), len(report["artifacts"]),
        len(report["logs"]), len(report["moves"])))

    for entry in report["knowledge"]:
        print("  [knowledge] %s (%s/%s)" % (entry["path"], entry["layer"], entry["project"] or entry["ticket"] or "-"))
    for entry in report["artifacts"]:
        print("  [document]  %s [%s/%s] (%s/%s)" % (
            entry["path"], entry["doc_kind"], entry["source"],
            entry["layer"], entry["project"] or entry["ticket"] or "-"))
    for entry in report["logs"]:
        print("  [log]       %s [%s]" % (entry["path"], entry["kind"]))
    for src, dst, note in report["moves"]:
        print("  [move] %s -> %s (%s)" % (src, dst, note))


if __name__ == "__main__":
    main()
