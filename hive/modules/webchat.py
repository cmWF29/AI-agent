"""网页对话桥：把浏览器里的一句话，变成一次 agent CLI 调用。

严格按要求：网页不直接调 LLM，而是“登录 VPS 执行 agent cli 命令”，
把用户输入作为参数交给 CLI；CLI 再把话送到常驻的秘书会话，拿到回复。

这样网页只是遥控器，真正的会话状态一直在 daemon 里。
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
import uuid

from ..kernel.api import ApiError, Module

MAX_JOBS = 60


class WebChat(Module):
    name = "webchat"

    def setup(self):
        self.jobs = {}
        self.lock = threading.Lock()
        self.cli_timeout = int(self.cfg.get("webchat", {}).get("cli_timeout", 900)) if isinstance(self.cfg.get("webchat"), dict) else 900
        self.secretary_id = self.cfg["secretary"].get("session_id") or "secretary"
        self.log.info("webchat.ready", secretary=self.secretary_id)

        self.api.route("POST", "/api/chat/send")(self.send)
        self.api.route("GET", "/api/chat/job/{job_id}")(self.job)
        self.api.route("GET", "/api/chat/history")(self.history)
        self.api.route("POST", "/api/chat/compact")(self.compact)
        self.api.route("POST", "/api/chat/secretary/reset")(self.reset)

    # ---------------- 发送 ----------------
    def send(self, payload):
        text = (payload.get("text") or "").strip()
        if not text:
            raise ApiError("text 不能为空", code="empty_text")
        job_id = "c-" + uuid.uuid4().hex[:10]
        job = {
            "id": job_id,
            "text": text,
            "status": "running",
            "created": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "reply": "",
            "log": "",
            "via": payload.get("via") or "cli",
            "t0": time.time(),
        }
        with self.lock:
            self.jobs[job_id] = job
            self._trim()
        target = self._run_cli if job["via"] == "cli" else self._run_direct
        threading.Thread(target=target, args=(job,), name="chat-" + job_id, daemon=True).start()
        self.emit("webchat.send", {"job": job_id, "chars": len(text), "via": job["via"]})
        return {"job_id": job_id, "status": "running"}

    def _trim(self):
        if len(self.jobs) <= MAX_JOBS:
            return
        old = sorted(self.jobs.values(), key=lambda j: j["t0"])[: len(self.jobs) - MAX_JOBS]
        for j in old:
            self.jobs.pop(j["id"], None)

    def _run_cli(self, job):
        root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        cmd = [
            sys.executable, "-m", "hive.cli", "ask",
            "--session", self.secretary_id,
            "--text", job["text"],
            "--url", "http://127.0.0.1:%d" % int(self.cfg["server"]["port"]),
            "--token", self.cfg["server"].get("token") or "",
            "--json",
            "--timeout", str(self.cli_timeout - 30),
        ]
        env = dict(os.environ)
        env["PYTHONPATH"] = root + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
        try:
            proc = subprocess.run(cmd, cwd=root, capture_output=True, text=True, timeout=self.cli_timeout, env=env)
            out = (proc.stdout or "").strip()
            err = (proc.stderr or "").strip()
            job["log"] = (out[-4000:] + ("\n[stderr]\n" + err[-2000:] if err else ""))
            parsed = None
            try:
                parsed = json.loads(out.splitlines()[-1]) if out else None
            except ValueError:
                parsed = None
            if parsed and isinstance(parsed, dict):
                job["reply"] = parsed.get("reply") or ""
                job["status"] = "done" if parsed.get("ok", True) else "error"
                if not parsed.get("ok", True):
                    job["error"] = parsed.get("error") or "cli 失败"
            elif out:
                job["reply"] = out
                job["status"] = "done"
            else:
                job["status"] = "error"
                job["error"] = err[-400:] or "CLI 无输出（exit=%s）" % proc.returncode
        except subprocess.TimeoutExpired:
            job["status"] = "error"
            job["error"] = "CLI 超时（%ss）" % self.cli_timeout
        except Exception as exc:
            job["status"] = "error"
            job["error"] = repr(exc)
        finally:
            job["ms"] = int((time.time() - job["t0"]) * 1000)
            self.emit("webchat.done", {"job": job["id"], "status": job["status"], "ms": job["ms"]})

    def _run_direct(self, job):
        try:
            res = self.ctx.api("sessions.ask", session=self.secretary_id, text=job["text"],
                               timeout=self.cli_timeout - 30)
            job["reply"] = res.get("reply") or ""
            job["status"] = "done" if res.get("status") != "timeout" else "error"
            if res.get("status") == "timeout":
                job["error"] = "会话超时"
        except ApiError as exc:
            job["status"] = "error"
            job["error"] = exc.message
        finally:
            job["ms"] = int((time.time() - job["t0"]) * 1000)
            self.emit("webchat.done", {"job": job["id"], "status": job["status"], "ms": job["ms"]})

    # ---------------- 查询 ----------------
    def job(self, payload):
        job = self.jobs.get(payload["job_id"])
        if not job:
            raise ApiError("job 不存在: %s" % payload["job_id"], status=404, code="no_job")
        return {"job": {k: v for k, v in job.items() if k != "t0"}}

    def history(self, payload):
        limit = min(int(payload.get("limit") or 20), 100)
        try:
            res = self.ctx.api("sessions.messages", session_id=self.secretary_id, limit=limit)
            return {"items": res.get("items", []), "total": res.get("total", 0)}
        except ApiError:
            return {"items": [], "total": 0}

    def compact(self, payload):
        return self.ctx.api("sessions.compact", session_id=self.secretary_id)

    def reset(self, payload):
        res = self.ctx.api("sessions.ensure", reset=True)
        return {"session": res.get("session")}
