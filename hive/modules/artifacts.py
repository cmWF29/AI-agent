"""交付件模块 —— 三层归档（公共 / 项目 / 工单）+ 体积统计 + 压缩。

需求 9 / 17 / 20：
  * 交付件不是散落在工单工作目录里，而是按层级归档：
        data/artifacts/public/...                     公共级（跨项目可复用）
        data/artifacts/projects/<pid>/...             项目级
        data/artifacts/projects/<pid>/tickets/<tid>/  工单级（路径自带工单号，肉眼可辨）
  * 工单结单时把工作目录整体归档进工单层，并写 index.json（文件清单+大小+摘要）；
  * 归档超过 compress_after_days 天的工单，自动压成 .tar.gz（保留 index），
  * 健康自检直接读 stats()（三层总量 + 最大的几个工单 + 压缩收益）。

对外 API：
  GET  /api/artifacts/list        列某一层
  GET  /api/artifacts/file        读文件（文本或 base64）
  POST /api/artifacts/write       往某一层写文件（PM/角色沉淀用）
  POST /api/artifacts/archive     把工单工作目录归档进工单层
  POST /api/artifacts/compress    压缩某个工单层（或全部过期工单）
  GET  /api/artifacts/stats       体积统计（健康页用）
"""
from __future__ import annotations

import base64
import json
import os
import shutil
import time
import tarfile

from ..kernel.api import ApiError, Module
from ..kernel.config import path_of
from ..kernel.store import ensure_dir, valid_id
from ..kernel.tools import Tool

SKIP_DIRS = {".git", "__pycache__", "node_modules", ".venv", "venv", "repo"}
MAX_FILE = 512 * 1024


def _now():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _human(n):
    for unit in ("B", "K", "M", "G"):
        if n < 1024 or unit == "G":
            return ("%.1f%s" % (n, unit)) if unit != "B" else "%dB" % n
        n /= 1024.0
    return "%.1fG" % n


