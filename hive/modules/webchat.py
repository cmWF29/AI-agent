"""网页桥 —— 群聊式控制台的后端。

两个职责：
1) 发消息：网页不直接调 LLM，而是“登录 VPS 执行 agent CLI 命令”（需求 4、6），
   CLI 再把话送到会话里。秘书群发到常驻秘书，工单群发到该工单的 PM。
2) 读消息：把“秘书 + 各工单里的 PM/角色”的发言聚合成一条时间线（群聊），
   全部通过 sessions.* / tickets.* 的对外 API 取，不碰别的模块的存储。

对外 API：
  POST /api/chat/send            发消息（payload.group 决定进哪个群）
  GET  /api/chat/job/{job_id}    查一次发送的结果
  GET  /api/chat/history         秘书群历史（兼容旧前端）
  POST /api/chat/compact         压缩秘书上下文
  POST /api/chat/secretary/reset 重置秘书会话
  GET  /api/web/groups           群列表（秘书 + 各工单 + 项目）
  GET  /api/web/timeline         某个群的时间线（支持 since_ts 增量）
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
        cfg = self.cfg.get("webchat") if isinstance(self.cfg.get("webchat"), dict) else {}
        self.cli_timeout = int(cfg.get("cli_timeout", 900))
        self.secretary_id = self.cfg["secretary"].get("session_id") or "secretary"
        self.log.info("webchat.ready", secretary=self.secretary_id)

        self.api.route("POST", "/api/chat/send", name="send")(self.send)
        self.api.route("GET", "/api/chat/job/{job_id}", name="job")(self.job)
        self.api.route("GET", "/api/chat/history", name="history")(self.history)
        self.api.route("POST", "/api/chat/compact", name="compact")(self.compact)
        self.api.route("POST", "/api/chat/secretary/reset", name="reset")(self.reset)
        self.api.route("GET", "/api/web/groups", name="groups")(self.groups)
        self.api.route("GET", "/api/web/timeline", name="timeline")(self.timeline)

    # ---------------- 发送 ----------------
    def send(self, payload):
        text = (payload.get("text") or "").strip()
        if not text:
            raise ApiError("text 不能为空", code="empty_text")
        group = (payload.get("group") or self.secretary_id).strip()
        job_id = "c-" + uuid.uuid4().hex[:10]
        job = {
            "id": job_id,
            "group": group,
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
        if group.startswith("T-") or group.startswith("ticket:"):
            ticket = group.split(":", 1)[-1]
            target = self._run_ticket if job["via"] == "cli" else self._run_ticket_direct
            threading.Thread(target=target, args=(job, ticket), name="chat-" + job_id, daemon=True).start()
        else:
            target = self._run_cli if job["via"] == "cli" else self._run_direct
            threading.Thread(target=target, args=(job,), name="chat-" + job_id, daemon=True).start()
        self.emit("webchat.send", {"job": job_id, "group": group, "chars": len(text), "via": job["via"]})
        return {"job_id": job_id, "status": "running", "group": group}

    def _trim(self):
        if len(self.jobs) <= MAX_JOBS:
            return
        old = sorted(self.jobs.values(), key=lambda j: j["t0"])[: len(self.jobs) - MAX_JOBS]
        for j in old:
            self.jobs.pop(j["id"], None)

    def _cli(self, argv):
        """跑一条 hive.cli 命令：网页永远只是遥控器。"""
        root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        cmd = [sys.executable, "-m", "hive.cli"] + argv
        env = dict(os.environ)
        env["PYTHONPATH"] = root + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
        return subprocess.run(cmd, cwd=root, capture_output=True, text=True,
                              timeout=self.cli_timeout, env=env)

    def _parse(self, job, proc):
        out = (proc.stdout or "").strip()
        err = (proc.stderr or "").strip()
        job["log"] = (out[-4000:] + ("\n[stderr]\n" + err[-2000:] if err else ""))
        parsed = None
        try:
            parsed = json.loads(out.splitlines()[-1]) if out else None
        except (ValueError, IndexError):
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

    def _run_cli(self, job):
        base = ["--url", "http://127.0.0.1:%d" % int(self.cfg["server"]["port"]),
                "--token", self.cfg["server"].get("token") or "",
                "--timeout", str(self.cli_timeout - 30)]
        try:
            proc = self._cli(["ask", "--session", self.secretary_id, "--text", job["text"], "--json"] + base)
            self._parse(job, proc)
        except subprocess.TimeoutExpired:
            job["status"] = "error"
            job["error"] = "CLI 超时（%ss）" % self.cli_timeout
        except Exception as exc:
            job["status"] = "error"
            job["error"] = repr(exc)
        finally:
            job["ms"] = int((time.time() - job["t0"]) * 1000)
            self.emit("webchat.done", {"job": job["id"], "group": job.get("group"),
                                       "status": job["status"], "ms": job["ms"]})

    def _run_ticket(self, job, ticket):
        base = ["--url", "http://127.0.0.1:%d" % int(self.cfg["server"]["port"]),
                "--token", self.cfg["server"].get("token") or "",
                "--timeout", str(self.cli_timeout - 30)]
        try:
            proc = self._cli(["ticket-msg", "--ticket", ticket, "--text", job["text"], "--json"] + base)
            out = (proc.stdout or "").strip()
            job["log"] = out[-2000:]
            data = {}
            try:
                data = json.loads(out.splitlines()[-1]) if out else {}
            except (ValueError, IndexError):
                data = {}
            if data.get("ok") is False or not data.get("session"):
                job["status"] = "error"
                job["error"] = data.get("error") or (proc.stderr or "投递失败")[-300:]
            else:
                job["session"] = data.get("session")
                job["status"] = "done"
                job["reply"] = "已投递给 %s" % data.get("session")
        except subprocess.TimeoutExpired:
            job["status"] = "error"
            job["error"] = "CLI 超时"
        except Exception as exc:
            job["status"] = "error"
            job["error"] = repr(exc)
        finally:
            job["ms"] = int((time.time() - job["t0"]) * 1000)
            self.emit("webchat.done", {"job": job["id"], "group": job.get("group"),
                                       "status": job["status"], "ms": job["ms"]})

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

    def _run_ticket_direct(self, job, ticket):
        try:
            res = self.ctx.api("tickets.message", ticket_id=ticket, text=job["text"])
            job["session"] = res.get("session")
            job["status"] = "done"
            job["reply"] = "已投递给 %s" % res.get("session")
        except ApiError as exc:
            job["status"] = "error"
            job["error"] = exc.message
        finally:
            job["ms"] = int((time.time() - job["t0"]) * 1000)

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

    # ---------------- 群列表 ----------------
    def groups(self, payload):
        items = []
        try:
            s = self.ctx.api("sessions.get", session_id=self.secretary_id)["session"]
            items.append({
                "id": self.secretary_id, "kind": "secretary", "title": "秘书",
                "project": "", "status": s.get("status"), "state": s.get("state"),
                "messages": s.get("messages", 0), "chars": s.get("chars", 0),
                "updated": s.get("updated"), "open": True,
            })
        except ApiError:
            items.append({"id": self.secretary_id, "kind": "secretary", "title": "秘书",
                          "project": "", "status": "lazy", "state": "lazy",
                          "messages": 0, "chars": 0, "updated": "", "open": True})

        projects = []
        try:
            projects = self.ctx.api("projects.list").get("items", [])
        except ApiError:
            projects = []

        try:
            tickets = self.ctx.api("tickets.list").get("items", [])
        except ApiError:
            tickets = []
        for t in tickets:
            items.append({
                "id": t["id"], "kind": "ticket", "title": t["title"], "project": t["project"],
                "status": t["status"], "state": t["status"], "pm": t.get("pm") or "",
                "roles": len(t.get("roles") or []), "updated": t.get("updated"),
                "open": t["status"] != "closed", "created": t.get("created"),
            })
        return {"items": items, "projects": projects, "secretary": self.secretary_id,
                "default_project": (projects[0]["id"] if projects else "")}

    # ---------------- 时间线（群聊） ----------------
    def timeline(self, payload):
        group = (payload.get("group") or self.secretary_id).strip()
        limit = max(10, min(int(payload.get("limit") or 80), 400))
        since = payload.get("since_ts")
        items = []
        if group.startswith("ticket:"):
            group = group.split(":", 1)[-1]
        if group.startswith("T-"):
            items = self._ticket_timeline(group, limit)
        else:
            items = self._session_timeline(self.secretary_id, limit)
        if since not in (None, ""):
            try:
                cut = float(since)
                items = [i for i in items if (i.get("ts") or 0) > cut]
            except (TypeError, ValueError):
                pass
        cursor = max([float(i.get("ts") or 0) for i in items] or [0])
        return {"group": group, "items": items[-limit:], "cursor": cursor}

    def _session_timeline(self, session_id, limit):
        try:
            res = self.ctx.api("sessions.messages", session_id=session_id, limit=limit)
        except ApiError:
            return []
        out = []
        for m in res.get("items", []):
            out.append(self._item(m, m.get("speaker") or session_id, m.get("role_name") or ""))
        return out

    def _ticket_timeline(self, ticket_id, limit):
        out = []
        try:
            t = self.ctx.api("tickets.get", ticket_id=ticket_id)["ticket"]
        except ApiError:
            return []
        try:
            sessions = self.ctx.api("sessions.list", ticket=ticket_id).get("items", [])
        except ApiError:
            sessions = []
        per = max(10, limit // max(1, len(sessions) or 1))
        for s in sessions:
            try:
                res = self.ctx.api("sessions.messages", session_id=s["id"], limit=per)
            except ApiError:
                continue
            for m in res.get("items", []):
                speaker = s.get("title") or s.get("role") or s["id"]
                out.append(self._item(m, speaker, s.get("role") or s.get("kind") or ""))
        for h in t.get("history") or []:
            out.append({
                "ts": self._parse_ts(h.get("ts")), "speaker": "系统", "role": "event",
                "text": "%s %s" % (h.get("event"), h.get("detail") or ""),
                "kind": "event", "session": "", "tool_names": [],
            })
        out.sort(key=lambda i: i.get("ts") or 0)
        return out

    def _item(self, m, speaker, role_name):
        return {
            "ts": self._parse_ts(m.get("ts")),
            "speaker": speaker,
            "role": m.get("role"),
            "role_name": role_name,
            "kind": m.get("kind"),
            "session": m.get("session"),
            "text": m.get("content") or "",
            "tool_names": m.get("tool_names") or [],
        }

    def _parse_ts(self, v):
        if isinstance(v, (int, float)):
            return float(v)
        if isinstance(v, str) and v:
            try:
                return time.mktime(time.strptime(v, "%Y-%m-%dT%H:%M:%SZ")) - time.timezone
            except ValueError:
                return 0.0
        return 0.0
