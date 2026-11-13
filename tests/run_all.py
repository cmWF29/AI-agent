#!/usr/bin/env python3
"""端到端自测：只测“对外 API”和可观察行为，不测内部私有实现。

跑法：python3 tests/run_all.py
依赖：无（自带 mock LLM，不花钱、不需要真 key）
"""
from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "tests"))

from mock_llm import MockLLM          # noqa: E402
from hive.kernel import Kernel        # noqa: E402
from hive.kernel.bus import Bus       # noqa: E402
from hive.kernel.config import load_config  # noqa: E402
from hive.kernel.output import OutputPolicy  # noqa: E402

RESULTS = []


def check(name, cond, detail=""):
    RESULTS.append((name, bool(cond), detail))
    print(("  PASS " if cond else "  FAIL ") + name + (("  <- " + str(detail)[:300]) if detail and not cond else ""))


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


class Env:
    def __init__(self, mock, inline_max=1000, compact_threshold=800, with_http=False, keep_recent=2):
        self.tmp = tempfile.mkdtemp(prefix="hive-test-")
        self.port = free_port()
        cfg_path = os.path.join(self.tmp, "config", "config.json")
        os.makedirs(os.path.dirname(cfg_path), exist_ok=True)
        self.cfg = load_config(cfg_path, overrides={
            "llm": {"base_url": mock.base_url, "api_key": "test-key", "model": "mock-deepseek",
                    "max_retries": 1, "timeout": 20, "temperature": 0},
            "tool_output": {"inline_max_chars": inline_max, "preview_chars": 80},
            "secretary": {"compact_threshold_chars": compact_threshold, "keep_recent_messages": keep_recent},
            "server": {"port": self.port, "token": "test-token", "web_password": "pw123"},
            "observability": {"level": "debug"},
            "sessions": {"max_concurrent": 4},
        })
        self.kernel = Kernel(cfg=self.cfg, web_dir=os.path.join(REPO, "web"))
        self.kernel.boot()
        if with_http:
            self.kernel.start_http()
        self.api = self.kernel.ctx.api

    def http(self, path, method="GET", body=None, token="test-token", cookie=None):
        url = "http://127.0.0.1:%d%s" % (self.port, path)
        data = json.dumps(body).encode("utf-8") if body is not None else None
        req = urllib.request.Request(url, data=data, method=method)
        req.add_header("Content-Type", "application/json")
        if token:
            req.add_header("X-Auth-Token", token)
        if cookie:
            req.add_header("Cookie", cookie)
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                return resp.status, json.loads(resp.read().decode("utf-8")), dict(resp.headers)
        except urllib.error.HTTPError as e:
            try:
                return e.code, json.loads(e.read().decode("utf-8")), dict(e.headers)
            except ValueError:
                return e.code, {}, dict(e.headers)

    def close(self):
        try:
            self.kernel.stop()
        except Exception:
            pass
        shutil.rmtree(self.tmp, ignore_errors=True)


# ---------------- 用例 ----------------
def test_bus():
    print("[1] 事件总线")
    bus = Bus(workers=2, buffer=50)
    got = []
    bus.subscribe("ticket.*", lambda ev: got.append(ev["topic"]), name="t")
    bus.subscribe("session.created", lambda ev: got.append(ev["topic"]), name="t2")
    bus.publish("ticket.created", {"id": "T1"}, source="test")
    bus.publish("session.created", {"id": "s1"}, source="test")
    bus.publish("unrelated", {}, source="test")
    bus.wait_idle(2)
    check("通配订阅命中", "ticket.created" in got)
    check("精确订阅命中", "session.created" in got)
    check("无关事件不投递", "unrelated" not in got, got)
    check("事件计数", bus.stats()["events"] == 3, bus.stats())
    check("事件缓冲", len(bus.recent) == 3)
    bus.shutdown()