class Artifacts(Module):
    name = "artifacts"

    def setup(self):
        self.root = ensure_dir(path_of(self.cfg, "artifacts.root", "data/artifacts"))
        self.cfg_a = self.cfg.get("artifacts") if isinstance(self.cfg.get("artifacts"), dict) else {}
        import threading
        self._archive_lock = threading.RLock()
        for sub in ("public",):
            ensure_dir(os.path.join(self.root, sub))
        self.log.info("artifacts.ready", root=self.root)

        self.api.route("GET", "/api/artifacts/list", name="list")(self.list_api)
        self.api.route("GET", "/api/artifacts/file", name="file")(self.file_api)
        self.api.route("POST", "/api/artifacts/write", name="write")(self.write_api)
        self.api.route("POST", "/api/artifacts/archive", name="archive")(self.archive_api)
        self.api.route("POST", "/api/artifacts/compress", name="compress")(self.compress_api)
        self.api.route("GET", "/api/artifacts/stats", name="stats")(self.stats_api)
        self._register_tools()

    # ---------------- 路径 ----------------
    def base_of(self, layer, project="", ticket=""):
        layer = (layer or "public").strip()
        if layer == "public":
            return os.path.join(self.root, "public")
        if layer == "project":
            if not valid_id(project):
                raise ApiError("非法 project id", status=400, code="bad_project")
            return os.path.join(self.root, "projects", project)
        if layer == "ticket":
            if not (valid_id(project) and valid_id(ticket)):
                raise ApiError("非法 project/ticket id", status=400, code="bad_scope")
            return os.path.join(self.root, "projects", project, "tickets", ticket)
        raise ApiError("layer 只能是 public/project/ticket", code="bad_layer")

    def _safe(self, base, rel):
        rel = (rel or "").strip().lstrip("/")
        base_real = os.path.realpath(base)
        p = os.path.realpath(os.path.join(base_real, rel))
        if p != base_real and not p.startswith(base_real + os.sep):
            raise ApiError("非法路径（越界）", status=400, code="bad_path")
        return p, rel

    # ---------------- 归档 ----------------
    def archive_ticket(self, ticket, project, source_dir, paths=None):
        """把工单工作目录复制进工单层，并写 index.json。paths 给定时只归档这些相对路径。"""
        with self._archive_lock:
            return self._archive_ticket(ticket, project, source_dir, paths)

    def _archive_ticket(self, ticket, project, source_dir, paths=None):
        dest = self.base_of("ticket", project=project, ticket=ticket)
        # 先写 staging 目录，成功后再整体替换；中途失败不会毁掉上一次归档
        staging = dest + ".tmp"
        shutil.rmtree(staging, ignore_errors=True)
        ensure_dir(staging)
        files = []
        wanted = set((p or "").replace("\\", "/").lstrip("/") for p in paths) if paths is not None else None
        if source_dir and os.path.isdir(source_dir):
            for dirpath, dirnames, filenames in os.walk(source_dir):
                dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
                for fn in filenames:
                    src = os.path.join(dirpath, fn)
                    rel = os.path.relpath(src, source_dir)
                    if wanted is not None and rel.replace(os.sep, "/") not in wanted:
                        continue
                    if rel.startswith("repo" + os.sep):
                        continue
                    # 角色各自的工作目录在 workspace/<role-N>/ 下，归档时去掉这层前缀，
                    # 让工单层里看到的是 docs/report.md 这种干净路径。
                    parts = rel.split(os.sep)
                    if parts and parts[0] == "workspace" and len(parts) > 1:
                        rel = os.sep.join(parts[1:])
                    try:
                        size = os.path.getsize(src)
                    except OSError:
                        continue
                    target = os.path.join(staging, rel)
                    ensure_dir(os.path.dirname(target))
                    try:
                        shutil.copy2(src, target)
                    except OSError:
                        continue
                    files.append({"path": rel.replace(os.sep, "/"), "size": size})
        index = {"ticket": ticket, "project": project, "archived": _now(),
                 "files": files, "bytes": sum(f["size"] for f in files), "compressed": False}
        self._write_index(staging, index)
        backup = dest + ".old"
        shutil.rmtree(backup, ignore_errors=True)
        try:
            if os.path.exists(dest):
                shutil.move(dest, backup)
            shutil.move(staging, dest)
        except OSError:
            if not os.path.exists(dest) and os.path.exists(backup):
                shutil.move(backup, dest)
            raise
        shutil.rmtree(backup, ignore_errors=True)
        self.emit("artifacts.archived", {"ticket": ticket, "project": project,
                                         "files": len(files), "bytes": index["bytes"]})
        self.log.info("artifacts.archived", ticket=ticket, files=len(files), bytes=index["bytes"])
        return index

    def _write_index(self, dest, index):
        try:
            with open(os.path.join(dest, "index.json"), "w", encoding="utf-8") as f:
                json.dump(index, f, ensure_ascii=False, indent=2)
        except OSError:
            pass

    def _index_any(self, project, ticket):
        dest = self.base_of("ticket", project=project, ticket=ticket)
        idx = self._read_index(dest)
        if idx:
            return idx, dest
        sibling = os.path.join(self.root, "projects", project, "tickets", ticket + ".index.json")
        try:
            with open(sibling, "r", encoding="utf-8") as f:
                return json.load(f), dest
        except (OSError, ValueError):
            return None, dest

    def _read_index(self, dest):
        p = os.path.join(dest, "index.json")
        if not os.path.exists(p):
            return None
        try:
            with open(p, "r", encoding="utf-8") as f:
                return json.load(f)
        except (OSError, ValueError):
            return None

    def compress_ticket(self, project, ticket):
        dest = self.base_of("ticket", project=project, ticket=ticket)
        idx = self._read_index(dest) or {"ticket": ticket, "project": project, "files": []}
        if idx.get("compressed"):
            return {"ticket": ticket, "already": True}
        tar_path = dest + ".tar.gz"
        before = self._tree_size(dest)
        try:
            with tarfile.open(tar_path, "w:gz") as tar:
                tar.add(dest, arcname=ticket)
        except (OSError, tarfile.TarError) as exc:
            raise ApiError("压缩失败: %s" % exc, code="compress_failed")
        after = os.path.getsize(tar_path)
        shutil.rmtree(dest, ignore_errors=True)
        idx["compressed"] = True
        idx["tar"] = os.path.basename(tar_path)
        idx["bytes_before"] = before
        idx["bytes_after"] = after
        # 压缩后 index 放在同级目录，便于列表仍然能显示“已压缩”
        try:
            with open(os.path.join(self.root, "projects", project, "tickets", ticket + ".index.json"),
                      "w", encoding="utf-8") as f:
                json.dump(idx, f, ensure_ascii=False, indent=2)
        except OSError:
            pass
        self.emit("artifacts.compressed", {"ticket": ticket, "before": before, "after": after})
        return {"ticket": ticket, "bytes_before": before, "bytes_after": after,
                "ratio": round(after / before, 3) if before else 1.0, "tar": tar_path}

    def _tree_size(self, path):
        total = 0
        for dirpath, dirnames, filenames in os.walk(path):
            dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
            for fn in filenames:
                try:
                    total += os.path.getsize(os.path.join(dirpath, fn))
                except OSError:
                    pass
        return total

    # ---------------- 查询 ----------------
    def list_files(self, layer, project="", ticket="", limit=300):
        base = self.base_of(layer, project=project, ticket=ticket)
        if not os.path.isdir(base):
            if layer == "ticket" and project and ticket:
                idx, _ = self._index_any(project, ticket)
                if idx:
                    files = idx.get("files") or []
                    return {"layer": layer, "root": base, "compressed": True,
                            "items": [{"path": f.get("path"), "size": f.get("size") or 0,
                                       "mtime": idx.get("archived") or ""} for f in files[:limit]],
                            "total": len(files), "bytes": idx.get("bytes_after") or idx.get("bytes") or 0}
            return {"layer": layer, "root": base, "items": [], "total": 0, "bytes": 0}
        items = []
        total = 0
        total_bytes = 0
        for dirpath, dirnames, filenames in os.walk(base):
            dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
            for fn in filenames:
                p = os.path.join(dirpath, fn)
                try:
                    st = os.stat(p)
                except OSError:
                    continue
                total += 1
                total_bytes += st.st_size
                if len(items) < limit:
                    items.append({"path": os.path.relpath(p, base).replace(os.sep, "/"),
                                  "size": st.st_size,
                                  "mtime": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(st.st_mtime))})
        items.sort(key=lambda i: (i["path"].count("/"), i["path"]))
        return {"layer": layer, "root": base, "items": items, "total": total, "bytes": total_bytes}

    def list_api(self, payload):
        layer = payload.get("layer") or "public"
        return self.list_files(layer, payload.get("project") or "", payload.get("ticket") or "",
                                int(payload.get("limit") or 300))

    def file_api(self, payload):
        layer = payload.get("layer") or "public"
        base = self.base_of(layer, payload.get("project") or "", payload.get("ticket") or "")
        p, rel = self._safe(base, payload.get("path"))
        raw = None
        size = 0
        if os.path.isfile(p):
            size = os.path.getsize(p)
            with open(p, "rb") as f:
                raw = f.read(min(size, MAX_FILE))
        elif layer == "ticket" and payload.get("ticket"):
            # 压缩后的工单：从 tar 里按成员读取，网页仍然能查看
            idx, dest = self._index_any(payload.get("project") or "", payload.get("ticket"))
            if idx and os.path.isfile(dest + ".tar.gz"):
                member = payload["ticket"] + "/" + rel
                try:
                    with tarfile.open(dest + ".tar.gz", "r:gz") as tar:
                        info = tar.getmember(member)
                        size = int(info.size)
                        fp = tar.extractfile(info)
                        raw = fp.read(min(size, MAX_FILE)) if fp else b""
                except (KeyError, OSError, tarfile.TarError):
                    raise ApiError("文件不存在: %s" % rel, status=404, code="no_file")
        if raw is None:
            raise ApiError("文件不存在: %s" % rel, status=404, code="no_file")
        try:
            text = raw.decode("utf-8")
            enc = "utf-8"
        except UnicodeDecodeError:
            text = base64.b64encode(raw).decode("ascii")
            enc = "base64"
        return {"layer": layer, "path": rel, "size": size, "truncated": size > MAX_FILE,
                "encoding": enc, "text": text}

    def write_api(self, payload):
        layer = payload.get("layer") or "public"
        base = self.base_of(layer, payload.get("project") or "", payload.get("ticket") or "")
        rel = (payload.get("path") or "").strip().lstrip("/")
        if not rel:
            raise ApiError("path 必填", code="missing_path")
        p, rel = self._safe(base, rel)
        ensure_dir(os.path.dirname(p))
        with open(p, "w", encoding="utf-8") as f:
            f.write(payload.get("content") or "")
        self.emit("artifacts.written", {"layer": layer, "path": rel,
                                        "project": payload.get("project") or "",
                                        "ticket": payload.get("ticket") or "",
                                        "session": payload.get("session") or "",
                                        "ts": time.time()})
        return {"layer": layer, "path": rel, "bytes": os.path.getsize(p)}

    def archive_api(self, payload):
        return {"index": self.archive_ticket(payload["ticket"], payload["project"], payload.get("source"),
                                              paths=payload.get("paths"))}

    def compress_api(self, payload):
        if payload.get("ticket"):
            return {"result": self.compress_ticket(payload["project"], payload["ticket"])}
        days = int(payload.get("days") or self.cfg_a.get("compress_after_days", 7))
        done = []
        projects_dir = os.path.join(self.root, "projects")
        for pid in os.listdir(projects_dir) if os.path.isdir(projects_dir) else []:
            tdir = os.path.join(projects_dir, pid, "tickets")
            if not os.path.isdir(tdir):
                continue
            for tid in os.listdir(tdir):
                full = os.path.join(tdir, tid)
                if not os.path.isdir(full):
                    continue
                # 只压缩已结单工单，避免把仍在跑的交付件拿走
                try:
                    st = self.ctx.api("tickets.get", ticket_id=tid)["ticket"].get("status")
                except ApiError:
                    st = None
                if st not in (None, "closed"):
                    continue
                age_days = (time.time() - os.path.getmtime(full)) / 86400.0
                if age_days >= days:
                    try:
                        done.append(self.compress_ticket(pid, tid))
                    except ApiError:
                        continue
        return {"compressed": done, "days": days}

    def stats_api(self, payload=None):
        layers = {}
        biggest = []
        for name, path in (("public", os.path.join(self.root, "public")),
                           ("projects", os.path.join(self.root, "projects"))):
            layers[name] = {"bytes": self._tree_size(path) if os.path.isdir(path) else 0,
                            "path": path}
        projects_dir = os.path.join(self.root, "projects")
        for pid in os.listdir(projects_dir) if os.path.isdir(projects_dir) else []:
            tdir = os.path.join(projects_dir, pid, "tickets")
            if not os.path.isdir(tdir):
                continue
            for tid in os.listdir(tdir):
                full = os.path.join(tdir, tid)
                if os.path.isdir(full):
                    biggest.append({"project": pid, "ticket": tid, "bytes": self._tree_size(full),
                                    "compressed": False})
                elif tid.endswith(".tar.gz"):
                    try:
                        biggest.append({"project": pid, "ticket": tid[:-7],
                                        "bytes": os.path.getsize(full), "compressed": True})
                    except OSError:
                        pass
        biggest.sort(key=lambda i: -i["bytes"])
        total = sum(v["bytes"] for v in layers.values())
        try:
            free = shutil.disk_usage(self.root).free
        except OSError:
            free = 0
        threshold = int(self.cfg_a.get("compress_threshold_mb", 200)) * 1024 * 1024
        return {"root": self.root, "total_bytes": total, "total_human": _human(total),
                "layers": layers, "biggest": biggest[:10], "disk_free": free,
                "need_compress": total > threshold, "threshold_bytes": threshold,
                "compressed": len([b for b in biggest if b["compressed"]])}

    # ---------------- 工具 ----------------
    def _register_tools(self):
        tools = self.ctx.tools

        def write_tool(args, tctx):
            res = self.write_api({
                "session": tctx.session_id,
                "layer": args.get("layer") or "ticket",
                "project": args.get("project") or tctx.session.get("project") or "",
                "ticket": args.get("ticket") or tctx.session.get("ticket") or "",
                "path": args.get("path") or "",
                "content": args.get("content") or "",
            })
            return "已写入 %s 层：%s（%d bytes）" % (res["layer"], res["path"], res["bytes"])

        def list_tool(args, tctx):
            layer = args.get("layer") or "ticket"
            res = self.list_files(layer,
                                  args.get("project") or tctx.session.get("project") or "",
                                  args.get("ticket") or tctx.session.get("ticket") or "")
            if not res["items"]:
                return "%s 层暂无文件（%s）" % (layer, res["root"])
            return "\n".join("%s (%dB)" % (i["path"], i["size"]) for i in res["items"][:80])

        def stats_tool(args, tctx):
            s = self.stats_api()
            return "交付件总量 %s；工单层最大：%s" % (
                s["total_human"], ", ".join("%s/%s=%s" % (b["project"], b["ticket"], _human(b["bytes"]))
                                            for b in s["biggest"][:5]) or "-")

        tools.register(Tool(
            "artifact_write", "把交付件写到指定层级（ticket/project/public），路径自带工单号。",
            {"type": "object", "properties": {
                "layer": {"type": "string", "enum": ["ticket", "project", "public"]},
                "path": {"type": "string", "description": "相对路径，如 docs/spec.md"},
                "content": {"type": "string"},
                "project": {"type": "string"},
                "ticket": {"type": "string"},
            }, "required": ["path", "content"]},
            write_tool, origin=self.name))

        tools.register(Tool(
            "artifact_list", "列出某一层已归档的交付件。",
            {"type": "object", "properties": {
                "layer": {"type": "string", "enum": ["ticket", "project", "public"]},
                "project": {"type": "string"}, "ticket": {"type": "string"},
            }},
            list_tool, origin=self.name))

        tools.register(Tool(
            "artifact_stats", "查看交付件三层体积统计（含压缩情况）。",
            {"type": "object", "properties": {}},
            stats_tool, origin=self.name))
