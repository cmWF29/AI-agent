"""会话/Agent 管理模块 —— 秘书常驻、角色临时、可并发。

每个会话 = 一个常驻 worker 线程 + 一个任务队列，所以：
  * 会话是持久的（秘书 session 不会因为一次问答被销毁）；
  * 会话内部严格串行（不抢消息），会话之间并发；
  * 想插队 -> inbox note；想打断 -> inbox abort（由 React 循环在边界消费）。

对外只有 API：sessions.spawn / send / ask / wait / compact / interrupt / destroy / list / get。
"""
from __future__ import annotations

import os
import queue
import threading
import time
import uuid

from ..kernel.api import ApiError, Module
from ..kernel.config import path_of
from ..kernel.store import Collection, ensure_dir, ts
from ..kernel.tools import Tool

MAX_ARCHIVE = 200


def _now():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _chars(messages):
    total = 0
    for m in messages:
        total += len(m.get("content") or "")
        for tc in (m.get("tool_calls") or []):
            total += len(str(tc))
    return total


class SessionRuntime:
    def __init__(self, record, manager):
        self.record = record
        self.manager = manager
        self.id = record["id"]
        self.queue = queue.Queue()
        self.inbox = []
        self.lock = threading.RLock()
        self.state = "idle"            # idle | running | destroyed
        self.job = None
        self.thread = threading.Thread(target=self._loop, name="sess-" + self.id[:8], daemon=True)
        self.thread.start()

    # ---------------- worker ----------------
    def _loop(self):
        while True:
            task = self.queue.get()
            if task is None:
                self.state = "destroyed"
                self.queue.task_done()
                break
            try:
                self._run_task(task)
            except Exception as exc:                       # 任何异常都不能让线程死掉
                self.manager.log.exc("session.task.crash", session=self.id, error=repr(exc))
                self._finish_job(task, error=repr(exc))
            finally:
                self.queue.task_done()

    def _run_task(self, task):
        rec = self.record
        job = task["job"]
        self.state = "running"
        self.current_job = job
        with self.lock:
            rec["status"] = "running"
            rec["stats"]["runs"] += 1
            rec["updated"] = _now()
        self.manager.persist(rec)
        self.manager.emit("session.run.start", {"session": self.id, "kind": rec["kind"], "job": job["id"],
                                                "chars": len(task.get("text") or "")})

        if self.manager.should_compact(rec):
            try:
                self.manager.compact_session(self.id, manual=False)
            except Exception as exc:
                self.manager.log.warn("session.autocompact.failed", session=self.id, error=repr(exc))

        result = None
        self.manager.acquire_slot()
        try:
            result = self.manager.react.run(
                session=rec,
                user_text=task.get("text") or None,
                drain=self.drain,
                hooks=self._hook,
                max_steps=task.get("max_steps"),
            )
        finally:
            self.manager.release_slot()
        reply = result.get("final") or ""
        job.update({"status": result.get("status"), "reply": reply, "steps": result.get("steps"), "error": result.get("error")})
        with self.lock:
            rec["status"] = "idle"
            rec["updated"] = _now()
            rec["stats"]["steps"] += int(result.get("steps") or 0)
            rec["last_reply"] = reply[:2000]
            rec["last_status"] = result.get("status")
        self.manager.persist(rec)
        self.state = "idle"
        self.current_job = None
        self.manager.emit("session.run.finish", {
            "session": self.id, "kind": rec["kind"], "job": job["id"],
            "status": job["status"], "steps": job["steps"], "reply_chars": len(reply),
        })
        job["event"].set()

    def _finish_job(self, task, error=None):
        job = task["job"]
        job.update({"status": "error", "error": error, "reply": ""})
        with self.lock:
            self.record["status"] = "error"
            self.record["updated"] = _now()
        self.state = "idle"
        self.current_job = None
        self.manager.persist(self.record)
        job["event"].set()
        self.manager.emit("session.run.error", {"session": self.id, "error": error})

    def _hook(self, name, payload):
        if name == "tool.start":
            self.record["stats"]["tool_calls"] += 1
        elif name == "llm.response":
            self.record["stats"]["llm_calls"] += 1
        self.manager.emit("session.hook",
                          {"session": self.id, "hook": name,
                           **{k: v for k, v in payload.items() if k != "session"}})
        # 边跑边落盘：否则长任务跑到一半，网页上的时间线还是旧内容
        if name in ("llm.response", "tool.result"):
            self.manager.persist(self.record)

    # ---------------- 中断 ----------------
    def drain(self):
        with self.lock:
            items = self.inbox
            self.inbox = []
        return items

    def push(self, item):
        with self.lock:
            self.inbox.append(item)
        self.manager.emit("session.interrupt", {"session": self.id, "kind": item.get("kind"), "chars": len(item.get("text") or "")})

    def stop(self):
        self.queue.put(None)