def test_output_policy(mock):
    print("[2] 工具输出策略")
    tmp = tempfile.mkdtemp(prefix="hive-out-")
    cfg = load_config(os.path.join(tmp, "config", "config.json"), overrides={
        "llm": {"base_url": mock.base_url, "api_key": "x"},
        "tool_output": {"inline_max_chars": 100, "preview_chars": 40},
    })
    pol = OutputPolicy(cfg)
    small = pol.apply("s1", "shell", "short output")
    big_text = "x" * 5000
    big = pol.apply("s1", "shell", big_text)
    check("小输出内联", small["mode"] == "inline" and small["text"] == "short output")
    check("大输出落盘", big["mode"] == "file" and os.path.exists(big["path"]), big.get("path"))
    check("落盘内容完整", open(big["path"], encoding="utf-8").read() == big_text)
    check("上下文里带路径和读法", "path=" in big["text"] and "grep" in big["text"])
    shutil.rmtree(tmp, ignore_errors=True)


def test_react_offload(mock):
    print("[3] ReAct 循环 + 大输出自动落盘")
    mock.set([
        {"tool_calls": [{"name": "shell", "arguments": {"command": "awk 'BEGIN{for(i=0;i<300;i++)printf \"x\"}'"}}]},
        {"content": "完成"},
    ])
    env = Env(mock, inline_max=80)
    try:
        session = {"id": "react-1", "messages": [], "workspace": os.path.join(env.tmp, "ws"),
                   "tools": ["shell"]}
        os.makedirs(session["workspace"], exist_ok=True)
        res = env.kernel.react.run(session=session)
        tool_msgs = [m for m in session["messages"] if m["role"] == "tool"]
        check("循环正常结束", res["status"] == "ok" and res["final"] == "完成", res)
        check("执行了工具", len(tool_msgs) == 1)
        check("大输出被替换为落盘提示",
              "path=" in tool_msgs[0]["content"] and "已落盘" in tool_msgs[0]["content"]
              and len(tool_msgs[0]["content"]) < 1200, len(tool_msgs[0]["content"]))
        path = [l.split("path=")[1] for l in tool_msgs[0]["content"].splitlines() if l.startswith("path=")][0]
        check("落盘文件存在", os.path.exists(path), path)
        check("上下文条数正确", len(session["messages"]) == 3, len(session["messages"]))
        events = [e["topic"] for e in env.kernel.bus.recent]
        check("发出 tool.result 事件", "tool.result" in events)
    finally:
        env.close()


def test_react_interrupt(mock):
    print("[4] ReAct 插话/打断")
    mock.set([
        {"tool_calls": [{"name": "shell", "arguments": {"command": "sleep 0.2"}}]},
        {"content": "第二轮"},
    ])
    env = Env(mock)
    try:
        session = {"id": "react-2", "messages": [], "workspace": os.path.join(env.tmp, "ws2"), "tools": ["shell"]}
        os.makedirs(session["workspace"], exist_ok=True)
        calls = {"n": 0}

        def drain2():
            calls["n"] += 1
            if calls["n"] == 1:
                return [{"kind": "note", "text": "顺便把 A 也改了"}]
            return []
        res = env.kernel.react.run(session=session, drain=drain2)
        contents = " ".join(m.get("content") or "" for m in session["messages"])
        check("插话进入上下文", "顺便把 A 也改了" in contents)
        check("插话后仍正常结束", res["status"] == "ok", res)
    finally:
        env.close()


def test_sessions_compact(mock):
    print("[5] 会话 API：常驻秘书 / 收回复 / 压缩 / 销毁")
    tail = "x" * 900
    mock.set([{"content": "第一轮回复" + tail}, {"content": "第二轮回复" + tail},
              {"content": "这是压缩后的摘要_ACK"}])
    env = Env(mock, compact_threshold=10 ** 9)   # 关掉自动压缩，先测手动
    try:
        r1 = env.api("sessions.ask", text="你好", timeout=30)
        check("秘书自动创建并回复",
              r1.get("status") == "ok" and (r1.get("reply") or "").startswith("第一轮回复"), (r1.get("status"), len(r1.get("reply") or "")))
        r2 = env.api("sessions.ask", text="第二句", timeout=30)
        check("同一会话继续对话", (r2.get("reply") or "").startswith("第二轮回复"), len(r2.get("reply") or ""))
        rec = env.api("sessions.get", session_id="secretary")["session"]
        check("会话消息累积", rec["messages"] >= 5, rec["messages"])
        msg = env.api("sessions.messages", session_id="secretary", limit=10)
        check("消息 API 可读", msg["total"] >= 5)
        comp = env.api("sessions.compact", session_id="secretary")
        check("手动压缩生效", comp.get("compacted") is True and comp["after_chars"] < comp["before_chars"], comp)
        after = env.api("sessions.messages", session_id="secretary", limit=10)
        joined = " ".join(i["content"] for i in after["items"])
        check("压缩后保留摘要", "这是压缩后的摘要_ACK" in joined, joined[:200])
        listed = env.api("sessions.list")
        check("会话列表正确", any(i["id"] == "secretary" for i in listed["items"]))
        env.api("sessions.destroy", session_id="secretary")
        check("销毁后会话消失", env.api("sessions.list")["total"] == 0)
        check("销毁后归档存在", os.path.exists(os.path.join(env.tmp, "data", "sessions", "archive", "secretary.json")))
    finally:
        env.close()


