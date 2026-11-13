"""运维模块：网页上的固定命令（重启/停止/回退/查版本/自检）。

与 watchdog 之间不靠 RPC，靠“控制文件”这个最简单的消息通道：
  ops 写 data/control/cmd-*.json  ->  watchdog 轮询并执行
这样 agent 崩了也不影响控制面，watchdog 崩了也不影响 agent。
"""
from __future__ import annotations

import json
import os
import subprocess
import threading
import time

from ..kernel.api import ApiError, Module
from ..kernel.config import path_of
from ..kernel.store import ensure_dir, inside, read_json, safe_id
from ..version import __version__

SERVICE_NAME = "hive-watchdog"


class Ops(Module):
    name = "ops"

    def setup(self):
        self.control_dir = ensure_dir(path_of(self.cfg, "ops.control_dir", "data/control"))
        self.lock = threading.Lock()
        self.log.info("ops.ready", control_dir=self.control_dir)

        self.api.route("GET", "/api/ops/status")(self.status)
        self.api.route("POST", "/api/ops/restart")(self.restart)
        self.api.route("POST", "/api/ops/stop")(self.stop_all)
        self.api.route("POST", "/api/ops/rollback")(self.rollback)
        self.api.route("GET", "/api/ops/versions")(self.versions)
        self.api.route("GET", "/api/ops/config")(self.config_view)
        self.api.route("POST", "/api/ops/selftest")(self.selftest)
        self.api.route("POST", "/api/ops/llm/ping")(self.llm_ping)
        self.api.route("POST", "/api/ops/service")(self.service)
        self.api.route("GET", "/api/ops/files")(self.files)
        self.api.route("GET", "/api/ops/file")(self.file_view)

    # ---------------- 控制文件 ----------------
    def _control(self, name, extra=None):
        payload = {"cmd": name, "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "by": "web"}
        payload.update(extra or {})
        path = os.path.join(self.control_dir, "cmd-%s-%s.json" % (int(time.time() * 1000), safe_id(name)))
        with self.lock:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False)
        self.emit("ops.control", payload)
        self.log.info("ops.control", cmd=name, path=path)
        return path

    def _watchdog_state(self):
        return read_json(os.path.join(self.control_dir, "watchdog.json"), {}) or {}

    # ---------------- 状态 ----------------
    def status(self, payload):
        kernel = self.ctx.state.get("kernel")
        wd = self._watchdog_state()
        hb_age = None
        if wd.get("ts"):
            try:
                hb_age = int(time.time() - float(wd["ts"]))
            except (TypeError, ValueError):
                hb_age = None
        sessions = self.ctx.api("sessions.list") if "sessions" in self.ctx.modules else {"items": []}
        tickets = self.ctx.api("tickets.list") if "tickets" in self.ctx.modules else {"items": []}
        return {
            "version": __version__,
            "pid": os.getpid(),
            "started_at": self.ctx.started_at,
            "uptime_sec": int(time.time() - (self.ctx.state["http"].started_at or time.time())) if self.ctx.state.get("http") else 0,
            "python": __import__("sys").version.split()[0],
            "watchdog": {"state": wd, "heartbeat_age_sec": hb_age, "alive": hb_age is not None and hb_age < 30},
            "sessions": len(sessions.get("items", [])),
            "tickets": len(tickets.get("items", [])),
            "llm": {
                "model": self.ctx.state["llm"].model,
                "base_url": self.ctx.state["llm"].base_url,
                "has_key": bool(self.ctx.state["llm"].api_key),
                "usage": self.ctx.state["llm"].usage,
            },
            "server": {"port": self.cfg["server"]["port"], "token_set": bool(self.cfg["server"].get("token"))},
        }

    # ---------------- 固定命令 ----------------
    def restart(self, payload):
        self._control("restart")
        return {"action": "restart", "note": "已通知 watchdog 重启 agent（约 2-5 秒）"}

    def stop_all(self, payload):
        self._control("stop")
        target = os.path.join(self.control_dir, "stop")

        def _later():
            time.sleep(1.5)
            ran = False
            for cmd in (["systemctl", "stop", SERVICE_NAME], ["service", SERVICE_NAME, "stop"]):
                try:
                    subprocess.run(cmd, capture_output=True, timeout=20)
                    ran = True
                    break
                except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
                    continue
            if not ran:
                # 没有 systemd 的场景（本地调试）：让 watchdog 自己退出
                try:
                    with open(target, "w", encoding="utf-8") as f:
                        f.write("stop")
                except OSError:
                    pass
            self.log.info("ops.stop.systemctl", ran=ran)
        threading.Thread(target=_later, name="ops-stop", daemon=True).start()
        return {"action": "stop", "note": "已请求彻底停止 watchdog+agent（先回包再执行，页面可能短时失联）"}

    def rollback(self, payload):
        import re
        target = (payload.get("target") or "HEAD^").strip()
        if not re.match(r"^[A-Za-z0-9_.~/^@{}-]{1,80}$", target):
            raise ApiError("非法的回退目标: %r" % target, code="bad_target")
        self._control("rollback", {"target": target})
        return {"action": "rollback", "target": target,
                "note": "已通知 watchdog 回退到 %s（回退前会自动存档当前改动，不会丢）" % target}

    def _repo_root(self):
        root = self.cfg.get("repo")
        if not root:
            cand = os.path.abspath(self.cfg["root"])
            root = cand if os.path.exists(os.path.join(cand, ".git")) else os.path.dirname(cand)
        return os.path.realpath(root)

    def files(self, payload):
        """agent 自身源码/配置浏览（只读）。跳过 .git / data 运行数据。"""
        base = self._repo_root()
        rel = (payload.get("path") or "").strip("/")
        target = os.path.realpath(os.path.join(base, rel))
        if not inside(base, target):
            raise ApiError("路径越界", status=400, code="bad_path")
        if not os.path.isdir(target):
            raise ApiError("目录不存在", status=404, code="no_dir")
        items = []
        for name in sorted(os.listdir(target)):
            if name in (".git", "__pycache__", "data"):
                continue
            full = os.path.join(target, name)
            items.append({"name": name, "path": os.path.relpath(full, base),
                          "type": "dir" if os.path.isdir(full) else "file",
                          "size": os.path.getsize(full) if os.path.isfile(full) else 0})
        return {"root": base, "path": rel, "items": items}

    def file_view(self, payload):
        base = self._repo_root()
        rel = (payload.get("path") or "").strip("/")
        if rel.startswith("data/") or rel.startswith(".git/"):
            raise ApiError("运行数据/版本库不开放浏览", status=403, code="forbidden")
        target = os.path.realpath(os.path.join(base, rel))
        if not inside(base, target) or not os.path.isfile(target):
            raise ApiError("文件不存在", status=404, code="no_file")
        if os.path.getsize(target) > 512 * 1024:
            raise ApiError("文件过大（>512KB）", status=413, code="too_big")
        try:
            text = open(target, encoding="utf-8").read()
        except UnicodeDecodeError:
            text = ""
        return {"path": rel, "text": text, "bytes": os.path.getsize(target)}

    def versions(self, payload):
        """版本列表：网页的“版本管理”直接消费，可指定任意一个版本回退。"""
        # 代码仓库：优先 config.repo；否则在 root / root 的上一级里找带 .git 的那个
        root = self.cfg.get("repo")
        if not root:
            cand = os.path.abspath(self.cfg["root"])
            root = cand if os.path.exists(os.path.join(cand, ".git")) else os.path.dirname(cand)
        n = min(int((payload or {}).get("limit") or 20), 60)
        try:
            head = subprocess.run(["git", "-C", root, "rev-parse", "--short", "HEAD"],
                                  capture_output=True, text=True, timeout=10)
            log = subprocess.run(["git", "-C", root, "log", "-%d" % n,
                                  "--pretty=%h\t%H\t%ad\t%an\t%s", "--date=iso"],
                                 capture_output=True, text=True, timeout=10)
            branches = subprocess.run(["git", "-C", root, "branch", "--list", "autosave/*"],
                                      capture_output=True, text=True, timeout=10)
            status = subprocess.run(["git", "-C", root, "status", "--porcelain"],
                                    capture_output=True, text=True, timeout=10)
        except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
            return {"version": __version__, "git": {"available": False, "error": repr(exc)}}
        current = (head.stdout or "").strip()
        commits = []
        for line in (log.stdout or "").splitlines():
            parts = line.split("\t")
            if len(parts) < 5:
                continue
            commits.append({"short": parts[0], "hash": parts[1], "date": parts[2],
                            "author": parts[3], "subject": parts[4],
                            "current": parts[0] == current})
        return {
            "version": __version__,
            "git": {
                "available": True,
                "head": current,
                "commits": commits,
                "log": ["%s %s %s" % (c["short"], c["date"][:16], c["subject"]) for c in commits],
                "autosave_branches": [b.strip() for b in (branches.stdout or "").splitlines() if b.strip()],
                "dirty": bool((status.stdout or "").strip()),
            },
        }

    def config_view(self, payload):
        cfg = json.loads(json.dumps(self.cfg))
        cfg.get("llm", {}).pop("api_key", None)
        cfg.get("server", {}).pop("token", None)
        cfg.get("server", {}).pop("web_password", None)
        cfg["llm"]["api_key_present"] = bool(self.ctx.state["llm"].api_key)
        cfg.pop("root", None)
        return {"config": cfg}

    def selftest(self, payload):
        checks = {}
        try:
            r = self.ctx.api("sessions.list")
            checks["sessions_api"] = {"ok": True, "sessions": r.get("total", 0)}
        except Exception as exc:
            checks["sessions_api"] = {"ok": False, "error": repr(exc)}
        try:
            r = self.ctx.api("knowledge.overview")
            checks["knowledge_api"] = {"ok": True, "root": r.get("root")}
        except Exception as exc:
            checks["knowledge_api"] = {"ok": False, "error": repr(exc)}
        checks["bus"] = {"ok": True, "stats": self.ctx.bus.stats()}
        checks["llm"] = {"key_present": bool(self.ctx.state["llm"].api_key)}
        if payload.get("ping_llm"):
            checks["llm_ping"] = self.ctx.state["llm"].ping()
        return {"checks": checks, "version": __version__}

    def llm_ping(self, payload):
        return self.ctx.state["llm"].ping()

    def service(self, payload):
        action = payload.get("action") or "status"
        if action not in ("status", "start", "stop", "restart"):
            raise ApiError("action 只能是 status/start/stop/restart")
        try:
            cmd = ["systemctl", action, SERVICE_NAME]
            if action == "status":
                cmd = ["systemctl", "is-active", SERVICE_NAME]
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
            return {"action": action, "code": res.returncode, "out": (res.stdout or "").strip(), "err": (res.stderr or "").strip()}
        except FileNotFoundError:
            return {"action": action, "available": False, "note": "本机没有 systemd"}
