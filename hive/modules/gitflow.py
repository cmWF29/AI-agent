"""工单级 git 工作流（需求 2）。

每个项目有一份 bare 仓库：data/projects/<pid>/repo.git
每个工单从它 clone 出自己的工作树：data/tickets/<tid>/repo，分支 ticket/<tid>
角色在这个工作树里改代码 —— 改完由 agent（不是靠人）commit + push。

并行的工单互不干扰：各写各的分支；收口时把分支合并回 main。
合并/推送前先 rebase 到最新 main：
  * 能自动合 → 继续，返回 ahead 数；
  * 冲突      → 不硬来：abort 掉，把冲突文件清单返回给工单，
                工单进入 conflict 状态，PM 必须“重新审视 + 重跑测试”才能再合。
这就是需求里说的“解决冲突后工单内必须重新审视/测试”的落点。

对外 API：
  POST /api/gitflow/project/init    建项目仓库
  POST /api/gitflow/ticket/init     给工单建分支工作树
  POST /api/gitflow/ticket/sync     commit + rebase + push
  GET  /api/gitflow/ticket/status   看分支/脏文件/落后多少
  POST /api/gitflow/ticket/merge    合回 main（冲突则返回冲突清单）
  GET  /api/gitflow/list            所有项目仓库概览
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess

from ..kernel.api import ApiError, Module
from ..kernel.config import path_of
from ..kernel.store import ensure_dir
from ..kernel.tools import Tool

GIT_ENV = {
    "GIT_AUTHOR_NAME": "Hive Agent",
    "GIT_AUTHOR_EMAIL": "agent@hive.local",
    "GIT_COMMITTER_NAME": "Hive Agent",
    "GIT_COMMITTER_EMAIL": "agent@hive.local",
    "GIT_TERMINAL_PROMPT": "0",
}

CONFLICT_HINTS = ("CONFLICT", "Automatic merge failed", "could not apply", "Resolve all conflicts")


class GitFlow(Module):
    name = "gitflow"

    def setup(self):
        self.projects_root = path_of(self.cfg, "projects.root", "data/projects")
        self.tickets_root = path_of(self.cfg, "tickets.root", "data/tickets")
        g = self.cfg.get("gitflow") if isinstance(self.cfg.get("gitflow"), dict) else {}
        self.enabled = bool(g.get("enabled", True))
        self.prefix = g.get("branch_prefix") or "ticket/"
        self.main = g.get("main_branch") or "main"
        self.remote = g.get("remote_name") or "origin"
        self.log.info("gitflow.ready", enabled=self.enabled)
        if not self._git_available():
            self.enabled = False
            self.log.warn("gitflow.disabled", reason="本机没有 git")

        self.api.route("POST", "/api/gitflow/project/init", name="project_init")(self.project_init_api)
        self.api.route("POST", "/api/gitflow/ticket/init", name="ticket_init")(self.ticket_init_api)
        self.api.route("POST", "/api/gitflow/ticket/sync", name="ticket_sync")(self.ticket_sync_api)
        self.api.route("GET", "/api/gitflow/ticket/status", name="ticket_status")(self.ticket_status_api)
        self.api.route("POST", "/api/gitflow/ticket/merge", name="ticket_merge")(self.ticket_merge_api)
        self.api.route("GET", "/api/gitflow/list", name="list")(self.list_api)
        self._register_tools()

    # ---------------- 基础 ----------------
    def _git_available(self):
        try:
            subprocess.run(["git", "--version"], capture_output=True, timeout=8)
            return True
        except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
            return False

    def _run(self, args, cwd=None, timeout=60):
        env = {k: v for k, v in os.environ.items() if k not in ("GIT_DIR", "GIT_WORK_TREE")}
        env.update(GIT_ENV)
        try:
            proc = subprocess.run(["git"] + args, cwd=cwd, capture_output=True, text=True,
                                  timeout=timeout, env=env)
        except (FileNotFoundError, subprocess.TimeoutExpired, OSError) as exc:
            return {"ok": False, "code": -1, "out": "", "err": repr(exc)}
        return {"ok": proc.returncode == 0, "code": proc.returncode,
                "out": (proc.stdout or "").strip(), "err": (proc.stderr or "").strip()}

    def bare(self, project):
        return os.path.join(self.projects_root, project, "repo.git")

    def main_tree(self, project):
        return os.path.join(self.projects_root, project, "main")

    def ticket_tree(self, ticket):
        return os.path.join(self.tickets_root, ticket, "repo")

    # ---------------- 项目仓库 ----------------
    def init_project(self, project, force=False):
        if not self.enabled:
            return {"enabled": False}
        bare = self.bare(project)
        ensure_dir(os.path.dirname(bare))
        if not os.path.isdir(bare):
            r = self._run(["init", "--bare", "-b", self.main, bare])
            if not r["ok"]:
                # 老 git（2.25 及以前）不支持 init -b，默认分支会是 master
                r = self._run(["init", "--bare", bare])
            if not r["ok"]:
                raise ApiError("git init 失败: %s" % r["err"], code="git_init_failed")
        # 不管用哪种方式建出来的，都把默认分支钉死在 main（否则后面 origin/main 永远不存在）。
        self._run(["symbolic-ref", "HEAD", "refs/heads/" + self.main], cwd=bare)
        has_main = self._run(["rev-parse", "--verify", "refs/heads/" + self.main], cwd=bare)["ok"]
        has_master = self._run(["rev-parse", "--verify", "refs/heads/master"], cwd=bare)["ok"]
        if has_master and not has_main:
            self._run(["branch", "-m", "master", self.main], cwd=bare)
        main = self.main_tree(project)
        if not os.path.isdir(main):
            r = self._run(["clone", bare, main])
            if not r["ok"]:
                raise ApiError("git clone 失败: %s" % r["err"], code="git_clone_failed")
            self._run(["checkout", "-B", self.main], cwd=main)
            ensure_dir(os.path.join(main, "docs"))
            with open(os.path.join(main, "README.md"), "w", encoding="utf-8") as f:
                f.write("# %s\n\n本仓库由 Hive Agent 管理：每个工单一个分支，收口后合回 %s。\n" % (project, self.main))
            with open(os.path.join(main, ".gitignore"), "w", encoding="utf-8") as f:
                f.write("data/\n*.pyc\n__pycache__/\n")
            self._run(["add", "-A"], cwd=main)
            self._run(["commit", "-m", "init: project repo"], cwd=main)
            self._run(["push", self.remote, self.main], cwd=main)
        self.emit("gitflow.project.ready", {"project": project})
        return {"enabled": True, "bare": bare, "main": main}

    # ---------------- 工单工作树 ----------------
    def init_ticket(self, ticket, project):
        if not self.enabled:
            return {"enabled": False}
        self.init_project(project)
        tree = self.ticket_tree(ticket)
        branch = self.prefix + ticket
        if os.path.isdir(os.path.join(tree, ".git")):
            return {"enabled": True, "tree": tree, "branch": branch, "existing": True}
        ensure_dir(os.path.dirname(tree))
        if os.path.isdir(tree):
            shutil.rmtree(tree, ignore_errors=True)
        r = self._run(["clone", self.bare(project), tree])
        if not r["ok"]:
            raise ApiError("git clone 工单仓库失败: %s" % r["err"], code="git_clone_failed")
        r = self._run(["checkout", "-b", branch], cwd=tree)
        if not r["ok"]:
            r = self._run(["checkout", branch], cwd=tree)
        # 注意：不要往每个工单分支写同名文件（比如 .hive-ticket），
        # 否则多个工单合并回 main 时会在“同一路径不同内容”上必然冲突。
        self.emit("gitflow.ticket.ready", {"ticket": ticket, "project": project, "branch": branch})
        self.log.info("gitflow.ticket.init", ticket=ticket, branch=branch)
        return {"enabled": True, "tree": tree, "branch": branch, "existing": False}

    def ticket_status(self, ticket):
        tree = self.ticket_tree(ticket)
        if not os.path.isdir(os.path.join(tree, ".git")):
            return {"enabled": self.enabled, "exists": False, "tree": tree}
        branch = self._run(["rev-parse", "--abbrev-ref", "HEAD"], cwd=tree)["out"]
        dirty = self._run(["status", "--porcelain"], cwd=tree)["out"]
        ahead = self._run(["rev-list", "--count", "HEAD"] + ([]), cwd=tree)
        last = self._run(["log", "-1", "--pretty=%h %s"], cwd=tree)["out"]
        self._run(["fetch", self.remote], cwd=tree, timeout=30)
        behind = self._run(["rev-list", "--count", "HEAD..%s/%s" % (self.remote, self.main)], cwd=tree)
        files = {}
        try:
            st = subprocess.run(["git", "diff", "--name-only", "HEAD"], cwd=tree, capture_output=True,
                                text=True, timeout=20)
            files["changed"] = [f for f in (st.stdout or "").splitlines() if f]
        except Exception:
            files["changed"] = []
        return {"enabled": self.enabled, "exists": True, "tree": tree, "branch": branch,
                "dirty": dirty, "dirty_files": len(dirty.splitlines()) if dirty else 0,
                "dirty_list": dirty.splitlines()[:20],
                "ahead_of_main": int(ahead["out"] or 0) if ahead["ok"] else 0,
                "behind_main": int(behind["out"] or 0) if behind["ok"] else 0,
                "last": last, "changed": files["changed"][:20],
                "head": self._run(["rev-parse", "--short", "HEAD"], cwd=tree)["out"]}

    def sync_ticket(self, ticket, message=""):
        """commit + rebase 到最新 main + push。冲突则 abort 并把清单返回。"""
        if not self.enabled:
            return {"enabled": False}
        tree = self.ticket_tree(ticket)
        if not os.path.isdir(os.path.join(tree, ".git")):
            raise ApiError("工单 %s 还没有 git 工作树" % ticket, status=409, code="no_tree")
        branch = self.prefix + ticket
        self._run(["add", "-A"], cwd=tree)
        msg = message or ("ticket %s: sync" % ticket)
        commit = self._run(["commit", "-m", msg], cwd=tree)
        committed = commit["ok"]
        if not commit["ok"] and "nothing to commit" not in commit["out"] + commit["err"]:
            return {"ok": False, "stage": "commit", "error": commit["err"] or commit["out"]}
        fetch = self._run(["fetch", self.remote], cwd=tree, timeout=30)
        if not fetch["ok"]:
            return {"ok": False, "stage": "fetch", "error": fetch["err"]}
        rebase = self._run(["rebase", "%s/%s" % (self.remote, self.main)], cwd=tree, timeout=60)
        if not rebase["ok"]:
            conflicts = self._conflict_files(tree)
            self._run(["rebase", "--abort"], cwd=tree)
            self.emit("gitflow.conflict", {"ticket": ticket, "files": conflicts})
            self.log.warn("gitflow.conflict", ticket=ticket, files=conflicts)
            return {"ok": False, "stage": "rebase", "conflict": conflicts,
                    "hint": "先解决冲突（人工/角色在工单工作树里改），再重跑测试，然后重新 sync",
                    "error": rebase["err"] or rebase["out"]}
        push = self._run(["push", "-u", self.remote, branch], cwd=tree, timeout=60)
        if not push["ok"]:
            if "rejected" in push["err"] or "non-fast-forward" in push["err"]:
                return {"ok": False, "stage": "push", "error": push["err"],
                        "hint": "远端分支已前进，请重新 sync"}
            return {"ok": False, "stage": "push", "error": push["err"]}
        head = self._run(["rev-parse", "--short", "HEAD"], cwd=tree)["out"]
        self.emit("gitflow.pushed", {"ticket": ticket, "branch": branch, "head": head,
                                     "committed": committed})
        self.log.info("gitflow.pushed", ticket=ticket, branch=branch, head=head)
        return {"ok": True, "stage": "done", "branch": branch, "head": head, "committed": committed}

    def _conflict_files(self, tree):
        out = self._run(["diff", "--name-only", "--diff-filter=U"], cwd=tree)
        files = [f for f in (out["out"] or "").splitlines() if f]
        if files:
            return files
        st = self._run(["status", "--porcelain"], cwd=tree)["out"]
        return [line[3:] for line in st.splitlines() if re.match(r"(UU|AA|DU|UD|AU|UA)", line)]

    def merge_ticket(self, ticket, project):
        """把工单分支合回 main（在项目主工作树里做，冲突就返回清单）。"""
        if not self.enabled:
            return {"enabled": False}
        main = self.main_tree(project)
        branch = self.prefix + ticket
        # 必须显式 refspec：git fetch origin ticket/x 只会写 FETCH_HEAD，
        # 不会产生 origin/ticket/x 引用，后面 merge 就会“not something we can merge”。
        fetch = self._run(["fetch", self.remote,
                           "%s:refs/remotes/%s/%s" % (branch, self.remote, branch)], cwd=main, timeout=30)
        self._run(["fetch", self.remote, self.main], cwd=main, timeout=30)
        if not fetch["ok"]:
            return {"ok": False, "stage": "fetch", "error": fetch["err"]}
        self._run(["checkout", self.main], cwd=main)
        # 主工作树是派生副本：直接对齐远端 main，避免本地落后导致的假冲突
        self._run(["reset", "--hard", "%s/%s" % (self.remote, self.main)], cwd=main)
        r = self._run(["merge", "--no-ff", "%s/%s" % (self.remote, branch),
                       "-m", "merge: %s" % ticket], cwd=main, timeout=60)
        if not r["ok"]:
            conflicts = self._conflict_files(main)
            self._run(["merge", "--abort"], cwd=main)
            self.emit("gitflow.merge.conflict", {"ticket": ticket, "project": project, "files": conflicts})
            return {"ok": False, "stage": "merge", "conflict": conflicts,
                    "hint": "冲突未合入；工单需要重新审视/改代码/重跑测试后再合"}
        if not r["ok"] and not conflicts:
            # 不是内容冲突，而是 git 层面的失败：一样不许当作“已合并”
            return {"ok": False, "stage": "merge", "error": r["err"] or r["out"],
                    "hint": "合并失败，先排查 git 状态再重试"}
        push = self._run(["push", self.remote, self.main], cwd=main, timeout=60)
        head = self._run(["rev-parse", "--short", "HEAD"], cwd=main)["out"]
        self.emit("gitflow.merged", {"ticket": ticket, "project": project, "head": head})
        self.log.info("gitflow.merged", ticket=ticket, project=project, head=head)
        return {"ok": push["ok"], "stage": "merged", "head": head, "push_error": "" if push["ok"] else push["err"]}

    # ---------------- API ----------------
    def project_init_api(self, payload):
        return {"repo": self.init_project(payload["project"], force=bool(payload.get("force")))}

    def ticket_init_api(self, payload):
        return {"repo": self.init_ticket(payload["ticket"], payload["project"])}

    def ticket_sync_api(self, payload):
        return {"result": self.sync_ticket(payload["ticket"], payload.get("message") or "")}

    def ticket_status_api(self, payload):
        return {"status": self.ticket_status(payload["ticket"])}

    def ticket_merge_api(self, payload):
        return {"result": self.merge_ticket(payload["ticket"], payload["project"])}

    def list_api(self, payload):
        items = []
        base = self.projects_root
        for pid in sorted(os.listdir(base)) if os.path.isdir(base) else []:
            bare = self.bare(pid)
            if not os.path.isdir(bare):
                continue
            branches = self._run(["branch", "--list"], cwd=bare)
            items.append({"project": pid, "bare": bare,
                          "branches": [b.strip(" *") for b in (branches["out"] or "").splitlines()]})
        return {"enabled": self.enabled, "items": items}

    # ---------------- 工具 ----------------
    def _register_tools(self):
        tools = self.ctx.tools

        def sync_tool(args, tctx):
            tid = args.get("ticket") or tctx.session.get("ticket")
            if not tid:
                return "缺少 ticket"
            res = self.sync_ticket(tid, args.get("message") or "")
            if res.get("conflict"):
                return "推送遇到冲突（%d 个文件）：%s。先解决冲突并重跑测试，再 sync。" % (
                    len(res["conflict"]), ", ".join(res["conflict"]))
            if not res.get("ok"):
                return "同步失败（%s）：%s" % (res.get("stage"), res.get("error"))
            return "已提交并推送分支 %s（%s）" % (res.get("branch"), res.get("head"))

        def status_tool(args, tctx):
            tid = args.get("ticket") or tctx.session.get("ticket")
            s = self.ticket_status(tid)
            if not s.get("exists"):
                return "工单 %s 没有 git 工作树（%s）" % (tid, s.get("tree"))
            return ("分支 %s | HEAD %s | 落后 main %s | 改动 %d 个文件 | 最近: %s" % (
                s["branch"], s["head"], s["behind_main"], s["dirty_files"], s["last"]))

        def merge_tool(args, tctx):
            tid = args.get("ticket") or tctx.session.get("ticket")
            res = self.merge_ticket(tid, args.get("project") or tctx.session.get("project") or "")
            if res.get("conflict"):
                return "合并冲突（%d 个文件）：%s —— 需要重新审视并重跑测试后再合。" % (
                    len(res["conflict"]), ", ".join(res["conflict"]))
            return "已合入 %s（%s）" % (self.main, res.get("head"))

        tools.register(Tool("git_sync", "把工单工作树的改动 commit + rebase + push 到远端分支。",
                            {"type": "object", "properties": {
                                "ticket": {"type": "string"}, "message": {"type": "string"}}},
                            sync_tool, origin=self.name))
        tools.register(Tool("git_status", "看工单分支状态（脏文件/落后 main 多少）。",
                            {"type": "object", "properties": {"ticket": {"type": "string"}}},
                            status_tool, origin=self.name))
        tools.register(Tool("git_merge", "把工单分支合回 main（冲突会返回清单）。",
                            {"type": "object", "properties": {
                                "ticket": {"type": "string"}, "project": {"type": "string"}}},
                            merge_tool, origin=self.name))