def test_tickets(mock):
    print("[6] 工单：PM 编排 / 角色 / 结单沉淀 / 临时会话销毁")
    mock.set([
        {"content": "已安排：架构+开发两个角色"},                     # PM 首次应答
        {"content": "角色交付：/tmp/x.py 已改好"},                    # 角色应答
        {"content": "DONE"},                                         # 角色归档应答
        {"content": "DONE"},                                         # PM 归档应答
    ])
    env = Env(mock, inline_max=500)
    try:
        t = env.api("tickets.create", goal="把 README 补一版架构说明", project="demo")["ticket"]
        check("工单创建", t["status"] == "running" and t["pm"], t)
        pm = t["pm"]
        env.api("sessions.wait", session=pm, timeout=30)
        role = env.api("tickets.roles", ticket_id=t["id"], role="architect", task="输出架构说明")["role"]
        env.api("sessions.wait", session=role["session"], timeout=30)
        detail = env.api("tickets.get", ticket_id=t["id"])["ticket"]
        check("角色已登记", len(detail["roles"]) == 1 and detail["roles"][0]["role"] == "architect", detail["roles"])
        check("角色会话在跑且已完成", detail["roles"][0]["state"] in ("idle", "running"), detail["roles"][0])
        closed = env.api("tickets.close", ticket_id=t["id"], summary="README 已补齐")["ticket"]
        check("结单成功", closed["status"] == "closed", closed)
        check("结单后 PM 销毁", not closed["pm"], closed["pm"])
        check("结单后角色销毁", closed["roles"] and closed["roles"][0]["status"] == "destroyed", closed["roles"])
        kpath = os.path.join(env.tmp, "data", "knowledge", "tickets", t["id"], "00-summary.md")
        check("工单知识归档", os.path.exists(kpath), kpath)
        if os.path.exists(kpath):
            check("归档内容含结论", "README 已补齐" in open(kpath, encoding="utf-8").read())
        live = env.api("sessions.list")["items"]
        check("临时会话已清空", all(i["kind"] != "role" for i in live), [i["id"] for i in live])
        topics = [e["topic"] for e in env.kernel.bus.recent]
        check("发出 ticket.closed 事件", "ticket.closed" in topics)
        check("发出 ticket.closing 事件", "ticket.closing" in topics)
    finally:
        env.close()


def test_http_auth(mock):
    print("[7] HTTP 层：鉴权 / 登录 / 健康检查")
    mock.set([{"content": "ok"}])
    env = Env(mock, with_http=True)
    try:
        st, body, _ = env.http("/api/health", token="")
        check("健康检查免鉴权", st == 200 and body.get("status") == "ok", (st, body))
        st, body, _ = env.http("/api/ops/status", token="")
        check("业务接口需要鉴权", st == 401, st)
        st, body, _ = env.http("/api/ops/status", token="test-token")
        check("带 token 可访问", st == 200 and body.get("ok") is True and "version" in body, (st, body))
        st, body, _ = env.http("/api/auth/login", method="POST", body={"password": "wrong"}, token="")
        check("错误密码拒绝", st == 401, st)
        st, body, headers = env.http("/api/auth/login", method="POST", body={"password": "pw123"}, token="")
        check("正确密码登录", st == 200 and body.get("token"), (st, body))
        cookie = (headers.get("Set-Cookie") or "").split(";")[0]
        st, body, _ = env.http("/api/ops/status", token="", cookie=cookie)
        check("cookie 可鉴权", st == 200, st)
        st, body, _ = env.http("/api/health/self", token="")
        check("深度自检", st == 200 and "checks" in body, (st, body))
        st, body, _ = env.http("/api/obs/metrics", token="test-token")
        check("维测指标可读", st == 200 and "topics" in body, st)
        st, body, _ = env.http("/api/bus/publish", method="POST",
                               body={"topic": "test.from.http", "payload": {"a": 1}}, token="test-token")
        check("外部可向总线投事件", st == 200 and body.get("event", {}).get("topic") == "test.from.http", (st, body))
        req = urllib.request.Request("http://127.0.0.1:%d/" % env.port)
        with urllib.request.urlopen(req, timeout=10) as resp:
            html = resp.read().decode("utf-8", "ignore")
        check("网页首页可访问", "Hive" in html and resp.status == 200, len(html))
    finally:
        env.close()