class Sessions(Module):
    name = "sessions"

    def setup(self):
        self.root = path_of(self.cfg, "sessions.root", "data/sessions")
        self.ws_root = path_of(self.cfg, "sessions.workspace_root", "data/workspaces")
        self.archive_dir = ensure_dir(os.path.join(self.root, "archive"))
        self.store = Collection(self.root)
        self.react = self.ctx.state["react"]
        self.llm = self.ctx.state["llm"]
        self.runtimes = {}
        self.jobs = {}
        self.lock = threading.RLock()
        self.max_concurrent = int(self.cfg["sessions"].get("max_concurrent", 8))
        self.slots = threading.BoundedSemaphore(max(1, self.max_concurrent))
        self.active = 0
        self.active_lock = threading.Lock()
        self.log.info("sessions.ready", root=self.root, max_concurrent=self.max_concurrent)

        # 上次是“跑到一半被重启”：记录里的 running/queued 状态已经没有线程了，
        # 不清掉会永远显示 running，工单也会卡住。这里统一标成 interrupted。
        recovered = []
        for sid in self.store.ids():
            try:
                rec = self.store.get(sid)
            except Exception:
                continue
            if rec.get("state") in ("running", "queued") or rec.get("status") in ("running", "queued"):
                rec["prev_state"] = rec.get("state") or rec.get("status")
                rec["state"] = "idle"
                rec["status"] = "interrupted"
                rec["updated"] = _now()
                self.persist(rec)
                recovered.append(sid)
        if recovered:
            self.log.warn("sessions.recovered", count=len(recovered), ids=recovered[:10])
            self.emit("sessions.recovered", {"count": len(recovered), "ids": recovered[:10]})
        self.recovered_ids = recovered

        # 常驻会话在首次访问时按需拉起，避免启动阶段就依赖 LLM
        self.secretary_id = self.cfg["secretary"].get("session_id") or "secretary"

        self.api.route("POST", "/api/sessions/spawn", name="spawn")(self.spawn_api)
        self.api.route("POST", "/api/sessions/send", name="send")(self.send_api)
        self.api.route("POST", "/api/sessions/ask", name="ask")(self.ask_api)
        self.api.route("POST", "/api/sessions/wait", name="wait")(self.wait_api)
        self.api.route("GET", "/api/sessions/list", name="list")(self.list_api)
        self.api.route("GET", "/api/sessions/state", name="state")(self._state_api)
        self.api.route("GET", "/api/sessions/{session_id}", name="get")(self.get_api)
        self.api.route("GET", "/api/sessions/{session_id}/messages", name="messages")(self.messages_api)
        self.api.route("POST", "/api/sessions/{session_id}/compact", name="compact")(self.compact_api)
        self.api.route("POST", "/api/sessions/{session_id}/interrupt", name="interrupt")(self.interrupt_api)
        self.api.route("POST", "/api/sessions/{session_id}/destroy", name="destroy")(self.destroy_api)
        self.api.route("POST", "/api/sessions/secretary/ensure", name="ensure")(self.ensure_api)

        self._register_tools()
        self.bus.subscribe("session.result", self._on_result, name="sessions.result")

    def shutdown(self):
        for sid, rt in list(self.runtimes.items()):
            try:
                rt.push({"kind": "abort", "text": "服务关闭"})
                rt.stop()
            except Exception:
                pass
        self.log.info("sessions.shutdown", count=len(self.runtimes))

    # ---------------- 并发闸门 ----------------
    # 会话本身是“一会话一线程”，会话之间天然并发；这里只限制“同时在跑 LLM 的会话数”，
    # 超出的会话在各自队列里排队。多工单并发时，靠这一个闸门保证不会把 VPS 打爆。
    def acquire_slot(self):
        self.slots.acquire()
        with self.active_lock:
            self.active += 1

    def release_slot(self):
        with self.active_lock:
            self.active = max(0, self.active - 1)
        try:
            self.slots.release()
        except ValueError:
            pass

    def _state_api(self, payload):
        with self.active_lock:
            active = self.active
        return {"active": active, "max_concurrent": self.max_concurrent,
                "sessions": len(self.store.list()),
                "queued": sum(1 for r in self.runtimes.values() if r.state == "running") - active}

    # ---------------- 记录 ----------------
    def persist(self, record):
        try:
            self.store.put(record["id"], record)
        except OSError as exc:
            self.log.error("session.persist.failed", session=record.get("id"), error=repr(exc))

    def get_record(self, session_id):
        rec = self.store.get(session_id)
        if rec is None:
            raise ApiError("会话不存在: %s" % session_id, status=404, code="no_session")
        return rec

    # ---------------- 生命周期 ----------------
    def spawn(self, kind="role", title="", system_prompt="", project="", ticket="", role="",
              parent="", tools=None, meta=None, input_text=None, workspace=None,
              model_temperature=None, session_id=None, display=""):
        sid = session_id or "%s-%s" % (kind[:3], uuid.uuid4().hex[:8])
        ws = ensure_dir(workspace or os.path.join(self.ws_root, sid))
        record = {
            "id": sid,
            "kind": kind,
            "title": title or ("%s/%s" % (role, sid)),
            "display": display or title or role or sid,
            "role": role,
            "project": project,
            "ticket": ticket,
            "parent": parent,
            "system_prompt": system_prompt,
            "messages": ([{"role": "system", "content": system_prompt}] if system_prompt else []),
            "status": "idle",
            "workspace": ws,
            "tools": tools,
            "meta": meta or {},
            "created": _now(),
            "updated": _now(),
            "stats": {"runs": 0, "steps": 0, "llm_calls": 0, "tool_calls": 0},
            "temperature": model_temperature,
        }
        with self.lock:
            self.store.put(sid, record)
            rt = SessionRuntime(record, self)
            self.runtimes[sid] = rt
        self.emit("session.created", {"session": sid, "kind": kind, "role": role,
                                      "project": project, "ticket": ticket, "parent": parent})
        self.log.info("session.created", session=sid, kind=kind, role=role, ticket=ticket)
        if input_text:
            self.submit(sid, input_text)
        return record

    def submit(self, session_id, text, max_steps=None):
        if session_id == self.secretary_id or session_id.startswith("sec-"):
            project = "" if session_id == self.secretary_id else session_id[4:]
            self.ensure_secretary(project=project)      # 幂等：顺带把提示词/工具策略升级热更新进来
        rec = self.get_record(session_id)
        rt = self._runtime(session_id)
        if rt.state == "destroyed":
            raise ApiError("会话已销毁: %s" % session_id, status=410, code="destroyed")
        if rt.state == "running":
            rt.push({"kind": "note", "text": text})
            return {"job_id": None, "injected": True, "state": "running"}
        job = {
            "id": "j-" + uuid.uuid4().hex[:8],
            "session": session_id,
            "status": "queued",
            "created": _now(),
            "event": threading.Event(),
        }
        self.jobs[job["id"]] = job
        rt.queue.put({"job": job, "text": text, "max_steps": max_steps})
        return {"job_id": job["id"], "injected": False, "state": "queued"}

    def wait(self, session_id, job_id=None, timeout=0):
        """timeout<=0 = 一直等（需求 16：复杂任务跑多久都正常，不要固定超时）。"""
        if job_id and job_id in self.jobs:
            job = self.jobs[job_id]
            if not job["event"].wait(None if not timeout or timeout <= 0 else timeout):
                return {"status": "timeout", "session": session_id, "job_id": job_id}
            return {"status": job["status"], "reply": job.get("reply", ""), "job_id": job_id,
                    "steps": job.get("steps"), "error": job.get("error")}
        rt = self._runtime(session_id)
        end = None if not timeout or timeout <= 0 else time.time() + timeout
        while end is None or time.time() < end:
            if rt.state == "idle" and not rt.queue.qsize():
                rec = self.get_record(session_id)
                return {"status": rec.get("last_status") or "idle", "reply": rec.get("last_reply") or "", "job_id": None}
            time.sleep(0.1)
        return {"status": "timeout", "session": session_id, "job_id": None}

    def _runtime(self, session_id):
        with self.lock:
            rt = self.runtimes.get(session_id)
        if rt is None:
            rec = self.store.get(session_id)
            if rec is None:
                raise ApiError("会话不存在: %s" % session_id, status=404, code="no_session")
            rt = SessionRuntime(rec, self)       # 进程重启后把历史会话重新挂起来
            with self.lock:
                self.runtimes[session_id] = rt
        return rt

    def destroy(self, session_id, archive=True):
        with self.lock:
            rt = self.runtimes.pop(session_id, None)
        if rt:
            rt.push({"kind": "abort", "text": "会话即将销毁"})
            rt.stop()
            try:
                rt.thread.join(timeout=5)
            except RuntimeError:
                pass
        rec = self.store.get(session_id)
        if rec and archive:
            rec = dict(rec)
            rec["archived"] = _now()
            try:
                import json
                with open(os.path.join(self.archive_dir, session_id + ".json"), "w", encoding="utf-8") as f:
                    json.dump(rec, f, ensure_ascii=False, indent=2)
            except OSError:
                pass
        self.store.delete(session_id)
        self._trim_archive()
        self.emit("session.destroyed", {"session": session_id, "archived": bool(rec)})
        self.log.info("session.destroyed", session=session_id)
        return {"destroyed": session_id}

    def _trim_archive(self):
        try:
            files = sorted(
                (os.path.join(self.archive_dir, f) for f in os.listdir(self.archive_dir)),
                key=lambda p: os.path.getmtime(p),
                reverse=True,
            )
            for path in files[MAX_ARCHIVE:]:
                os.remove(path)
        except OSError:
            pass

    # ---------------- 压缩 ----------------
    def should_compact(self, record):
        if record.get("kind") != "secretary":
            return False
        if not self.cfg["secretary"].get("auto_compact"):
            return False
        return _chars(record.get("messages") or []) > int(self.cfg["secretary"].get("compact_threshold_chars", 30000))

    def compact_session(self, session_id, manual=False):
        rec = self.get_record(session_id)
        keep = int(self.cfg["secretary"].get("keep_recent_messages", 8))
        msgs = rec.get("messages") or []
        if len(msgs) <= keep + 2:
            return {"compacted": False, "reason": "too_short", "messages": len(msgs)}
        system = None
        body = msgs
        if msgs and msgs[0].get("role") == "system":
            system = msgs[0]
            body = msgs[1:]
        tail = [dict(m) for m in body[-keep:]]
        while tail and tail[0].get("role") == "tool":
            tail.pop(0)
        old = body[: len(body) - len(tail)]
        if not old:
            return {"compacted": False, "reason": "nothing_to_compact"}

        text = "\n".join(
            "%s: %s" % (m.get("role"), (m.get("content") or "")[:1500]) for m in old
        )[:60000]
        summary = ""
        try:
            summary = self.llm.complete_text(
                system=("你是对话压缩器。把给定的历史对话压成一段中文要点摘要，"
                        "保留：结论、已生效的约定、未完成的动作、关键 id/路径。不要编造，不要客套。"),
                user=text,
            )
        except Exception as exc:
            self.log.warn("session.compact.llm_failed", session=session_id, error=repr(exc))
            summary = "（压缩时 LLM 不可用，以下为原始截断）\n" + text[:2000]

        compact_msg = {
            "role": "user",
            "content": "[历史摘要｜上下文自动压缩]\n" + summary.strip() + "\n（以上为更早对话的压缩结果，细节可再用工具查证）",
        }
        new_msgs = ([system] if system else []) + [compact_msg] + tail
        before, after = _chars(msgs), _chars(new_msgs)
        rec["messages"] = new_msgs
        rec["stats"]["compactions"] = rec["stats"].get("compactions", 0) + 1
        rec["updated"] = _now()
        self.persist(rec)
        self.emit("session.compacted", {"session": session_id, "before_chars": before,
                                        "after_chars": after, "manual": manual})
        self.log.info("session.compacted", session=session_id, before=before, after=after, manual=manual)
        return {"compacted": True, "before_chars": before, "after_chars": after,
                "messages_before": len(msgs), "messages_after": len(new_msgs)}

    # ---------------- 秘书 ----------------
    def secretary_for(self, project=""):
        """本地层一个总秘书；每个项目一个项目秘书（需求 6：一个项目一个秘书，可行）。"""
        return ("sec-" + project) if project else self.secretary_id

    def ensure_secretary(self, reset=False, project=""):
        sid = self.secretary_for(project)
        prompt = self._secretary_prompt(project)
        # 秘书只“发作业/查进度”，不碰执行类工具（shell/文件/爬网页一律没有）。
        # 这是需求 7 的硬约束：秘书只负责发作业，收作业都不用秘书做。
        tools = [
            "ticket_create", "ticket_list", "ticket_status",
            "project_list", "project_create", "project_status",
            "knowledge_read", "knowledge_list", "knowledge_search",
            "memory_add", "memory_search",
            "agent_list", "agent_status", "agent_wait",
        ]
        if reset and self.store.exists(sid):
            self.destroy(sid)
        if not reset and self.store.exists(sid):
            rec = self.store.get(sid)
            # 工具集变了 = 权限模型变了：旧对话里可能残留“它当时确实执行过”的上下文，
            # 新策略下模型会拿旧输出冒充新结果。这种情况必须重建会话（旧会话进归档）。
            if rec.get("tools") != tools:
                self.log.warn("session.secretary.policy_changed", session=sid,
                              old=rec.get("tools"), new=tools)
                self.destroy(sid, archive=True)
                self.emit("session.secretary.recreated", {"session": sid, "reason": "tool_policy"})
                return self._spawn_secretary(prompt, tools, project, sid)
            # 提示词变了 = 行为准则变了，同样重建（旧对话里的“旧习气”会污染新策略）
            if prompt and rec.get("system_prompt") != prompt:
                self.log.warn("session.secretary.prompt_changed", session=sid)
                self.destroy(sid, archive=True)
                self.emit("session.secretary.recreated", {"session": sid, "reason": "prompt"})
                return self._spawn_secretary(prompt, tools, project, sid)
            return rec
        return self._spawn_secretary(prompt, tools, project, sid)

    def _spawn_secretary(self, prompt, tools, project="", sid=None):
        sid = sid or self.secretary_id
        return self.spawn(
            kind="secretary",
            title=("项目秘书/" + project) if project else "秘书",
            display=("项目秘书·" + project) if project else "秘书",
            system_prompt=prompt,
            role="secretary",
            project=project,
            tools=tools,
            meta={"resident": True},
            workspace=os.path.join(self.ws_root, sid),
            session_id=sid,
        )

    def _secretary_prompt(self, project=""):
        try:
            compose = self.ctx.api("knowledge.compose", scopes=[{"layer": "public"}])
            base = compose.get("text") or ""
        except ApiError:
            base = ""
        scope = ""
        if project:
            scope = (
                "\n\n## 你服务的项目：%s\n"
                "你只管这个项目。开工单一律带 project=\"%s\"，不要碰别的项目。\n" % (project, project)
            )
        return (base.strip() + "\n\n" if base.strip() else "") + scope

    # ---------------- API ----------------
    def spawn_api(self, payload):
        kind = payload.get("kind") or "role"
        res = self.spawn(
            kind=kind,
            title=payload.get("title") or "",
            display=payload.get("display") or "",
            system_prompt=payload.get("system_prompt") or "",
            project=payload.get("project") or "",
            ticket=payload.get("ticket") or "",
            role=payload.get("role") or "",
            parent=payload.get("parent") or "",
            tools=payload.get("tools"),
            meta=payload.get("meta") or {},
            input_text=payload.get("input") or payload.get("input_text"),
            workspace=payload.get("workspace"),
        )
        return {"session": self._summary(res)}

    def send_api(self, payload):
        sid = payload.get("session") or self.secretary_id
        text = payload.get("text")
        if text is None:
            raise ApiError("text 必填", code="missing_text")
        return self.submit(sid, text, max_steps=payload.get("max_steps"))

    def ask_api(self, payload):
        sid = payload.get("session") or self.secretary_id
        if sid == self.secretary_id or sid.startswith("sec-"):
            self.ensure_secretary(project="" if sid == self.secretary_id else sid[4:])
        text = payload.get("text")
        # 默认不设超时（需求 16：复杂任务跑很久是正常的）；需要上限时显式传 timeout。
        timeout = int(payload.get("timeout") or 0)
        job = self.submit(sid, text, max_steps=payload.get("max_steps"))
        if job.get("injected"):
            return {"status": "injected", "reply": "", "job_id": None}
        res = self.wait(sid, job["job_id"], timeout=timeout)
        res["session"] = sid
        return res

    def wait_api(self, payload):
        sid = payload.get("session")
        if not sid:
            raise ApiError("session 必填", code="missing_session")
        return self.wait(sid, payload.get("job_id"), timeout=int(payload.get("timeout") or 0))

    def list_api(self, payload):
        kind = payload.get("kind")
        project = payload.get("project")
        ticket = payload.get("ticket")
        items = [self._summary(r) for r in self.store.list()]
        if kind:
            items = [i for i in items if i["kind"] == kind]
        if project:
            items = [i for i in items if (i.get("project") or "") == project]
        if ticket:
            items = [i for i in items if (i.get("ticket") or "") == ticket]
        items.sort(key=lambda i: i.get("updated") or "", reverse=True)
        return {"items": items, "total": len(items), "active": self.active,
                "max_concurrent": self.max_concurrent}

    def get_api(self, payload):
        rec = self.get_record(payload["session_id"])
        out = self._summary(rec)
        out["messages"] = len(rec.get("messages") or [])
        out["meta"] = rec.get("meta", {})
        out["partial"] = rec.get("partial") or {}
        out["workspace"] = rec.get("workspace")
        return {"session": out}

    def messages_api(self, payload):
        """消息读取：带 ts / 说话人 / 工具名，网页群聊直接消费这个结果。"""
        rec = self.get_record(payload["session_id"])
        limit = min(int(payload.get("limit") or 40), 500)
        since = payload.get("since_ts")
        msgs = rec.get("messages") or []
        if since is not None and str(since) != "":
            try:
                cut = float(since)
                msgs = [m for m in msgs if float(m.get("ts") or 0) > cut]
            except (TypeError, ValueError):
                pass
        items = []
        for m in msgs[-limit:]:
            items.append({
                "session": rec["id"],
                "speaker": rec.get("display") or rec.get("title") or rec.get("role") or rec["id"],
                "kind": rec.get("kind"),
                "role_name": rec.get("role"),
                "role": m.get("role"),
                "ts": m.get("ts"),
                "content": (m.get("content") or "")[:2000],
                "tool_names": [(tc.get("function") or {}).get("name") for tc in (m.get("tool_calls") or [])],
                "tool_calls": len(m.get("tool_calls") or []),
            })
        return {"session": rec["id"], "total": len(rec.get("messages") or []), "items": items}

    def compact_api(self, payload):
        sid = payload.get("session_id") or self.secretary_id
        return self.compact_session(sid, manual=True)

    def interrupt_api(self, payload):
        sid = payload["session_id"]
        rt = self._runtime(sid)
        abort = payload.get("abort", True)
        rt.push({"kind": "abort" if abort else "note", "text": payload.get("text") or ""})
        return {"interrupted": True, "abort": abort}

    def destroy_api(self, payload):
        return self.destroy(payload["session_id"], archive=payload.get("archive", True))

    def ensure_api(self, payload):
        rec = self.ensure_secretary(reset=bool(payload.get("reset")),
                                    project=payload.get("project") or "")
        return {"session": self._summary(rec)}

    def _summary(self, rec):
        rt = self.runtimes.get(rec["id"])
        # 运行中的会话，磁盘上的 rec 还是旧快照；流式增量写在 runtime 的 record 上，
        # 这里必须优先读 runtime，否则网页 livebar 永远看不到 partial（表现为“没在流式输出”）。
        live = rt.record if (rt is not None and getattr(rt, "record", None)) else rec
        return {
            "id": rec["id"],
            "kind": rec.get("kind"),
            "title": rec.get("title"),
            "display": rec.get("display") or rec.get("title") or rec.get("role") or rec["id"],
            "role": rec.get("role"),
            "project": rec.get("project"),
            "ticket": rec.get("ticket"),
            "parent": rec.get("parent"),
            "status": rec.get("status"),
            "state": rt.state if rt else rec.get("status"),
            "messages": len(rec.get("messages") or []),
            "chars": _chars(rec.get("messages") or []),
            "created": rec.get("created"),
            "updated": rec.get("updated"),
            "stats": rec.get("stats"),
            "last_reply": (rec.get("last_reply") or "")[:300],
            "tools": rec.get("tools"),
            "partial": {"text": (live.get("partial") or {}).get("text", "")[-2000:],
                        "step": (live.get("partial") or {}).get("step"),
                        "state": (live.get("partial") or {}).get("state")},
        }

    # ---------------- 工具 ----------------
    def _on_result(self, ev):
        payload = ev.get("payload") or {}
        sid = payload.get("session")
        if not sid:
            return
        rec = self.store.get(sid)
        if rec:
            rec.setdefault("meta", {})["result"] = payload.get("summary", "")
            self.persist(rec)

    def _register_tools(self):
        tools = self.ctx.tools

        def spawn_tool(args, tctx):
            kind = args.get("kind") or "role"
            res = self.spawn(
                kind=kind,
                title=args.get("title") or "",
                role=args.get("role") or "",
                system_prompt=args.get("system_prompt") or "",
                project=args.get("project") or tctx.session.get("project") or "",
                ticket=args.get("ticket") or tctx.session.get("ticket") or "",
                parent=tctx.session_id,
                tools=args.get("tools"),
                input_text=args.get("task"),
            )
            return "已创建会话 %s（kind=%s role=%s），任务已投递。" % (res["id"], kind, res.get("role") or "-")

        def send_tool(args, tctx):
            sid = args.get("session")
            res = self.submit(sid, args.get("text") or "")
            if res.get("injected"):
                return "会话 %s 正在运行，已作为插话投递。" % sid
            if args.get("wait"):
                waited = self.wait(sid, res["job_id"], timeout=int(args.get("timeout") or 300))
                return "会话 %s 回复：\n%s" % (sid, waited.get("reply") or waited.get("status"))
            return "已投递，job=%s" % res["job_id"]

        def wait_tool(args, tctx):
            sid = args.get("session")
            res = self.wait(sid, None, timeout=int(args.get("timeout") or 300))
            return "会话 %s 状态=%s\n%s" % (sid, res.get("status"), res.get("reply") or "")

        def list_tool(args, tctx):
            items = [self._summary(r) for r in self.store.list()]
            if args.get("kind"):
                items = [i for i in items if i["kind"] == args["kind"]]
            if not items:
                return "暂无会话"
            return "\n".join("%s | %s | %s | %s字 | %s" % (
                i["id"], i["kind"], i["role"] or "-", i["chars"], i["state"] or i["status"]) for i in items)

        def status_tool(args, tctx):
            rec = self.get_record(args.get("session"))
            s = self._summary(rec)
            return "\n".join("%s: %s" % (k, s[k]) for k in ("id", "kind", "role", "status", "state", "messages", "chars"))

        def interrupt_tool(args, tctx):
            self._runtime(args.get("session")).push({
                "kind": "abort" if args.get("abort", True) else "note",
                "text": args.get("text") or "",
            })
            return "已通知会话 %s" % args.get("session")

        def destroy_tool(args, tctx):
            self.destroy(args.get("session"))
            return "已销毁 %s（已归档）" % args.get("session")

        def compact_tool(args, tctx):
            res = self.compact_session(args.get("session") or self.secretary_id, manual=True)
            return "压缩结果: %s" % res

        def result_tool(args, tctx):
            summary = args.get("summary") or ""
            rec = self.store.get(tctx.session_id)
            if rec:
                rec.setdefault("meta", {})["result"] = summary
                self.persist(rec)
            self.emit("session.result", {"session": tctx.session_id, "summary": summary,
                                         "ticket": tctx.session.get("ticket"), "role": tctx.session.get("role")})
            return "已上报结果（%d 字）。你可以结束本次任务了。" % len(summary)

        tools.register(Tool(
            "agent_spawn", "拉起一个新会话/新 agent 去干活（kind 可选 role/pm/manual）。",
            {"type": "object", "properties": {
                "kind": {"type": "string", "enum": ["role", "pm", "manual"]},
                "role": {"type": "string", "description": "角色名，如 architect、developer、reviewer"},
                "title": {"type": "string"},
                "task": {"type": "string", "description": "投递给它的首个任务"},
                "system_prompt": {"type": "string", "description": "可选：自定义角色提示词"},
                "tools": {"type": "array", "items": {"type": "string"}, "description": "可选：限制可用工具"},
            }, "required": ["role", "task"]},
            spawn_tool, origin=self.name))

        tools.register(Tool(
            "agent_send", "给已有会话发消息（运行中会自动变成插话）。",
            {"type": "object", "properties": {
                "session": {"type": "string"},
                "text": {"type": "string"},
                "wait": {"type": "boolean", "description": "true 则同步等回复"},
                "timeout": {"type": "integer"},
            }, "required": ["session", "text"]},
            send_tool, origin=self.name))

        tools.register(Tool(
            "agent_wait", "等待会话空闲并取回它的最新回复。",
            {"type": "object", "properties": {
                "session": {"type": "string"},
                "timeout": {"type": "integer"},
            }, "required": ["session"]},
            wait_tool, origin=self.name))

        tools.register(Tool(
            "agent_list", "列出当前所有会话。",
            {"type": "object", "properties": {"kind": {"type": "string"}}},
            list_tool, origin=self.name))

        tools.register(Tool(
            "agent_status", "查看单个会话状态。",
            {"type": "object", "properties": {"session": {"type": "string"}}, "required": ["session"]},
            status_tool, origin=self.name))

        tools.register(Tool(
            "agent_interrupt", "打断/插话给正在运行的会话。",
            {"type": "object", "properties": {
                "session": {"type": "string"},
                "text": {"type": "string"},
                "abort": {"type": "boolean", "description": "true=打断，false=插话"},
            }, "required": ["session"]},
            interrupt_tool, origin=self.name))

        tools.register(Tool(
            "agent_destroy", "销毁会话（先归档再删除）。",
            {"type": "object", "properties": {"session": {"type": "string"}}, "required": ["session"]},
            destroy_tool, origin=self.name))

        tools.register(Tool(
            "agent_compact", "手动压缩某个会话的上下文。",
            {"type": "object", "properties": {"session": {"type": "string"}}},
            compact_tool, origin=self.name))

        tools.register(Tool(
            "session_result", "把本角色的作业结果上报（写入工单记录）。",
            {"type": "object", "properties": {"summary": {"type": "string"}}, "required": ["summary"]},
            result_tool, origin=self.name))
