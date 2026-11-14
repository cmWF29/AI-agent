"""基础执行工具包：shell / read_file / write_file / grep / http_get。

工具全部注册到内核的 ToolRegistry，React 循环不关心它们从哪来。
"""
from __future__ import annotations

import os
import re
import subprocess
import urllib.request

from ...kernel.api import Module
from ...kernel.store import ensure_dir, inside
from ...kernel.tools import Tool, ToolError


def _resolve(workspace, path):
    if not path:
        raise ToolError("path 必填")
    base = os.path.realpath(workspace)
    p = path if os.path.isabs(path) else os.path.join(base, path)
    p = os.path.realpath(p)
    if not inside(base, p):
        raise ToolError("路径越界（只能读写本会话工作目录）: %s" % path)
    return p


class ToolPack(Module):
    name = "toolpack"

    def setup(self):
        cfg = self.cfg["tools"]
        self.allow_shell = bool(cfg.get("allow_shell", True))
        self.shell_timeout = int(cfg.get("shell_timeout", 120))
        self.max_read = int(cfg.get("max_read_bytes", 2 * 1024 * 1024))
        self.deny = [re.compile(p) for p in (cfg.get("deny_patterns") or [])]
        self.builtin_deny = [
            re.compile(r"rm\s+-rf\s+/\s*($|[;&|])"),
            re.compile(r"mkfs\."),
            re.compile(r"dd\s+if=.*of=/dev/[sv]d"),
            re.compile(r":\(\)\s*\{\s*:\|:&\s*\};:"),
        ]
        self._register()
        self.log.info("toolpack.ready", shell=self.allow_shell, timeout=self.shell_timeout)

    def _register(self):
        reg = self.ctx.tools
        reg.register(Tool("shell", "在会话工作目录执行 shell 命令（输出过大时会被落盘，只给你路径）。",
                          {"type": "object", "properties": {
                              "command": {"type": "string"},
                              "cwd": {"type": "string", "description": "可选，默认会话工作目录"},
                              "timeout": {"type": "integer"},
                          }, "required": ["command"]},
                          self.shell, origin=self.name))
        reg.register(Tool("read_file", "读取文件片段（按行号），默认 200 行。",
                          {"type": "object", "properties": {
                              "path": {"type": "string"},
                              "offset": {"type": "integer", "description": "起始行号，1 开始"},
                              "limit": {"type": "integer", "description": "读取行数，默认 200"},
                          }, "required": ["path"]},
                          self.read_file, origin=self.name))
        reg.register(Tool("write_file", "写入文件（覆盖或追加），自动建目录。",
                          {"type": "object", "properties": {
                              "path": {"type": "string"},
                              "content": {"type": "string"},
                              "mode": {"type": "string", "enum": ["overwrite", "append"]},
                          }, "required": ["path", "content"]},
                          self.write_file, origin=self.name))
        reg.register(Tool("grep", "在文件/目录里做正则检索，返回 路径:行号:内容。",
                          {"type": "object", "properties": {
                              "pattern": {"type": "string"},
                              "path": {"type": "string", "description": "文件或目录，默认工作目录"},
                              "glob": {"type": "string", "description": "如 *.py"},
                              "max_matches": {"type": "integer"},
                              "ignore_case": {"type": "boolean"},
                          }, "required": ["pattern"]},
                          self.grep, origin=self.name))
        reg.register(Tool("http_get", "发起 GET 请求（用于查文档/健康检查）。",
                          {"type": "object", "properties": {
                              "url": {"type": "string"},
                              "timeout": {"type": "integer"},
                          }, "required": ["url"]},
                          self.http_get, origin=self.name))

    # ---------------- shell ----------------
    def shell(self, args, tctx):
        if not self.allow_shell:
            raise ToolError("shell 工具被配置禁用（tools.allow_shell=false）")
        cmd = (args.get("command") or "").strip()
        if not cmd:
            raise ToolError("command 不能为空")
        for pat in list(self.deny) + self.builtin_deny:
            if pat.search(cmd):
                raise ToolError("命令命中禁止规则，已拒绝执行: %s" % cmd[:80])
        cwd = args.get("cwd") or tctx.workspace
        cwd = os.path.realpath(cwd)
        if not inside(os.path.realpath(tctx.workspace), cwd):
            raise ToolError("cwd 越界（只能在本会话工作目录内执行）: %s" % cwd)
        ensure_dir(cwd)
        timeout = int(args.get("timeout") or self.shell_timeout)
        env = dict(os.environ)
        env.setdefault("HIVE_SESSION", tctx.session_id)
        t0 = __import__("time").time()
        try:
            proc = subprocess.run(cmd, shell=True, cwd=cwd, capture_output=True, text=True,
                                  timeout=timeout, env=env, errors="replace")
            out = proc.stdout or ""
            err = proc.stderr or ""
        except subprocess.TimeoutExpired as exc:
            out = (exc.stdout or "") if isinstance(exc.stdout, str) else ""
            err = (exc.stderr or "") if isinstance(exc.stderr, str) else ""
            text = "命令超时（>%ds）\nstdout:\n%s\nstderr:\n%s" % (timeout, out, err)
            return {"ok": False, "text": text, "meta": {"timeout": True, "cwd": cwd}}
        elapsed = int((__import__("time").time() - t0) * 1000)
        text = "$ %s\n(cwd=%s, exit=%d, %dms)\n%s" % (cmd, cwd, proc.returncode, elapsed, out)
        if err:
            text += "\n[stderr]\n" + err
        return {"ok": proc.returncode == 0, "text": text,
                "meta": {"exit_code": proc.returncode, "cwd": cwd, "ms": elapsed}}

    # ---------------- 文件 ----------------
    def read_file(self, args, tctx):
        path = _resolve(tctx.workspace, args.get("path"))
        if not os.path.isfile(path):
            raise ToolError("文件不存在: %s" % path)
        size = os.path.getsize(path)
        if size > self.max_read:
            raise ToolError("文件过大（%d bytes），请用 grep 或 shell 的 head/sed 定位" % size)
        offset = max(1, int(args.get("offset") or 1))
        limit = min(int(args.get("limit") or 200), 1000)
        lines = []
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            for no, line in enumerate(f, 1):
                if no < offset:
                    continue
                if no >= offset + limit:
                    break
                lines.append("%6d\t%s" % (no, line.rstrip("\n")))
        total = sum(1 for _ in open(path, "r", encoding="utf-8", errors="replace"))
        return "%s  (行 %d-%d / 共 %d 行)\n%s" % (
            path, offset, min(offset + len(lines) - 1, total), total, "\n".join(lines))

    def write_file(self, args, tctx):
        path = _resolve(tctx.workspace, args.get("path"))
        ensure_dir(os.path.dirname(path))
        mode = "a" if args.get("mode") == "append" else "w"
        content = args.get("content") or ""
        with open(path, mode, encoding="utf-8") as f:
            f.write(content)
        return {"text": "已写入 %s（%d 字，mode=%s）" % (path, len(content), mode),
                "meta": {"path": path, "chars": len(content)}}

    # ---------------- 检索 ----------------
    def grep(self, args, tctx):
        pattern = args.get("pattern")
        if not pattern:
            raise ToolError("pattern 必填")
        flags = re.IGNORECASE if args.get("ignore_case") else 0
        try:
            rx = re.compile(pattern, flags)
        except re.error as exc:
            raise ToolError("正则非法: %s" % exc)
        base = _resolve(tctx.workspace, args.get("path") or ".")
        glob_pat = args.get("glob")
        max_matches = min(int(args.get("max_matches") or 200), 2000)
        matches = []
        files = []
        if os.path.isfile(base):
            files = [base]
        else:
            for dirpath, dirnames, filenames in os.walk(base):
                dirnames[:] = [d for d in dirnames if d not in (".git", "__pycache__", "node_modules", ".venv")]
                for name in filenames:
                    if glob_pat and not __import__("fnmatch").fnmatch(name, glob_pat):
                        continue
                    files.append(os.path.join(dirpath, name))
        for path in files[:8000]:
            try:
                if os.path.getsize(path) > self.max_read:
                    continue
                with open(path, "r", encoding="utf-8", errors="replace") as f:
                    for no, line in enumerate(f, 1):
                        if rx.search(line):
                            matches.append("%s:%d: %s" % (path, no, line.rstrip()[:300]))
                            if len(matches) >= max_matches:
                                raise StopIteration
            except StopIteration:
                matches.append("... 命中数已达上限 %d" % max_matches)
                break
            except (OSError, UnicodeError):
                continue
        if not matches:
            return "没有命中：/ %s in %s" % (pattern, base)
        return "\n".join(matches)

    # ---------------- HTTP ----------------
    def http_get(self, args, tctx):
        url = args.get("url")
        if not url:
            raise ToolError("url 必填")
        timeout = int(args.get("timeout") or 30)
        req = urllib.request.Request(url, headers={"User-Agent": "hive-agent/1.0"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                body = resp.read(200000).decode("utf-8", "replace")
                return "HTTP %s %s\n%s" % (resp.status, url, body[:5000])
        except Exception as exc:
            raise ToolError("请求失败: %r" % exc)