def test_cli_and_webchat(mock):
    print("[8] CLI + 网页对话（网页确实是通过 CLI 跑的）")
    mock.set([{"content": "这是秘书的回复"}])
    env = Env(mock, with_http=True)
    try:
        cmd = [sys.executable, "-m", "hive.cli", "ask", "--text", "你好", "--json",
               "--url", "http://127.0.0.1:%d" % env.port, "--token", "test-token", "--timeout", "60"]
        env_vars = dict(os.environ, PYTHONPATH=REPO)
        proc = subprocess.run(cmd, cwd=REPO, capture_output=True, text=True, timeout=120, env=env_vars)
        out = (proc.stdout or "").strip().splitlines()
        parsed = json.loads(out[-1]) if out else {}
        check("CLI 执行成功", proc.returncode == 0 and parsed.get("ok") is True, (proc.returncode, proc.stderr[-300:]))
        check("CLI 拿到秘书回复", parsed.get("reply") == "这是秘书的回复", parsed)

        st, body, _ = env.http("/api/chat/send", method="POST", body={"text": "网页来的消息"})
        check("网页发送被接受", st == 200 and body.get("job_id"), (st, body))
        job_id = body["job_id"]
        job = {}
        for _ in range(90):
            time.sleep(1)
            st, payload, _ = env.http("/api/chat/job/%s" % job_id)
            job = payload.get("job") or {}
            if job.get("status") != "running":
                break
        check("网页任务完成", job.get("status") == "done", job)
        check("网页拿到回复", bool(job.get("reply")), job.get("reply"))
        check("网页走的是 CLI", "hive.cli" in (job.get("log") or "") or job.get("via") == "cli", job.get("via"))
        hist = env.http("/api/chat/history?limit=5")[1]
        check("历史可读", hist.get("total", 0) >= 1, hist.get("total"))
    finally:
        env.close()


def test_ops(mock):
    print("[9] 运维命令 / 状态 / 版本")
    mock.set([{"content": "ok"}])
    env = Env(mock, with_http=True)
    try:
        st, s, _ = env.http("/api/ops/status")
        check("状态含模块与 llm", s.get("ok") and s["llm"]["model"] == "mock-deepseek", s.get("llm"))
        st, v, _ = env.http("/api/ops/versions")
        check("版本接口可用", st == 200 and v.get("version"), v.get("git", {}).get("available"))
        st, st2, _ = env.http("/api/ops/selftest", method="POST", body={"ping_llm": True})
        check("自检通过", st == 200 and "checks" in st2, st2.get("checks", {}).keys())
        st, cfgv, _ = env.http("/api/ops/config")
        check("配置接口不泄露密钥", st == 200 and "api_key" not in cfgv["config"]["llm"], cfgv["config"]["llm"].keys())
        control = os.path.join(env.tmp, "data", "control")
        env.http("/api/ops/restart", method="POST", body={})
        files = [f for f in os.listdir(control) if f.startswith("cmd-")]
        check("重启命令写入控制文件", any("restart" in f for f in files), files)
        st, health, _ = env.http("/api/health/self")
        check("健康自检含关键项", health.get("healthy") is True and len(health.get("checks", [])) >= 5, health.get("failed"))
    finally:
        env.close()


def test_secretary_policy(mock):
    print("[10] 秘书的工具策略：只发作业，没有执行权")
    mock.set([{"content": "工单已派出"}])
    env = Env(mock)
    try:
        env.api("sessions.ensure")
        sec = env.api("sessions.get", session_id="secretary")["session"]
        tools = sec.get("tools") or []
        for banned in ("shell", "read_file", "write_file", "grep", "http_get"):
            check("秘书没有 %s 工具" % banned, banned not in tools, tools)
        check("秘书有 ticket_create", "ticket_create" in tools, tools)
        check("秘书有 project_list", "project_list" in tools, tools)
    finally:
        env.close()


