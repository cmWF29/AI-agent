"""仓库同步模块：只读仓库状态 + fetch 远端引用，不碰工作区文件。

真正的 deploy / merge 仍由生产钩子执行；这里提供网页/内核可查询的统一入口。
"""
from __future__ import annotations

import os
import shutil
import subprocess

from ...kernel.api import Module, ApiError


def _git_bin():
    found = shutil.which("git")
    if found:
        return found
    for p in (r"D:\Git\cmd\git.exe", r"C:\Program Files\Git\cmd\git.exe"):
        if os.path.isfile(p):
            return p
    return "git"


class GitSync(Module):
    name = "gitsync"

    def setup(self):
        self.api.route("GET", "/api/gitsync/status", name="status")(self.status)
        self.api.route("POST", "/api/gitsync/fetch", name="fetch")(self.fetch)
        self.log.info("gitsync.ready")

    def _git(self, args, timeout=30):
        proc = subprocess.run(
            [_git_bin()] + args,
            cwd=self.ctx.cfg["root"],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        if proc.returncode != 0:
            raise ApiError((proc.stderr or "git 失败").strip(), 500, "git_failed")
        return (proc.stdout or "").strip()

    def status(self, payload):
        return {
            "branch": self._git(["branch", "--show-current"]),
            "head": self._git(["rev-parse", "--short", "HEAD"]),
            "dirty": bool(self._git(["status", "--porcelain"])),
            "remote": self._git(["remote", "-v"]).splitlines()[:4],
        }

    def fetch(self, payload):
        # 只有显式 POST 才动远端引用；不执行 merge/reset/push。
        self._git(["fetch", "--all", "--prune"], timeout=60)
        return {"ok": True, "head": self._git(["rev-parse", "--short", "HEAD"])}
