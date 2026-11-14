"""Agent 后端模块：把“已有 agent”接进同一套会话/工单生命周期。

不是新的一层业务；它是 kernel BackendRegistry 的一个插件实现。
- api：内核 ReactLoop，调 LLM API + 工具。
- claude-code：调本机 Claude Code CLI，工作目录仍是会话 workspace，产物仍由工单归档。

所以“自己做 ReAct”与“交给已有 agent”只是两个后端流程，PM/角色/结单/交付件逻辑不变。
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import threading
import queue
import time
import uuid

from ...kernel.api import ApiError, Module
from ...kernel.config import path_of
from ...kernel.store import ensure_dir
from ...kernel.hostres import check_host_resources, guard_config


class ClaudeCodeBackend:
    name = "claude-code"
    meta = {"name": "claude-code", "label": "Claude Code CLI",
            "description": "已有 agent 进程；使用本机文件/shell，不自建 ReAct"}

    def __init__(self, cfg, log, root):
        a = (cfg.get("agents") or {}).get("claude_code") or {}
        self.cfg = cfg
        self.log = log
        self.root = ensure_dir(root)
        self.command = a.get("command") or "claude"
        self.args = list(a.get("args") or ["-p", "{prompt}", "--output-format", "stream-json",
                                           "--permission-mode", "bypassPermissions"])
        self.timeout = int(a.get("timeout") or 0)  # 0 = 不设固定上限，靠插话/abort 中断
        self.extra_env = a.get("env") or {}

    def available(self):
        """布尔可用性：只看 CLI 装没装。

        前端（projects/ui.js）读的是 `cc.available`，这里必须保持布尔语义；
        资源门禁的结论放在 `reason` / `resources` 里，不改变 available 的含义，
        否则“机器忙”会被误显示成“没装 CLI”。
        """
        p = self._resolve_command()
        return bool(p and (os.path.isfile(p) or shutil.which(p)))

    def status(self):
        """给 /api/agents/backends 用的完整状态：available + reason + resources。"""
        installed = self.available()
        gate = check_host_resources(self.cfg)
        if not installed:
            reason = "本机未安装 claude CLI"
        elif not gate["ok"]:
            reason = gate["reason"]
        else:
            reason = ""
        return {
            "available": installed,
            "installed": installed,
            "reason": reason,
            "resources": gate["resources"],
            "guard": gate["guard"],
        }

    def _fallback_api(self, session, user_text, drain, hooks, max_steps, gate):
        """资源不足时降级到内核 api 后端跑同一轮。

        降级不是静默的：返回值里带 degraded / degraded_reason / resources，
        会话记录也打上标记，前端和工单都能看到“这轮不是 claude-code 跑的”。
        """
        api = getattr(self, "api_backend", None)
        if api is None:
            err = ApiError("宿主机资源不足且 api 后端不可用：%s" % gate["reason"],
                           status=503, code="host_resources_insufficient")
            err.reason = gate["reason"]
            err.resources = gate["resources"]
            err.guard_code = gate["code"]
            raise err
        self.log.info("agent.claude.fallback_api", session=session.get("id"),
                      code=gate["code"], reason=gate["reason"])
        res = api.run(session, user_text=user_text, drain=drain, hooks=hooks,
                      max_steps=max_steps)
        if isinstance(res, dict):
            res = dict(res)
            res["degraded"] = True
            res["degraded_from"] = "claude-code"
            res["degraded_reason"] = gate["reason"]
            res["degraded_code"] = gate["code"]
            res["resources"] = gate["resources"]
        return res

    def _resolve_command(self):
        """优先找常见 npm 全局安装位置，避免服务进程的 PATH 不含 npm。"""
        cmd = self.command
        candidates = [cmd]
        if os.name == "nt":
            appdata = os.environ.get("APPDATA") or ""
            if appdata:
                candidates += [os.path.join(appdata, "npm", "claude.exe"),
                               os.path.join(appdata, "npm", "claude.cmd")]
        else:
            candidates += ["/usr/local/bin/claude", "/opt/homebrew/bin/claude"]
        for c in candidates:
            if c and os.path.isfile(c):
                return c
        return shutil.which(cmd) or cmd

    def _prompt_file(self, session, user_text, drain):
        sid = session.get("id") or "session"
        d = ensure_dir(os.path.join(self.root, sid))
        path = os.path.join(d, "prompt-%s.md" % uuid.uuid4().hex[:8])
        text = (session.get("system_prompt") or "").strip()
        history = []
        for m in (session.get("messages") or [])[-8:]:
            if m.get("role") in ("user", "assistant") and m.get("content"):
                history.append("%s: %s" % (m.get("role"), m.get("content")[:1200]))
        notes = []
        for n in (drain() if drain else []) or []:
            if n.get("kind") == "note" and n.get("text"):
                notes.append(n["text"])
            
        body = ["# Hive Agent 任务", "", "## 系统角色", text or "（无）", "",
                "## 最近对话", "\n".join(history) or "（无）", "",
                "## 当前任务", user_text or "（继续）"]
        if notes:
            body += ["", "## 运行中插话", "\n".join(notes)]
        body += ["", "## 工作目录", os.path.abspath(session.get("workspace") or "."), "",
                 "请直接在工作目录内完成任务；需要交付的文件写到 docs/ 下。最后用中文给出结果摘要。"]
        with open(path, "w", encoding="utf-8") as f:
            f.write("\n".join(body))
        return path

    def run(self, session, user_text=None, drain=None, hooks=None, max_steps=None):
        ws = ensure_dir(session.get("workspace") or os.path.join(self.root, session.get("id") or "ws"))
        prompt_file = self._prompt_file(session, user_text, drain)
        instruction = "请读取文件 %s，按其中任务执行；完成后输出结果摘要。" % prompt_file
        argv = [instruction if x == "{prompt}" else x for x in self.args]
        # 外部 CLI 的流式输出统一用 stream-json；兼容旧配置里的 json/text。
        for i, x in enumerate(argv):
            if x == "--output-format" and i + 1 < len(argv):
                argv[i + 1] = "stream-json"
        if "--output-format" not in argv:
            argv += ["--output-format", "stream-json"]
        if "--include-partial-messages" not in argv:
            argv.append("--include-partial-messages")
        if "--verbose" not in argv:
            argv.append("--verbose")
        exe = self._resolve_command()
        cmd = [exe] + argv
        # Windows 的 npm 全局命令是 .cmd，需要 cmd /c 包一层
        if os.name == "nt" and exe.lower().endswith((".cmd", ".bat")):
            cmd = ["cmd.exe", "/c"] + cmd
        env = dict(os.environ)
        # llm 配置是唯一事实源：必须覆盖进程环境里可能残留的 ANTHROPIC_*，
        # 否则服务进程会拿宿主的旧 model 去连 DeepSeek，表现为 CLI 长时间不返回。
        llm = self.cfg.get("llm") if isinstance(self.cfg, dict) else {}
        if llm.get("api_key"):
            env["ANTHROPIC_AUTH_TOKEN"] = str(llm["api_key"])
        if llm.get("base_url"):
            env["ANTHROPIC_BASE_URL"] = str(llm["base_url"]).rstrip("/") + "/anthropic"
        if llm.get("model"):
            env["ANTHROPIC_MODEL"] = str(llm["model"])
            env["ANTHROPIC_SMALL_FAST_MODEL"] = str(llm["model"])
        # 显式 agents.claude_code.env 优先，用于个别部署覆盖
        env.update({str(k): str(v) for k, v in self.extra_env.items()})
        # 宿主机资源门禁：在真正 Popen 之前判定，避免把机器打爆。
        # 不足时按 agents.claude_code.guard.on_insufficient 处理：
        #   reject       -> 抛 ApiError（带 reason/resources），调用方看到明确原因
        #   fallback_api -> 降级到内核 api 后端，结果带 degraded=true
        gate = check_host_resources(self.cfg)
        if not gate["ok"]:
            self.log.warn("agent.claude.guard", session=session.get("id"),
                          code=gate["code"], reason=gate["reason"],
                          action=gate["action"], resources=gate["resources"])
            if gate["action"] == "fallback_api":
                return self._fallback_api(session, user_text, drain, hooks, max_steps, gate)
            err = ApiError("宿主机资源不足，已拒绝启动 claude-code：%s" % gate["reason"],
                           status=503, code="host_resources_insufficient")
            # ApiError 只有 message/status/code；把结构化原因挂在实例上，
            # 供 HTTP 层和测试读取，不改变 ApiError 的对外契约。
            err.reason = gate["reason"]
            err.resources = gate["resources"]
            err.guard_code = gate["code"]
            raise err
        t0 = time.time()
        self.log.info("agent.claude.start", session=session.get("id"), cwd=ws, cmd=cmd[:2],
                      model=env.get("ANTHROPIC_MODEL"), has_token=bool(env.get("ANTHROPIC_AUTH_TOKEN")))
        try:
            p = subprocess.Popen(cmd, cwd=ws, env=env, stdin=subprocess.DEVNULL,
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                                 encoding="utf-8", errors="replace")
        except FileNotFoundError:
            raise ApiError("找不到 agent CLI：%s（请先安装 Claude Code）" % self.command,
                           code="backend_not_installed")
        # 分流 stdout/stderr，主线程只做三件事：读增量、响应 abort、判结束。
        lines = queue.Queue()

        def _reader(stream, tag):
            try:
                for line in iter(stream.readline, ""):
                    if line:
                        lines.put((tag, line))
            finally:
                try:
                    stream.close()
                except Exception:
                    pass

        for stream, tag in ((p.stdout, "out"), (p.stderr, "err")):
            threading.Thread(target=_reader, args=(stream, tag), daemon=True).start()

        out_lines, err_lines = [], []
        stream_text = []
        final = ""
        meta = {}
        aborted = False
        last_emit = 0.0
        while True:
            try:
                tag, line = lines.get(timeout=2)
                if tag == "out":
                    out_lines.append(line)
                    try:
                        obj = json.loads(line)
                    except ValueError:
                        obj = None
                    if isinstance(obj, dict):
                        typ = obj.get("type")
                        if typ == "stream_event":
                            ev = obj.get("event") or {}
                            if ev.get("type") == "content_block_delta":
                                delta = ev.get("delta") or {}
                                txt = delta.get("text") if delta.get("type") == "text_delta" else ""
                                if txt:
                                    stream_text.append(txt)
                                    now = time.time()
                                    if hooks and (now - last_emit >= 0.15 or len(txt) >= 48):
                                        last_emit = now
                                        hooks("llm.delta", {"text": "".join(stream_text),
                                                            "model": "claude-code", "step": 1})
                        elif typ == "result":
                            final = obj.get("result") or final
                            meta = {k: obj.get(k) for k in ("session_id", "is_error", "total_cost_usd", "num_turns") if k in obj}
                        elif typ == "assistant" and not stream_text:
                            # 有些版本只给 assistant 整段消息，没有 partial
                            msg = obj.get("message") or {}
                            for block in msg.get("content") or []:
                                if block.get("type") == "text":
                                    stream_text.append(block.get("text") or "")
                else:
                    err_lines.append(line)
            except queue.Empty:
                # 外部 agent 默认不设固定超时；只响应会话插话/abort 与显式配置上限
                for item in (drain() if drain else []) or []:
                    if item.get("kind") == "abort":
                        aborted = True
                        try:
                            p.kill()
                        except OSError:
                            pass
                        break
                if aborted:
                    break
                if self.timeout and (time.time() - t0) >= self.timeout:
                    try:
                        p.kill()
                    except OSError:
                        pass
                    break
                if p.poll() is not None and lines.empty():
                    break
            if p.poll() is not None and lines.empty():
                break
        out = "".join(out_lines).strip()
        err = "".join(err_lines).strip()
        if aborted:
            if hooks:
                hooks("llm.delta", {"text": "", "state": "aborted", "model": "claude-code"})
            raise ApiError("agent 任务已被用户打断", code="backend_aborted")
        if not final:
            final = "".join(stream_text).strip() or out
        if not meta:
            try:
                obj = json.loads(out.splitlines()[-1] if out else "{}")
                if isinstance(obj, dict) and obj.get("result"):
                    final = obj["result"]
                    meta = {k: obj.get(k) for k in ("session_id", "is_error", "total_cost_usd", "num_turns") if k in obj}
            except ValueError:
                pass
        if p.returncode != 0 and not final:
            raise ApiError("agent CLI 失败（exit %s）：%s" % (p.returncode, err[:300]),
                           code="backend_failed")
        ms = int((time.time() - t0) * 1000)
        if hooks:
            hooks("llm.delta", {"text": final, "state": "done", "model": "claude-code"})
            hooks("llm.response", {"text": final, "model": "claude-code", "ms": ms, "streamed": True, **(meta or {})})
        rec = session
        rec.setdefault("messages", [])
        if user_text:
            rec["messages"].append({"role": "user", "content": user_text})
        rec["messages"].append({"role": "assistant", "content": final})
        rec["last_reply"] = final[:2000]
        rec["last_status"] = "ok"
        rec["stats"] = rec.get("stats") or {}
        rec["stats"]["llm_calls"] = int(rec["stats"].get("llm_calls") or 0) + 1
        return {"status": "ok" if p.returncode == 0 else "error", "final": final,
                "steps": 1, "error": "" if p.returncode == 0 else err[:300]}


class Agents(Module):
    name = "agents"

    def setup(self):
        a = self.cfg.get("agents") if isinstance(self.cfg.get("agents"), dict) else {}
        root = path_of(self.cfg, "agents.root", "data/agents")
        self.root = ensure_dir(root)
        self.claude = ClaudeCodeBackend(self.cfg, self.log, self.root)
        self.backends = self.ctx.state["backends"]
        # 资源门禁降级目标：内核 api 后端（可能尚未注册，run 时再取）
        self.claude.api_backend = self.backends.get("api")
        self.backends.register("claude-code", self.claude, label="Claude Code CLI",
                               description="已有 agent 进程；使用本机文件/shell，不自建 ReAct")
        self.api.route("GET", "/api/agents/backends", name="backends")(self.backends_api)
        self.api.route("POST", "/api/agents/run", name="run")(self.run_api)
        self.log.info("agents.ready", backends=[b["name"] for b in self.backends.list()])

    def backends_api(self, payload=None):
        items = self.backends.list()
        for b in items:
            backend = self.backends.get(b.get("name"))
            if hasattr(backend, "status"):
                b.update(backend.status())
            elif hasattr(backend, "available"):
                b["available"] = bool(backend.available())
        return {"items": items, "default": self.cfg.get("sessions", {}).get("backend") or "api"}

    def run_api(self, payload):
        """直接验证后端：不建会话，只在一个临时工作目录跑一轮。"""
        text = (payload.get("prompt") or "").strip()
        if not text:
            raise ApiError("prompt 不能为空", code="empty_prompt")
        name = payload.get("backend") or "claude-code"
        backend = self.backends.get(name)
        if backend is None:
            raise ApiError("未知后端: %s" % name, code="bad_backend")
        ws = ensure_dir(payload.get("workspace") or os.path.join(self.root, "tmp-" + uuid.uuid4().hex[:8]))
        sess = {"id": "probe-" + uuid.uuid4().hex[:8], "workspace": ws,
                "system_prompt": payload.get("system_prompt") or "你是执行型 agent，直接完成任务。",
                "messages": []}
        return {"result": backend.run(sess, user_text=text, hooks=lambda *a, **k: None)}