def test_projects_and_concurrency(mock):
    print("[11] 多项目 + 多工单并发")
    mock.set([{"content": "PM-A 已安排"}, {"content": "PM-B 已安排"},
              {"content": "PM-A 收尾"}, {"content": "PM-B 收尾"}])
    env = Env(mock, with_http=True)
    try:
        p = env.api("projects.create", name="alpha", title="阿尔法项目")["project"]
        check("项目创建", p["id"] == "alpha", p)
        check("项目幂等", env.api("projects.ensure", name="alpha")["project"]["id"] == "alpha")

        t1 = env.api("tickets.create", goal="任务一", project="alpha")["ticket"]
        t2 = env.api("tickets.create", goal="任务二", project="beta")["ticket"]
        check("两个工单同时存在", t1["id"] != t2["id"] and t1["status"] == "running" and t2["status"] == "running")
        check("工单挂在项目上", t1["project"] == "alpha" and t2["project"] == "beta", (t1["project"], t2["project"]))
        check("未登记的项目被自动创建",
              env.api("projects.get", project_id="beta")["project"]["id"] == "beta")

        env.api("sessions.wait", session=t1["pm"], timeout=30)
        env.api("sessions.wait", session=t2["pm"], timeout=30)
        a = env.api("projects.get", project_id="alpha")["project"]
        check("项目统计工单数", a["ticket_count"] == 1 and a["open_tickets"] == 1, a.get("ticket_count"))
        listing = env.api("tickets.list", project="alpha")["items"]
        check("工单按项目过滤", len(listing) == 1 and listing[0]["id"] == t1["id"], listing)

        st = env.api("sessions.state")
        check("并发闸门可见", st["active"] >= 0 and st["max_concurrent"] == 4, st)

        # 两个 PM 分别收到自己的任务，不串话
        m1 = env.api("sessions.messages", session_id=t1["pm"], limit=10)
        m2 = env.api("sessions.messages", session_id=t2["pm"], limit=10)
        text1 = " ".join(i["content"] for i in m1["items"])
        text2 = " ".join(i["content"] for i in m2["items"])
        check("PM 各自拿到自己的工单", "任务一" in text1 and "任务二" not in text1, text1[:80])
        check("第二个 PM 没被串话", "任务二" in text2, text2[:80])
    finally:
        env.close()


def test_group_chat(mock):
    print("[12] 群聊：分组 / 时间线 / 对工单说话 / 交付件")
    mock.set([
        {"content": "我是秘书，已开工单"},                              # 秘书
        {"content": "PM 收到，开始编排"},                               # PM
        {"content": "再补一条要求：要写测试"},                          # PM 收到群聊插话
        {"tool_calls": [{"name": "write_file", "arguments": {
            "path": "deliver/report.md", "content": "# 报告\n交付完成\n"}}]},
        {"content": "交付完成：deliver/report.md"},                     # 角色
    ])
    env = Env(mock, with_http=True)
    try:
        env.api("sessions.ask", text="帮我做一份报告", timeout=30)
        groups = env.http("/api/web/groups")[1]
        check("群列表含秘书", any(g["id"] == "secretary" for g in groups["items"]), groups["items"])
        check("群列表含项目", len(groups.get("projects", [])) >= 1, groups.get("projects"))

        tl = env.http("/api/web/timeline?group=secretary&limit=50")[1]
        check("秘书时间线可读", len(tl["items"]) >= 2, len(tl.get("items", [])))
        check("时间线有用户发言", any(i["role"] == "user" for i in tl["items"]))
        check("时间线有助手发言", any(i["role"] == "assistant" for i in tl["items"]))
        check("时间线带 ts", all(i.get("ts") is not None for i in tl["items"]))

        t = env.api("tickets.create", goal="写一份报告", project="default")["ticket"]
        env.api("sessions.wait", session=t["pm"], timeout=30)
        msg = env.http("/api/tickets/%s/message" % t["id"], method="POST",
                       body={"text": "再补一条要求：要写测试"})[1]
        check("工单群消息投递给 PM", msg.get("session") == t["pm"], msg)

        role = env.api("tickets.roles", ticket_id=t["id"], role="writer", task="写报告")["role"]
        env.api("sessions.wait", session=role["session"], timeout=30)

        tl2 = env.http("/api/web/timeline?group=%s&limit=80" % t["id"])[1]
        speakers = [i["speaker"] for i in tl2["items"]]
        check("工单时间线聚合 PM 与角色", any("PM" in s for s in speakers) and any("writer" in s for s in speakers), speakers[:6])
        check("工单时间线含系统事件", any(i["role"] == "event" for i in tl2["items"]), len(tl2["items"]))

        files = env.http("/api/tickets/%s/files" % t["id"])[1]
        check("交付件可见", any(f["path"].endswith("report.md") for f in files["items"]), files)
        rel = [x["path"] for x in files["items"] if x["path"].endswith("report.md")][0]
        f = env.http("/api/tickets/%s/file?path=%s" % (t["id"], urllib.parse.quote(rel)))[1]
        check("交付件可读", "交付完成" in (f.get("text") or ""), f.get("text", "")[:60])
        bad = env.http("/api/tickets/%s/file?path=../../config/config.json" % t["id"])[1]
        check("路径穿越被拒", bad.get("ok") is False, bad)
    finally:
        env.close()


