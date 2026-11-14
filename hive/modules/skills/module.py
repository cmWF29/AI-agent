"""开源 Skill 管理模块。

只做三件事，保持和现有架构一致：
  1. 连接来源（本地目录 / GitHub 仓库或 tree / raw SKILL.md），把 Skill 包安装到
     data/skills/packages/<id>/；
  2. 把 SKILL.md 的元数据同步到 library.skills（技能库），不另造一套角色库结构；
  3. 由“Skill 拆解者”把 Skill 拆成 角色卡 + 技能卡 + 流程插件：角色是“谁来做”，
     Skill 是“怎么做”，流程插件是“交什么、怎么验”。

Skill 包本身不是模块，不直接拿 Context；它只被角色按提示词读取/执行。
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import time
import uuid

from ...kernel.api import ApiError, Module
from ...kernel.config import path_of
from ...kernel.tools import Tool
from ...kernel.store import ensure_dir, inside, valid_id


DEFAULT_SOURCES = [
    {"id": "anthropic-skills", "name": "Anthropic 官方 Skills", "type": "github",
     "url": "https://github.com/anthropics/skills",
     "note": "官方/示例集合；pptx、canvas-design 等可直接安装，注意各 Skill 自身许可证。"},
    {"id": "minimax-skills", "name": "MiniMax Skills", "type": "github",
     "url": "https://github.com/MiniMax-AI/skills",
     "note": "MIT 风格的技能集合，含 pptx-generator、multimodal 等。"},
    {"id": "superpowers", "name": "Superpowers Skills", "type": "github",
     "url": "https://github.com/obra/superpowers",
     "note": "社区高星 Skill 集合；适合用 tree URL 安装单个 Skill。"},
    {"id": "local", "name": "本地目录", "type": "local",
     "url": "",
     "note": "填本机 Skill 目录；必须以 SKILL.md 为入口。"},
]

EXAMPLES = [
    {"source": "https://github.com/anthropics/skills/tree/main/skills/pptx",
     "name": "Anthropic pptx", "kind": "ppt", "source_id": "anthropic-skills"},
    {"source": "https://github.com/anthropics/skills/tree/main/skills/canvas-design",
     "name": "Anthropic canvas-design", "kind": "image", "source_id": "anthropic-skills"},
    {"source": "https://github.com/MiniMax-AI/skills/tree/main/skills/pptx-generator",
     "name": "MiniMax pptx-generator", "kind": "ppt", "source_id": "minimax-skills"},
]

ROLE_ALIASES = {
    "pptx": "ppter", "ppt": "ppter", "slides": "ppter", "presentation": "ppter",
    "pptx-generator": "ppter", "ppt-agent": "ppter",
    "canvas-design": "visual-designer", "image-generation": "image-designer",
    "imagegen": "image-designer", "gif-sticker-maker": "visual-designer",
}


def _slug(text):
    s = re.sub(r"[^a-zA-Z0-9_\-\u4e00-\u9fff]+", "-", str(text or "")).strip("-").lower()
    return s[:48] or "skill"


def parse_frontmatter(text):
    """只解析 SKILL.md 常见的扁平 frontmatter，不引入 YAML 依赖。"""
    m = re.match(r"^\ufeff?---\s*\n(.*?)\n---\s*\n?", text, flags=re.S)
    if not m:
        return {}, text
    head = m.group(1)
    body = text[m.end():]
    out = {}
    for line in head.splitlines():
        if not line.strip() or line.lstrip().startswith("#") or ":" not in line:
            continue
        if line.startswith((" ", "\t")):
            continue
        k, v = line.split(":", 1)
        v = v.strip().strip('"').strip("'")
        if v.startswith("[") and v.endswith("]"):
            v = [x.strip().strip('"').strip("'") for x in v[1:-1].split(",") if x.strip()]
        out[k.strip()] = v
    return out, body


def _git():
    return shutil.which("git") or r"D:\Git\cmd\git.exe"


class Skills(Module):
    name = "skills"

    def setup(self):
        self.root = ensure_dir(path_of(self.cfg, "skills.root", "data/skills"))
        self.pkg_root = ensure_dir(os.path.join(self.root, "packages"))
        self.tmp_root = ensure_dir(os.path.join(self.root, "tmp"))
        cfg = self.cfg.get("skills") or {}
        self.sources = cfg.get("sources") or DEFAULT_SOURCES
        self.examples = cfg.get("examples") or EXAMPLES
        self.api.route("GET", "/api/skills/installed", name="installed")(self.installed_api)
        self.api.route("GET", "/api/skills/sources", name="sources")(self.sources_api)
        self.api.route("POST", "/api/skills/install", name="install")(self.install_api)
        self.api.route("POST", "/api/skills/decompose", name="decompose")(self.decompose_api)
        self.api.route("POST", "/api/skills/remove", name="remove")(self.remove_api)
        self.api.route("GET", "/api/skills/item", name="item")(self.item_api)
        self._register_tools()
        self.log.info("skills.ready", root=self.root, sources=len(self.sources))

    # ---------------- package helpers ----------------
    def _library(self):
        return self.ctx.api("library.upsert")

    def _record(self, rec):
        return self.ctx.api("library.upsert", kind="skills", item=rec)

    def _read_meta(self, sid):
        p = os.path.join(self.pkg_root, sid, "meta.json")
        try:
            with open(p, encoding="utf-8") as f:
                return json.load(f)
        except (OSError, ValueError):
            return None

    def _write_meta(self, sid, meta):
        p = os.path.join(self.pkg_root, sid, "meta.json")
        with open(p, "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False, indent=2)

    def _copy_tree(self, src, dst, sid):
        src = os.path.abspath(src)
        dst = os.path.abspath(dst)
        if not inside(src, os.path.join(src, "SKILL.md")) and not os.path.isfile(os.path.join(src, "SKILL.md")):
            raise ApiError("来源目录里没有 SKILL.md", code="no_skill_md")
        if os.path.realpath(dst).startswith(os.path.realpath(self.pkg_root) + os.sep) is False:
            raise ApiError("非法安装目录", code="bad_target")
        tmp = dst + ".tmp-" + uuid.uuid4().hex[:6]
        shutil.copytree(src, tmp, ignore=shutil.ignore_patterns(".git", "__pycache__", "*.pyc"))
        if os.path.isdir(dst):
            shutil.rmtree(dst)
        os.replace(tmp, dst)
        return dst

    def _find_skill_root(self, base):
        base = os.path.abspath(base)
        if os.path.isdir(base) and os.path.isfile(os.path.join(base, "SKILL.md")):
            return base
        found = []
        for root, dirs, files in os.walk(base):
            dirs[:] = [d for d in dirs if d not in (".git", "node_modules", "__pycache__")]
            if "SKILL.md" in files:
                found.append(root)
            if len(found) > 8:
                break
        if len(found) == 1:
            return found[0]
        if found:
            raise ApiError("来源里有多个 SKILL.md，请用 GitHub tree URL 指定具体 Skill", code="ambiguous_skill")
        raise ApiError("来源里没有 SKILL.md", code="no_skill_md")

    def _from_github(self, url):
        tree = re.match(r"https://github\.com/([^/]+)/([^/]+)(?:/tree/([^/]+)/(.*))?$", url)
        raw = re.match(r"https://raw\.githubusercontent\.com/([^/]+)/([^/]+)/([^/]+)/(.*)/SKILL\.md", url)
        tmp = ensure_dir(os.path.join(self.tmp_root, "gh-" + uuid.uuid4().hex[:8]))
        if raw:
            import urllib.request
            target = os.path.join(tmp, "SKILL.md")
            urllib.request.urlretrieve(url, target)
            return tmp, tmp
        if not tree:
            raise ApiError("只支持 GitHub 仓库/tree 链接或 raw SKILL.md 链接", code="bad_source")
        owner, repo, branch, path = tree.groups()
        git = _git()
        if not git or not os.path.isfile(git):
            raise ApiError("找不到 git，可改用本地目录安装", code="no_git")
        cmd = [git, "clone", "--depth", "1"]
        if branch:
            cmd += ["--branch", branch]
        cmd += ["https://github.com/%s/%s.git" % (owner, repo), tmp]
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        if p.returncode != 0:
            shutil.rmtree(tmp, ignore_errors=True)
            raise ApiError("git clone 失败：%s" % (p.stderr or p.stdout)[:300], code="clone_failed")
        if path:
            parts = path.replace("\\", "/").split("/")
            if os.path.isabs(path) or any(p == ".." or p.startswith("..") for p in parts):
                shutil.rmtree(tmp, ignore_errors=True)
                raise ApiError("GitHub 路径非法", code="bad_path")
        base = os.path.join(tmp, path or "")
        if not os.path.isdir(base):
            raise ApiError("GitHub 仓库里没有路径：%s" % (path or "/"), code="no_path")
        return self._find_skill_root(base), tmp

    # ---------------- install ----------------
    def install(self, source, sid="", overwrite=False):
        source = (source or "").strip()
        if not source:
            raise ApiError("source 不能为空", code="empty_source")
        tmp = None
        try:
            if os.path.isdir(source):
                skill_dir = self._find_skill_root(source)
                source_type = "local"
            elif source.startswith(("https://github.com/", "https://raw.githubusercontent.com/")):
                skill_dir, tmp = self._from_github(source)
                source_type = "github"
            else:
                raise ApiError("来源必须是本地目录或 GitHub 链接", code="bad_source")
            with open(os.path.join(skill_dir, "SKILL.md"), encoding="utf-8", errors="replace") as f:
                text = f.read()
            front, body = parse_frontmatter(text)
            name = str(front.get("name") or os.path.basename(skill_dir) or "")
            skill_id = _slug(sid or name)
            if not valid_id(skill_id):
                raise ApiError("Skill id 非法: %s" % skill_id, code="bad_id")
            dst = os.path.join(self.pkg_root, skill_id)
            if os.path.isdir(dst) and not overwrite:
                raise ApiError("Skill %s 已安装（overwrite=true 可更新）" % skill_id, status=409, code="exists")
            self._copy_tree(skill_dir, dst, skill_id)
            assets = []
            for root, dirs, files in os.walk(dst):
                dirs[:] = [d for d in dirs if d not in (".git", "__pycache__")]
                for f in files:
                    if f == "meta.json":
                        continue
                    rel = os.path.relpath(os.path.join(root, f), dst).replace("\\", "/")
                    if rel != "SKILL.md":
                        assets.append(rel)
            assets = sorted(assets)[:200]
            meta = {"id": skill_id, "name": name, "description": str(front.get("description") or ""),
                    "source": source, "source_type": source_type, "installed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "frontmatter": front, "assets": assets, "package": os.path.relpath(dst, self.root)}
            self._write_meta(skill_id, meta)
            self._record({"id": skill_id, "name": name, "cn": front.get("cn") or name,
                          "description": meta["description"], "body": body[:8000],
                          "source": source, "source_type": source_type, "package": meta["package"],
                          "assets": assets, "installed": True, "frontmatter": front,
                          "decomposed": False})
            self.emit("skills.installed", {"id": skill_id, "source": source, "type": source_type})
            self.log.info("skills.installed", id=skill_id, source=source, assets=len(assets))
            return {"skill": meta}
        finally:
            if tmp:
                shutil.rmtree(tmp, ignore_errors=True)

    # ---------------- decompose ----------------
    def decompose(self, sid, role_id="", overwrite=False, backend=""):
        meta = self._read_meta(sid)
        if not meta:
            raise ApiError("没有这个已安装 Skill: %s" % sid, code="no_skill")
        try:
            with open(os.path.join(self.pkg_root, sid, "SKILL.md"), encoding="utf-8", errors="replace") as f:
                text = f.read()
        except OSError:
            raise ApiError("Skill 包缺少 SKILL.md", code="no_skill_md")
        front, body = parse_frontmatter(text)
        role = _slug(role_id or front.get("role") or ROLE_ALIASES.get(sid, sid))
        cn = str(front.get("cn") or role)
        outputs = front.get("must_outputs") or front.get("outputs")
        if isinstance(outputs, str):
            outputs = [x.strip() for x in outputs.split(",") if x.strip()]
        if not outputs:
            if role == "ppter":
                outputs = ["**/*.pptx", "docs/**/*.md"]
            elif role in ("visual-designer", "image-designer"):
                outputs = ["**/*.png", "**/*.jpg", "**/*.pdf", "docs/**/*.md"]
            else:
                outputs = ["docs/**/*.md"]
        responsibilities = meta.get("description") or "按 %s 的 SKILL.md 完成可验证的交付" % sid
        prompt = (body or "").strip()[:6000]
        prompt += "\n\n执行约束：\n1) 先读 Skill 包里的 SKILL.md 和资源；2) 产物必须落到工作树；" \
                  "3) 不要编造已完成；4) 交付时写清验证命令/证据。\nSkill 包：%s" % os.path.join(self.pkg_root, sid)
        checks = [{"kind": "glob", "path": p} for p in outputs]
        try:
            res = self.ctx.api("library.design",
                               role=role, responsibility=responsibilities, must_outputs=outputs,
                               prompt=prompt, skills=[{"id": sid, "name": meta.get("name") or sid,
                                                       "body": body[:8000]}],
                               cn=cn, checks=checks, overwrite=bool(overwrite), backend=backend or "")
        except ApiError as exc:
            if exc.status == 409:
                return {"skill": sid, "role": role, "existing": True, "note": exc.message}
            raise
        # 给角色卡补上来源，便于 UI 区分“内置/拆解生成”
        card = dict(res.get("role") or {})
        card.update({"skill_id": sid, "skill_source": meta.get("source") or "",
                     "source": "skill-decomposer"})
        self.ctx.api("library.upsert", kind="roles", item=card)
        meta["decomposed"] = True
        meta["role"] = role
        meta["must_outputs"] = outputs
        self._write_meta(sid, meta)
        self._record({"id": sid, "name": meta.get("name") or sid, "cn": cn,
                      "description": meta.get("description") or "", "body": body[:8000],
                      "source": meta.get("source") or "", "source_type": meta.get("source_type") or "",
                      "package": meta.get("package"), "assets": meta.get("assets") or [],
                      "installed": True, "frontmatter": meta.get("frontmatter") or {},
                      "decomposed": True, "role": role, "must_outputs": outputs})
        self.emit("skills.decomposed", {"id": sid, "role": role})
        return {"skill": sid, "role": role, "flow": res.get("flow") or {}, "outputs": outputs,
                "decomposed_by": "skill-decomposer"}

    # ---------------- API ----------------
    def installed_api(self, payload):
        records = []
        for sid in sorted(os.listdir(self.pkg_root)) if os.path.isdir(self.pkg_root) else []:
            if not os.path.isdir(os.path.join(self.pkg_root, sid)):
                continue
            m = self._read_meta(sid)
            if m:
                records.append(m)
        return {"items": records, "total": len(records)}

    def sources_api(self, payload):
        return {"sources": self.sources, "examples": self.examples}

    def install_api(self, payload):
        res = self.install(payload.get("source") or "", sid=payload.get("id") or "",
                           overwrite=bool(payload.get("overwrite")))
        if payload.get("decompose"):
            res["decompose"] = self.decompose(res["skill"]["id"], payload.get("role") or "",
                                              overwrite=bool(payload.get("overwrite")),
                                              backend=payload.get("backend") or "")
        return res

    def decompose_api(self, payload):
        return self.decompose(payload.get("id") or payload.get("skill") or "",
                              payload.get("role") or "", overwrite=bool(payload.get("overwrite")),
                              backend=payload.get("backend") or "")

    def remove_api(self, payload):
        sid = payload.get("id") or payload.get("skill") or ""
        if not valid_id(sid):
            raise ApiError("非法 Skill id", code="bad_id")
        p = os.path.join(self.pkg_root, sid)
        if not inside(self.pkg_root, p):
            raise ApiError("非法路径", code="bad_path")
        if os.path.isdir(p):
            shutil.rmtree(p)
        try:
            self._record({"id": sid, "name": sid, "installed": False, "decomposed": False})
        except ApiError:
            pass
        self.emit("skills.removed", {"id": sid})
        return {"skill": sid, "removed": True}

    def item_api(self, payload):
        sid = payload.get("id") or ""
        m = self._read_meta(sid)
        if not m:
            raise ApiError("没有这个 Skill: %s" % sid, status=404, code="no_skill")
        return {"skill": m}

    def _register_tools(self):
        def install_tool(args, tctx):
            res = self.install(args.get("source") or "", args.get("id") or "",
                               bool(args.get("overwrite")))
            return "已安装 Skill %s（来源 %s）；如需拆成角色+流程，再调 skill_decompose。" % (
                res["skill"]["id"], res["skill"]["source_type"])
        self.ctx.tools.register(Tool(
            "skill_install", "安装开源 Skill（本地目录/GitHub tree/raw SKILL.md）到技能库。",
            {"type": "object", "properties": {
                "source": {"type": "string"}, "id": {"type": "string"},
                "overwrite": {"type": "boolean"}}, "required": ["source"]},
            install_tool, origin=self.name))

        def sources_tool(args, tctx):
            return "\n".join("%s: %s" % (s["name"], s.get("url") or s.get("type")) for s in self.sources)
        self.ctx.tools.register(Tool(
            "skill_sources", "列出可连接的 Skill 来源。", {"type": "object", "properties": {}},
            sources_tool, origin=self.name))

        def decompose_tool(args, tctx):
            res = self.decompose(args.get("id") or "", args.get("role") or "",
                                 bool(args.get("overwrite")), backend=args.get("backend") or "")
            if res.get("existing"):
                return "角色 %s 已存在，未覆盖。" % res.get("role")
            return "已拆解：Skill %s -> 角色 %s；流程校验 %d 项。" % (
                res["skill"], res["role"], len(res.get("outputs") or []))
        self.ctx.tools.register(Tool(
            "skill_decompose", "Skill 拆解者：把 SKILL.md 拆成角色卡+技能卡+流程插件。",
            {"type": "object", "properties": {
                "id": {"type": "string"}, "role": {"type": "string"}, "overwrite": {"type": "boolean"},
                "backend": {"type": "string", "enum": ["", "api", "claude-code"]}},
             "required": ["id"]},
            decompose_tool, origin=self.name))
