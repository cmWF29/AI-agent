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
import time
import uuid

from ..kernel.api import ApiError, Module
from ..kernel.config import path_of
from ..kernel.store import ensure_dir


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
        self.args = a.get("args") or ["-p", "{prompt}", "--output-format", "json",
                                      "--permission-mode", "bypassPermissions"]
        self.timeout = int(a.get("timeout") or 0)  # 0 = 不设固定上限，靠插话/abort 中断
        self.extra_env = a.get("env") or {}

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
        out = err = ""
        aborted = False
        while True:
            try:
                out, err = p.communicate(timeout=2)
                break
            except subprocess.TimeoutExpired:
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
                    try:
                        out, err = p.communicate(timeout=5)
                    except subprocess.TimeoutExpired:
                        out, err = "", "aborted"
                    break
                if self.timeout and (time.time() - t0) >= self.timeout:
                    try:
                        p.kill()
                    except OSError:
                        pass
                    try:
                        out, err = p.communicate(timeout=5)
                    except subprocess.TimeoutExpired:
                        out, err = "", "timeout"
                    break
        out = (out or "").strip()
        err = (err or "").strip()
        if aborted:
            raise ApiError("agent 任务已被用户打断", code="backend_aborted")
        final = out
        meta = {}
        try:
            obj = json.loads(out)
            if isinstance(obj, dict):
                final = obj.get("result") or obj.get("content") or final
                meta = {k: obj.get(k) for k in ("session_id", "is_error", "total_cost_usd", "num_turns") if k in obj}
        except ValueError:
            pass
        if p.returncode != 0 and not final:
            raise ApiError("agent CLI 失败（exit %s）：%s" % (p.returncode, err[:300]),
                           code="backend_failed")
        ms = int((time.time() - t0) * 1000)
        if hooks:
            hooks("llm.response", {"text": final, "model": "claude-code", "ms": ms, **(meta or {})})
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
        self.backends.register("claude-code", self.claude, label="Claude Code CLI",
                               description="已有 agent 进程；使用本机文件/shell，不自建 ReAct")
        self.api.route("GET", "/api/agents/backends", name="backends")(self.backends_api)
        self.api.route("POST", "/api/agents/run", name="run")(self.run_api)
        self.log.info("agents.ready", backends=[b["name"] for b in self.backends.list()])

    def backends_api(self, payload=None):
        return {"items": self.backends.list(), "default": self.cfg.get("sessions", {}).get("backend") or "api"}

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