def test_versions(mock):
    print("[13] 版本管理：列表 / 指定版本回退")
    mock.set([{"content": "ok"}])
    env = Env(mock, with_http=True)
    try:
        root = env.tmp
        subprocess.run(["git", "init", "-q"], cwd=root, check=True)
        subprocess.run(["git", "config", "user.email", "t@t"], cwd=root, check=True)
        subprocess.run(["git", "config", "user.name", "t"], cwd=root, check=True)
        open(os.path.join(root, "VERSION"), "w").write("0.0.1")
        subprocess.run(["git", "add", "-A"], cwd=root, check=True)
        subprocess.run(["git", "commit", "-qm", "v1"], cwd=root, check=True)
        open(os.path.join(root, "VERSION"), "w").write("0.0.2")
        subprocess.run(["git", "commit", "-aqm", "v2"], cwd=root, check=True)

        v = env.http("/api/ops/versions")[1]
        check("版本列表有 commits", len(v["git"].get("commits", [])) >= 2, v["git"].get("log"))
        check("当前版本被标记", any(c["current"] for c in v["git"]["commits"]), v["git"]["commits"])
        old = [c for c in v["git"]["commits"] if not c["current"]][0]

        st, r, _ = env.http("/api/ops/rollback", method="POST", body={"target": old["short"]})
        check("回退到指定版本被接受", st == 200 and r["target"] == old["short"], r)
        control = os.path.join(root, "data", "control")
        cmds = [f for f in os.listdir(control) if f.startswith("cmd-")]
        payloads = []
        for f in cmds:
            try:
                payloads.append(json.load(open(os.path.join(control, f), encoding="utf-8")))
            except ValueError:
                pass
        check("控制文件带 target", any(p.get("target") == old["short"] for p in payloads), payloads)
        bad = env.http("/api/ops/rollback", method="POST", body={"target": "a;rm -rf /"})[1]
        check("非法 target 被拒", bad.get("ok") is False, bad)
    finally:
        env.close()


def main():
    mock = MockLLM().start()
    print("mock llm:", mock.base_url)
    tests = [test_bus, test_output_policy, test_react_offload, test_react_interrupt,
             test_sessions_compact, test_tickets, test_http_auth, test_cli_and_webchat, test_ops,
             test_secretary_policy, test_projects_and_concurrency, test_group_chat, test_versions]
    t0 = time.time()
    for t in tests:
        try:
            if t in (test_bus,):
                t()
            else:
                t(mock)
        except Exception as exc:
            import traceback
            traceback.print_exc()
            check(t.__name__ + " 未崩溃", False, repr(exc))
        print()
    mock.stop()
    passed = sum(1 for _, ok, _ in RESULTS if ok)
    total = len(RESULTS)
    print("=" * 60)
    print("结果: %d/%d 通过，用时 %.1fs" % (passed, total, time.time() - t0))
    if passed != total:
        for name, ok, detail in RESULTS:
            if not ok:
                print("  ✗ %s  %s" % (name, detail))
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
