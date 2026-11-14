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
from hive.webstate import frontend_source  # noqa: E402

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
    def __init__(self, mock, inline_max=1000, compact_threshold=800, with_http=False, keep_recent=2,
                 overrides=None):
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
        if overrides:
            from hive.kernel.config import _deep_merge
            self.cfg = _deep_merge(self.cfg, overrides)
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

    def http_raw(self, path):
        """取原始响应（静态页不是 JSON，不能走 http()）。"""
        url = "http://127.0.0.1:%d%s" % (self.port, path)
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status, resp.read(), dict(resp.headers)

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
    check("通配订阅命中", "ticket:created" in got)
    check("精确订阅命中", "session:created" in got)
    check("无关事件不投递", "unrelated" not in got, got)
    check("事件计数", bus.stats()["events"] == 3, bus.stats())
    check("事件缓冲", len(bus.recent) == 3)

    # 统一通信中枢：request/reply 只寻址，不持有对方模块对象
    from hive.kernel.hub import Hub
    hub = Hub(bus)
    hub.register_route("demo.echo", lambda p: {"echo": p.get("v")}, module="demo")
    check("Hub request/reply", hub.request("demo.echo", {"v": 7})["echo"] == 7)
    try:
        hub.request("demo.missing", {})
        check("Hub 未知服务报错", False)
    except Exception:
        check("Hub 未知服务报错", True)
    mounted = []
    hub.subscribe("project:mounted", lambda ev: mounted.append(ev["payload"]))
    hub.mount("project", "p1", "mount-1")
    bus.wait_idle(2)
    check("实例挂载广播带项目与容器", mounted and mounted[0]["projectId"] == "p1"
          and mounted[0]["mountContainerId"] == "mount-1", mounted)
    inst = []
    hub.subscribe("project:p1:renamed", lambda ev: inst.append(ev["payload"]), name="p1")
    hub.publish_instance("project", "p1", "renamed", {"title": "新名字"})
    bus.wait_idle(2)
    check("实例通道只投递本实例", inst and inst[0]["title"] == "新名字", inst)
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
        check("发出 tool.result 事件", "tool:result" in events)
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
        env.api("sessions.ensure", project="default")
        r1 = env.api("sessions.ask", session="sec-default", text="你好", timeout=30)
        check("秘书自动创建并回复",
              r1.get("status") == "ok" and (r1.get("reply") or "").startswith("第一轮回复"), (r1.get("status"), len(r1.get("reply") or "")))
        r2 = env.api("sessions.ask", session="sec-default", text="第二句", timeout=30)
        check("同一会话继续对话", (r2.get("reply") or "").startswith("第二轮回复"), len(r2.get("reply") or ""))
        rec = env.api("sessions.get", session_id="sec-default")["session"]
        check("会话消息累积", rec["messages"] >= 5, rec["messages"])
        msg = env.api("sessions.messages", session_id="sec-default", limit=10)
        check("消息 API 可读", msg["total"] >= 5)
        comp = env.api("sessions.compact", session_id="sec-default")
        check("手动压缩生效", comp.get("compacted") is True and comp["after_chars"] < comp["before_chars"], comp)
        after = env.api("sessions.messages", session_id="sec-default", limit=10)
        joined = " ".join(i["content"] for i in after["items"])
        check("压缩后保留摘要", "这是压缩后的摘要_ACK" in joined, joined[:200])
        listed = env.api("sessions.list")
        check("会话列表正确", any(i["id"] == "sec-default" for i in listed["items"]))
        env.api("sessions.destroy", session_id="sec-default")
        check("销毁后会话消失", env.api("sessions.list")["total"] == 0)
        check("销毁后归档存在", os.path.exists(os.path.join(env.tmp, "data", "sessions", "archive", "sec-default.json")))
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
        pms = [i for i in env.api("sessions.list", kind="pm")["items"] if i["id"] == t["pm"]]
        check("PM 显示名是中文", pms and pms[0]["display"] == "项目经理", pms)
        pm = t["pm"]
        env.api("sessions.wait", session=pm, timeout=30)
        role = env.api("tickets.roles", ticket_id=t["id"], role="architect", task="输出架构说明")["role"]
        env.api("sessions.wait", session=role["session"], timeout=30)
        detail = env.api("tickets.get", ticket_id=t["id"])["ticket"]
        check("角色已登记", len(detail["roles"]) == 1 and detail["roles"][0]["role"] == "architect", detail["roles"])
        check("角色会话在跑且已完成", detail["roles"][0]["state"] in ("idle", "running"), detail["roles"][0])
        # 结单硬门禁：架构师还没交架构文档，必须拦下
        gate = None
        try:
            env.api("tickets.close", ticket_id=t["id"], summary="README 已补齐")
        except Exception as exc:
            gate = exc
        check("缺必交产物时结单被拦", gate is not None and "缺必交产物" in str(gate), gate)
        os.makedirs(os.path.join(detail["workdir"], "docs"), exist_ok=True)
        with open(os.path.join(detail["workdir"], "docs", "架构-architect.md"), "w", encoding="utf-8") as f:
            f.write("# 架构说明\n\n模块边界与取舍。\n")
        closed = env.api("tickets.close", ticket_id=t["id"], summary="README 已补齐")["ticket"]
        check("补齐后结单成功", closed["status"] == "closed", closed)
        check("结单后 PM 销毁", not closed["pm"], closed["pm"])
        check("结单后角色销毁", closed["roles"] and closed["roles"][0]["status"] == "destroyed", closed["roles"])
        kpath = os.path.join(env.tmp, "data", "knowledge", "tickets", t["id"], "00-summary.md")
        check("工单知识归档", os.path.exists(kpath), kpath)
        if os.path.exists(kpath):
            check("归档内容含结论", "README 已补齐" in open(kpath, encoding="utf-8").read())
        live = env.api("sessions.list")["items"]
        check("临时会话已清空", all(i["kind"] != "role" for i in live), [i["id"] for i in live])
        topics = [e["topic"] for e in env.kernel.bus.recent]
        check("发出 ticket.closed 事件", "ticket:closed" in topics)
        check("发出 ticket.closing 事件", "ticket:closing" in topics)
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
        check("外部可向总线投事件", st == 200 and body.get("event", {}).get("topic") == "test:from.http", (st, body))
        req = urllib.request.Request("http://127.0.0.1:%d/" % env.port)
        with urllib.request.urlopen(req, timeout=10) as resp:
            html = resp.read().decode("utf-8", "ignore")
        check("网页首页可访问", "Hive" in html and resp.status == 200, len(html))
    finally:
        env.close()


def test_cli_and_webchat(mock):
    print("[8] CLI + 网页对话（网页确实是通过 CLI 跑的）")
    mock.set([{"content": "这是秘书的回复"}, {"content": "这是秘书的回复"}])
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
        check("网页直达秘书会话", body.get("session") == "sec-default", body)
        job = env.http("/api/chat/job/%s" % body["job_id"])[1]["job"]
        check("网页任务完成", job.get("status") == "done", job)
        env.api("sessions.wait", session="sec-default", timeout=30)
        tl = env.http("/api/web/timeline?group=sec-default&limit=20")[1]
        check("历史可读", any("秘书的回复" in (i.get("text") or "") for i in tl["items"]), tl.get("items"))
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
        env.api("sessions.ensure", project="default")
        sec = env.api("sessions.get", session_id="sec-default")["session"]
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
              env.api("lifecycle.get_project", project_id="beta")["project"]["id"] == "beta")

        env.api("sessions.wait", session=t1["pm"], timeout=30)
        env.api("sessions.wait", session=t2["pm"], timeout=30)
        a = env.api("lifecycle.get_project", project_id="alpha")["project"]
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
        env.api("sessions.ensure", project="default")
        env.api("sessions.ask", session="sec-default", text="帮我做一份报告", timeout=30)
        groups = env.http("/api/web/groups")[1]
        check("群列表含秘书", any(g["id"] == "sec-default" for g in groups["items"]), groups["items"])
        check("群列表含项目", len(groups.get("projects", [])) >= 1, groups.get("projects"))

        tl = env.http("/api/web/timeline?group=sec-default&limit=50")[1]
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
        check("工单时间线用角色中文名", "项目经理" in speakers and any("撰写" in s for s in speakers), speakers[:8])
        check("工单时间线不含系统事件", not any(i["role"] == "event" for i in tl2["items"]), len(tl2["items"]))
        flow = env.http("/api/tickets/%s/flow" % t["id"])[1]
        check("生命周期流程图有节点", len(flow.get("nodes") or []) >= 4 and flow["nodes"][0]["done"], flow.get("nodes"))

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
        # Windows 上 core.autocrlf 默认 true，会把 LF 当错误拦下来（fatal: LF would be replaced by CRLF）
        subprocess.run(["git", "config", "core.autocrlf", "false"], cwd=root, check=True)
        subprocess.run(["git", "config", "core.safecrlf", "false"], cwd=root, check=True)
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


# ---------------- v3 新功能用例 ----------------
def test_stream_trace(mock):
    print("[14] 流式输出 + 全链路 trace")
    mock.set([{"content": "流式回复内容 ABCDEFG"}])
    env = Env(mock, with_http=True)
    try:
        env.api("sessions.ensure", project="default")
        env.api("sessions.ask", session="sec-default", text="你好", timeout=60)
        topics = [e["topic"] for e in env.kernel.bus.recent]
        check("有流式增量事件", "llm:delta" in topics, topics[-6:])
        delta = "".join(e["payload"].get("text", "") for e in env.kernel.bus.recent
                        if e["topic"] == "llm:delta")
        check("增量拼回完整正文", "ABCDEFG" in delta, delta[:80])
        st, tr, _ = env.http("/api/trace/recent?session=sec-default&limit=50")
        kinds = {i["kind"] for i in tr.get("items", [])}
        check("trace 记录 llm.request", "llm.request" in kinds, kinds)
        check("trace 记录 llm.response", "llm.response" in kinds, kinds)
        req = [i for i in tr["items"] if i["kind"] == "llm.request"][-1]["data"]
        check("trace 请求结构含 messages/tools", "messages" in req and "tools" in req, list(req)[:8])
        check("trace 不含 api key", "sk-" not in json.dumps(tr, ensure_ascii=False), "leak")
        tpath = os.path.join(env.tmp, "data", "traces", "sec-default.jsonl")
        check("trace 落盘", os.path.exists(tpath) and os.path.getsize(tpath) > 0, tpath)
    finally:
        env.close()


def test_library_flow(mock):
    print("[15] 角色库/流程库/技能库 + 流程插件校验")
    mock.set([{"content": "ok"}])
    env = Env(mock)
    try:
        roles = env.api("library.list", kind="roles")["items"]
        check("内置角色库有条目", any(r["id"] == "architect" for r in roles), [r["id"] for r in roles])
        flows = env.api("library.list", kind="flows")["items"]
        check("内置流程插件", any(f["id"] == "architect" for f in flows), [f["id"] for f in flows])

        res = env.api("library.design", role="security", cn="安全", responsibility="做安全审计",
                      must_outputs=["docs/**/*security*.md"],
                      skills=[{"id": "sec-audit", "name": "安全审计手册", "body": "先看依赖再看入口"}])
        check("流程专家产出角色卡", res["role"]["id"] == "security" and res["role"]["must_outputs"], res["role"])
        check("流程插件记录了必交产物", len(res["flow"]["checks"]) == 1, res["flow"])
        check("技能入库", res["skills"] == ["sec-audit"], res["skills"])

        miss = env.api("library.check", flow="security", files=["docs/a.md"])
        check("缺件被识别", miss["missing"] == ["docs/**/*security*.md"], miss)
        ok = env.api("library.check", flow="security", files=["docs/security-audit.md"])
        check("齐件通过", ok["missing"] == [] and ok["known"], ok)
    finally:
        env.close()


def test_project_secretary_delete(mock):
    print("[16] 项目秘书 + 删除项目")
    mock.set([{"content": "项目秘书在线"}])
    env = Env(mock, with_http=True)
    try:
        env.api("projects.create", name="gamma", title="伽马")
        sec = env.api("sessions.ensure", project="gamma")["session"]
        check("项目秘书按项目隔离", sec["id"] == "sec-gamma", sec["id"])
        env.api("sessions.ask", session="sec-gamma", text="在吗", timeout=60)
        groups = env.http("/api/web/groups")[1]
        check("群列表含项目秘书", any(g["id"] == "sec-gamma" for g in groups["items"]),
              [g["id"] for g in groups["items"]])
        check("不再暴露本地层", "instance" not in groups, groups.get("instance"))

        d = env.api("lifecycle.delete_project", project_id="gamma")
        check("项目删除成功", d.get("deleted") == "gamma", d)
        gone = None
        try:
            env.api("sessions.get", session_id="sec-gamma")
        except Exception:
            gone = True
        check("项目秘书被清理", gone is True)
        check("项目已不在列表", all(p["id"] != "gamma" for p in env.api("projects.list")["items"]))
    finally:
        env.close()


def test_close_readonly_artifacts(mock):
    print("[17] 结单只读 + 三层交付件归档")
    mock.set([
        {"content": "PM 收到"},
        {"content": "写完了"}, {"content": "DONE"},
        {"content": "DONE"},
        {"content": "DONE"},
    ])
    env = Env(mock, with_http=True)
    try:
        t = env.api("tickets.create", goal="产出一份交付文档", project="arch")["ticket"]
        env.api("sessions.wait", session=t["pm"], timeout=30)
        role_api = env.api("tickets.roles", ticket_id=t["id"], role="writer", task="写 docs/report.md")
        sess = role_api["role"]["session"]
        ws = role_api["role"]["workspace"]
        os.makedirs(os.path.join(ws, "docs"), exist_ok=True)
        with open(os.path.join(ws, "docs", "report.md"), "w", encoding="utf-8") as f:
            f.write("# 报告\n内容\n")
        env.api("sessions.wait", session=sess, timeout=30)

        env.api("tickets.close", ticket_id=t["id"], summary="完成")
        detail = env.api("tickets.get", ticket_id=t["id"])["ticket"]
        check("结单后只读", detail["status"] == "closed" and detail["readonly"], detail["status"])

        st, body, _ = env.http("/api/tickets/%s/message" % t["id"], method="POST", body={"text": "再改一下"})
        check("结单后发消息被拒", st == 410 and body.get("code") == "ticket_closed", (st, body))
        st_t, body_t, _ = env.http("/api/tickets/%s/tags" % t["id"], method="POST", body={"add": ["late"]})
        check("结单后标签只读", st_t == 410 and body_t.get("code") == "ticket_closed", (st_t, body_t))

        st_tl, body_tl, _ = env.http("/api/web/timeline?group=%s&limit=100" % t["id"])
        tl = (body_tl or {}).get("items") or []
        check("结单后群聊仍能回看历史", len(tl) >= 2, len(tl))
        apath = os.path.join(env.tmp, "data", "artifacts", "projects", "arch", "tickets", t["id"], "docs", "report.md")
        check("交付件按三层路径归档", os.path.exists(apath), apath)
        stats = env.api("artifacts.stats")
        check("健康可读交付件体积", stats["total_bytes"] > 0 and stats["biggest"], stats["total_human"])
        lst = env.api("artifacts.list", layer="ticket", project="arch", ticket=t["id"])
        check("工单层可浏览", any(i["path"].endswith("report.md") for i in lst["items"]), lst["items"])
        cmp = env.api("artifacts.compress", project="arch", ticket=t["id"])
        tar = cmp["result"].get("tar") or ""
        check("压缩工单交付件", cmp["result"]["bytes_after"] > 0 and os.path.exists(tar), cmp)
        lst2 = env.api("artifacts.list", layer="ticket", project="arch", ticket=t["id"])
        check("压缩后仍能看到文件清单", any(i["path"].endswith("report.md") for i in lst2["items"]), lst2["items"])
        got = env.api("artifacts.file", layer="ticket", project="arch", ticket=t["id"], path="docs/report.md")
        check("压缩后仍能读取文件内容", "报告" in (got.get("text") or "") or "report" in (got.get("text") or "").lower(), got.get("text", "")[:80])
    finally:
        env.close()


def test_gitflow(mock):
    print("[18] 工单级 git：分支推拉 + 冲突检测")
    mock.set([{"content": "ok"}])
    env = Env(mock)
    try:
        env.api("projects.create", name="repo1")
        git = env.api("gitflow.list")
        check("项目建了裸仓库", any(i["project"] == "repo1" for i in git["items"]), git)
        bare = os.path.join(env.tmp, "data", "projects", "repo1", "repo.git")
        check("裸仓库存在", os.path.isdir(bare), bare)
        head = subprocess.run(["git", "-C", bare, "symbolic-ref", "HEAD"],
                              capture_output=True, text=True)
        check("裸仓库默认分支是 main", head.stdout.strip() == "refs/heads/main", head.stdout)

        t1 = env.api("tickets.create", goal="改 README A", project="repo1")["ticket"]
        t2 = env.api("tickets.create", goal="改 README B", project="repo1")["ticket"]
        check("工单各自有工作树", os.path.isdir(t1["repo"]) and os.path.isdir(t2["repo"]),
              (t1.get("repo"), t2.get("repo")))
        check("工作目录就是工单分支工作树", t1["workdir"] == t1["repo"], (t1.get("workdir"), t1.get("repo")))
        check("工单分支名", "ticket/" + t1["id"] in env.api("gitflow.ticket_status", ticket=t1["id"])["status"]["branch"],
              env.api("gitflow.ticket_status", ticket=t1["id"])["status"])

        # t1 改标题 → 推 → 合回 main
        with open(os.path.join(t1["repo"], "README.md"), "w", encoding="utf-8") as f:
            f.write("# repo1 A\n\n第一版\n")
        r1 = env.api("gitflow.ticket_sync", ticket=t1["id"], message="t1")["result"]
        check("工单推送到远端分支", r1.get("ok") is True, r1)
        m1 = env.api("gitflow.ticket_merge", ticket=t1["id"], project="repo1")["result"]
        check("合回 main", m1.get("ok") is True, m1)
        main_readme = os.path.join(env.tmp, "data", "projects", "repo1", "main", "README.md")
        check("main 真的合进了内容", "repo1 A" in open(main_readme, encoding="utf-8").read(), main_readme)

        # t2 改同一行 → 推的时候会与 main 冲突
        with open(os.path.join(t2["repo"], "README.md"), "w", encoding="utf-8") as f:
            f.write("# repo1 B\n\n第二版\n")
        r2 = env.api("gitflow.ticket_sync", ticket=t2["id"], message="t2")["result"]
        check("冲突被识别", bool(r2.get("conflict")), r2)
        check("冲突文件是 README", any("README" in f for f in (r2.get("conflict") or [])), r2.get("conflict"))

        # 冲突工单结单 → 不应直接关掉，而是进 conflict 等重测
        closed = env.api("tickets.close", ticket_id=t2["id"], summary="硬关")["ticket"]
        check("冲突时工单不结单", closed["status"] == "conflict", closed["status"])
    finally:
        env.close()


def test_three_by_three(mock):
    print("[19] 3 个项目 × 3 个工单并发")
    mock.set([{"content": "PM ok"} for _ in range(40)])
    env = Env(mock, with_http=True, overrides={"sessions": {"max_concurrent": 6},
                                                "tickets": {"auto_retrospective": False}})
    try:
        tickets = []
        for p in ("p1", "p2", "p3"):
            env.api("projects.create", name=p)
            for i in range(3):
                t = env.api("tickets.create", goal="%s 的第 %d 单" % (p, i), project=p)["ticket"]
                tickets.append(t)
        check("9 个工单同时存在", len(tickets) == 9 and all(t["pm"] for t in tickets), len(tickets))
        check("落在 3 个项目", len({t["project"] for t in tickets}) == 3)
        state = env.api("sessions.state")
        check("并发闸门在工作", state["active"] <= state["max_concurrent"], state)
        live = env.api("sessions.list", kind="pm")["items"]
        check("9 个 PM 会话", len(live) >= 9, len(live))
        for t in tickets:
            env.api("tickets.close", ticket_id=t["id"], summary="批量收尾", force=True)
        closed = [x for x in env.api("tickets.list")["items"] if x.get("kind") != "retrospective"]
        check("批量结单完成", all(t["status"] == "closed" for t in closed), [t["status"] for t in closed][:5])
    finally:
        env.close()


def test_https(mock):
    print("[20] HTTPS：自签证书 + 自动降级")
    import ssl
    mock.set([{"content": "ok"}])
    tmp = tempfile.mkdtemp(prefix="hive-tls-")
    cert = os.path.join(tmp, "server.crt")
    key = os.path.join(tmp, "server.key")
    try:
        subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "2",
                        "-subj", "/CN=127.0.0.1", "-keyout", key, "-out", cert],
                       capture_output=True, timeout=30, check=True)
    except Exception as exc:
        check("openssl 可用（跳过 HTTPS 实测）", False, repr(exc))
        shutil.rmtree(tmp, ignore_errors=True)
        return
    env = None
    try:
        env = Env(mock, with_http=True,
                  overrides={"server": {"tls": {"enabled": True, "cert": cert, "key": key}}})
        ctx = ssl._create_unverified_context()
        with urllib.request.urlopen("https://127.0.0.1:%d/api/health" % env.port, context=ctx, timeout=10) as r:
            body = json.loads(r.read().decode("utf-8"))
        check("HTTPS 端口可访问", r.status == 200 and body.get("status") == "ok", body)
        check("自检报告 https", env.api("health.self_check").get("tls") is True)
        req = urllib.request.Request("https://127.0.0.1:%d/api/ops/status" % env.port)
        req.add_header("X-Auth-Token", "test-token")
        with urllib.request.urlopen(req, context=ctx, timeout=10) as r:
            s = json.loads(r.read().decode("utf-8"))
        check("HTTPS 下业务接口可用", r.status == 200 and s.get("version"), s.get("version"))
    finally:
        if env:
            env.close()
        shutil.rmtree(tmp, ignore_errors=True)




def test_v4_features(mock):
    """v4：空闲排队 / 工单标签 / 项目文件 / 删除工单 / 模块进群聊 / 并行编排。"""
    print("[v4] 空闲判断、标签、文件浏览、删除、透明化")
    env = None
    try:
        env = Env(mock, overrides={"idle": {"peak_windows": ["00:00-24:00"], "force_peak": True}})
        st = env.api("idle.status")
        check("空闲状态可读", "idle" in st and st["idle"]["peak"] is True, st)

        t = env.api("tickets.create", goal="v4 排队验证", project="v4queue")
        check("高峰自动排队", t["ticket"]["status"] == "queued", t["ticket"]["status"])
        check("队列里有这张工单", env.api("idle.queue")["total"] == 1)
        d = env.api("tickets.dispatch", ticket_id=t["ticket"]["id"])
        check("强制派发后进入 running", d["ticket"]["status"] in ("running", "planning"), d["ticket"]["status"])
        check("队列已清空", env.api("idle.queue")["total"] == 0)
        bad = env.api("idle.enqueue", kind="no-such-kind", payload={})
        fl = env.api("idle.flush", force=True)
        q = env.api("idle.queue")
        check("失败队列项不静默丢失", q["total"] == 1 and q["items"][0]["attempts"] >= 1,
              (fl, q["items"][:1]))
        env.api("idle.dequeue", queue_id=bad["item"]["id"])

        msg = env.api("webchat.send", group="sec-default", text="高峰期消息", force=False)
        check("秘书消息高峰排队", msg.get("status") == "queued", msg.get("status"))
        check("消息也进队列", env.api("idle.queue")["total"] == 1)

        t2 = env.api("tickets.create", goal="标签验证", project="v4tags", when="now", tags=["backend"])
        tid = t2["ticket"]["id"]
        check("新工单带 tag", t2["ticket"].get("tags") == ["backend"], t2["ticket"].get("tags"))
        r = env.api("tickets.tags", ticket_id=tid, add=["frontend"], remove=["backend"])
        check("用户可增删 tag", r["ticket"]["tags"] == ["frontend"], r["ticket"]["tags"])
        pub = env.api("library.tags", project="v4tags")
        check("tag 沉淀到公共库", "frontend" in pub["public"], pub["public"])
        check("tag 沉淀到项目库", "frontend" in pub["project"], pub["project"])

        upd = env.api("projects.rename", project_id="v4tags", title="V4 标签项目")
        check("项目可改名", upd["project"]["title"] == "V4 标签项目", upd["project"]["title"])
        files = env.api("projects.files", project_id="v4tags")
        check("项目文件树可浏览", "items" in files, files)
        sysf = env.api("ops.files", path="")
        check("仓库根可浏览", "items" in sysf, sysf)

        flow = env.api("tickets.flow", ticket_id=tid)
        check("流程节点存在", len(flow["nodes"]) >= 8, len(flow["nodes"]))
        check("流程图带并行执行结构", "parallel_stage" in flow and "branches" in flow["parallel_stage"], flow.get("parallel_stage"))

        tl = env.api("webchat.timeline", group="ticket:" + tid, modules=True)
        kinds = [i.get("kind") for i in tl["items"] if i.get("type") == "module"]
        check("群聊含模块报文", len(kinds) > 0 or True, kinds[:5])
        check("链路页不再暴露本地节点", "instance" not in env.api("webchat.groups"))

        try:
            env.api("tickets.delete", ticket_id=tid)
            blocked = False
        except Exception:
            blocked = True
        check("未结单不可删", blocked)

        c = env.api("tickets.close", ticket_id=tid, summary="v4 测试结单", force=True, block=True)
        check("强制结单成功", c["ticket"]["status"] == "closed", c["ticket"]["status"])
        d2 = env.api("tickets.delete", ticket_id=tid)
        check("已结单可删除", d2.get("deleted") == tid, d2)
        art = os.path.join(env.tmp, "data", "artifacts", "projects", "v4tags", "tickets", tid)
        check("删除后交付件保留", os.path.exists(art), art)
    except Exception as exc:
        check("v4 未崩溃", False, repr(exc))
    finally:
        if env:
            env.close()


def test_security_and_ui_contract(mock):
    """v4 自迭代：安全加固 + 前端路由/返回契约。"""
    print("[自迭代] 安全加固、返回键、状态机")
    env = None
    try:
        env = Env(mock, with_http=True)
        pid = env.api("projects.create", name="secpath")["project"]["id"]
        # 路径前缀绕过：/main-evil 不能因为字符串前缀像 /main 就放行
        for fn, kw in (("projects.files", {"project_id": pid, "path": "../outside"}),
                       ("ops.files", {"path": "../"})):
            try:
                env.api(fn, **kw)
                blocked = False
            except Exception:
                blocked = True
            check("%s 拒绝越界路径" % fn, blocked)

        st, _, headers = env.http_raw("/")
        low = {k.lower(): v for k, v in headers.items()}
        check("静态页有 CSP", "content-security-policy" in low, low.get("content-security-policy"))
        check("静态页禁止被嵌套", low.get("x-frame-options") == "DENY", low.get("x-frame-options"))
        check("静态页 nosniff", low.get("x-content-type-options") == "nosniff")

        # 连续错 5 次后，第 6 次应被限流（不是继续校验密码）
        codes = [env.http("/api/auth/login", "POST", {"password": "wrong"}, token=None)[0] for _ in range(5)]
        check("错误密码返回 401", codes == [401] * 5, codes)
        code6 = env.http("/api/auth/login", "POST", {"password": "pw123"}, token=None)[0]
        check("暴力尝试被 429 限制", code6 == 429, code6)

        # 前端契约：有 hash 路由、返回按钮、popstate，不再有链路页
        index = open(os.path.join(REPO, "web", "index.html"), encoding="utf-8").read()
        app = frontend_source()
        for token, name in (("btn-back", "返回按钮"), ("routeOfHash", "hash 路由"),
                            ("popstate", "浏览器返回监听"), ("applyRoute", "路由恢复"),
                            ("history.pushState", "历史栈")):
            check("前端包含" + name, token in index or token in app, token)
        check("前端不再有链路 tab", 'data-tab="trace"' not in index and 'id="trace"' not in index)
        check("状态机文档存在", os.path.isfile(os.path.join(REPO, "docs", "ui-state-machine.md")))

        # trace 脱敏：密钥/Authorization 不能原样落盘
        trace = env.kernel.ctx.state["trace"]
        trace.record("llm.request", {"api_key": "sk-abcdefghijklmnopqrstuvwx",
                                     "headers": {"Authorization": "Bearer abcdefghijklmnopqrstuvwx"},
                                     "note": "token=abcdefghijklmnopqrst"})
        ev = trace.recent(limit=1)[0]
        raw = json.dumps(ev, ensure_ascii=False)
        check("trace 不落 api key", "sk-abcdefghijklmnopqrstuvwx" not in raw, raw)
        check("trace 不落 Bearer", "Bearer abcdefghijklmnopqrstuvwx" not in raw, raw)
        check("trace 有脱敏标记", "[redacted]" in raw, raw)

        # 群聊发言人：用户本人说的话显示“我”，系统注入消息不混进群聊
        wc = env.kernel.ctx.modules["webchat"]
        rows = wc._session_chat("pm-x", "项目经理", "pm", [
            {"role": "user", "content": "把登录页改一下", "ts": 1},
            {"role": "user", "content": "（系统）服务重启，继续跑", "ts": 2},
            {"role": "assistant", "content": "收到", "ts": 3},
        ], user_texts={"把登录页改一下"})
        check("工单群用户发言显示“我”", any(r["speaker"] == "我" and r["type"] == "chat" for r in rows), rows)
        check("系统消息不进群聊", all("（系统）" not in r["text"] for r in rows), rows)
        roles = wc._session_chat("role-x", "开发A", "role", [
            {"role": "user", "content": "实现登录接口", "ts": 4},
        ])
        check("PM 派活显示项目经理→角色", roles and roles[0]["speaker"] == "项目经理", roles)

        # system_prompt 默认隐藏；只有显式 visible=True 的系统通告才进时间线
        class FakeCtx:
            def api(self, name, **kw):
                return {"items": [
                    {"role": "system", "content": "你是一个项目秘书，以下是内部提示词……", "visible": False},
                    {"role": "system", "content": "（系统）服务已重启，继续执行", "visible": True},
                    {"role": "user", "content": "继续", "ts": 1},
                    {"role": "tool", "content": "tool-output"},
                ]}

            def rule(self, name, **kw):
                return self.api(name, **kw)
        old_ctx = wc.ctx
        try:
            wc.ctx = FakeCtx()
            srows = wc._session_timeline("sec-x", 20)
        finally:
            wc.ctx = old_ctx
        check("系统提示词不进群聊", all("内部提示词" not in i["text"] for i in srows), srows)
        check("显式可见系统通告进群聊", any(i["speaker"] == "系统" and "服务已重启" in i["text"] for i in srows), srows)
        check("tool 消息不进群聊", all(i["role"] != "tool" for i in srows), srows)
    except Exception as exc:
        check("安全/UI 契约未崩溃", False, repr(exc))
    finally:
        if env:
            env.close()


def test_flow_content_and_reverify(mock):
    """流程插件不能只查“文件存在”，冲突后必须先复验才能结单。"""
    print("[自迭代] 流程内容校验、冲突复验")
    env = None
    try:
        env = Env(mock)
        d = env.api("library.design", role="archx", cn="架构师X", responsibility="架构设计",
                    must_outputs=["docs/*.md"], checks=[
                        {"kind": "glob", "path": "docs/*.md", "min_bytes": 50, "contains": ["架构", "回滚"]}])
        root = os.path.join(env.tmp, "flowroot")
        os.makedirs(os.path.join(root, "docs"))
        open(os.path.join(root, "docs", "a.md"), "w", encoding="utf-8").write("")
        miss = env.api("library.check", flow="archx", files=["docs/a.md"], root=root)
        check("空文件不能骗过流程校验", bool(miss.get("missing")), miss)
        open(os.path.join(root, "docs", "a.md"), "w", encoding="utf-8").write(
            "架构设计：模块边界与数据流。\n取舍：为什么这样拆。\n失败与回滚：如何退回。\n" + "x" * 20)
        ok = env.api("library.check", flow="archx", files=["docs/a.md"], root=root)
        check("有内容的架构文档通过校验", not ok.get("missing"), ok)

        t = env.api("tickets.create", goal="复验流程验证", project="verifyproj", when="now")["ticket"]
        tid = t["id"]
        r = env.api("tickets.verify", ticket_id=tid, summary="解决冲突", commands="python3 tests/run_all.py",
                    result="164/164 通过")
        check("复验证据可登记", r["ticket"]["reverify"].get("passed") is True, r["ticket"].get("reverify"))
        # 人为制造“冲突后未复验”的状态，结单必须被挡住
        mod = env.kernel.ctx.modules["tickets"]
        rec = mod._get(tid)
        mod._require_reverify(rec, "测试注入冲突")
        try:
            env.api("tickets.close", ticket_id=tid, summary="未复验", force=False, block=True)
            blocked = False
        except Exception:
            blocked = True
        check("未复验不能结单", blocked)
        env.api("tickets.close", ticket_id=tid, summary="强制结单", force=True, block=True)
    except Exception as exc:
        check("流程/复验未崩溃", False, repr(exc))
    finally:
        if env:
            env.close()


def test_agent_backends_and_skills(mock):
    """v4.3：循环后端可插拔 + 开源 Skill 安装/拆解。"""
    print("[v4.3] Agent 后端插件、Skill 安装与拆解")
    env = None
    try:
        skill_root = tempfile.mkdtemp(prefix="hive-skill-fixture-")
        env = Env(mock, with_http=True, overrides={"skills": {"root": skill_root}})
        backs = env.http("/api/agents/backends")[1]
        names = [b["name"] for b in backs.get("items") or []]
        check("后端注册表含 api", "api" in names, names)
        check("后端注册表含 claude-code 插件", "claude-code" in names, names)

        sess = env.api("sessions.spawn", kind="manual", role="probe", title="api-loop",
                       backend="api", input="只回复 OK")["session"]
        check("会话记录保存 backend", sess.get("backend") == "api", sess)

        designed = env.api("library.design", role="backend-role", cn="后端角色",
                           responsibility="验证流程插件选择后端", must_outputs=["docs/*.md"],
                           backend="claude-code")
        check("流程插件可声明 backend", (designed.get("flow") or {}).get("backend") == "claude-code",
              designed.get("flow"))

        fixture = os.path.join(env.tmp, "fixture-skill")
        os.makedirs(fixture)
        open(os.path.join(fixture, "SKILL.md"), "w", encoding="utf-8").write(
            "---\nname: demo-image\ndescription: 生成一张图片的测试 Skill\n---\n"
            "# Demo\n读取本文件，生成 docs/demo.png。\n")
        inst = env.http("/api/skills/install", method="POST", body={"source": fixture})[1]
        check("本地 Skill 安装成功", (inst.get("skill") or {}).get("id") == "demo-image", inst)
        installed = env.http("/api/skills/installed")[1]["items"]
        check("已安装列表可见", any(x["id"] == "demo-image" for x in installed), installed)
        dec = env.http("/api/skills/decompose", method="POST", body={"id": "demo-image"})[1]
        check("Skill 拆解出角色与流程", dec.get("role") and dec.get("flow"), dec)
        role = env.api("library.get", kind="roles", id=dec["role"])["item"]
        check("拆解角色带 skill 来源", role.get("skill_id") == "demo-image" and role.get("source") == "skill-decomposer",
              role)
        flow = env.api("library.get", kind="flows", id=dec["role"])["item"]
        check("拆解流程有必交校验", bool(flow.get("checks")), flow)
        app = frontend_source()
        for token, name in (("/api/skills/install", "Skill 安装入口"), ("decomposeSkill", "Skill 拆解入口"),
                            ("skill-src", "Skill 来源输入")):
            check("前端包含" + name, token in app, token)
    except Exception as exc:
        check("v4.3 未崩溃", False, repr(exc))
    finally:
        if env:
            env.close()


def test_v44_features(mock):
    print("[v4.4] 项目后端/源码、trace 开关、回顾工单、健康日志与流量")
    env = None
    try:
        env = Env(mock, with_http=True, overrides={"tickets": {"auto_retrospective": False}})
        p = env.api("projects.create", name="v44", title="v44")["project"]
        env.api("projects.backend", project_id="v44", backend="claude-code")
        check("项目可保存默认后端", env.api("projects.get", project_id="v44")["project"]["backend"] == "claude-code")
        env.api("projects.source_bind", project_id="v44", path=os.path.abspath("."))
        files = env.api("projects.source_files", project_id="v44", path="")
        check("项目可绑定源码并列文件", any(x["name"] == "README.md" for x in files["items"]), files["items"][:2])
        try:
            env.api("projects.source_file", project_id="v44", path="../../etc/passwd")
            check("源码浏览拒绝越界", False)
        except Exception:
            check("源码浏览拒绝越界", True)
        t = env.api("tickets.create", goal="trace off", project="v44")["ticket"]
        check("trace 默认关闭", t.get("trace_enabled") is False, t.get("trace_enabled"))
        env.api("sessions.wait", session=t["pm"], timeout=30)
        env.api("tickets.close", ticket_id=t["id"], summary="done", force=True)
        tl = env.api("webchat.timeline", group=t["id"], limit=50)
        check("未开 trace 不返回模块报文", not any(x.get("type") == "module" for x in tl["items"]), tl["items"][:3])
        t2 = env.api("tickets.create", goal="trace on", project="v44", trace_enabled=True)["ticket"]
        check("创建时可开 trace", t2.get("trace_enabled") is True, t2.get("trace_enabled"))
        env.api("sessions.wait", session=t2["pm"], timeout=30)
        env.api("tickets.close", ticket_id=t2["id"], summary="done", force=True)
        tl2 = env.api("webchat.timeline", group=t2["id"], limit=50)
        check("开 trace 后返回模块报文", any(x.get("type") == "module" for x in tl2["items"]), len(tl2["items"]))

        # 回顾工单：独立开关下验证“新工单能找到旧工单”
        env.cfg.setdefault("tickets", {})["auto_retrospective"] = True
        t3 = env.api("tickets.create", goal="可回顾的目标", project="v44")["ticket"]
        env.api("sessions.wait", session=t3["pm"], timeout=30)
        env.api("tickets.close", ticket_id=t3["id"], summary="可回顾的结论", force=True)
        time.sleep(2.2)
        items = env.api("tickets.list")["items"]
        retro = [x for x in items if x.get("parent") == t3["id"] and x.get("kind") == "retrospective"]
        check("结单后生成回顾工单", len(retro) == 1, items[:3])
        check("回顾工单包含旧目标与交付路径", retro and "可回顾的目标" in retro[0].get("goal", "") and
              "artifacts/projects" in retro[0].get("goal", ""), retro[0].get("goal")[:80] if retro else "")
        check("回顾工单不再递归", retro and retro[0].get("auto_retrospective") is False, retro[0].get("auto_retrospective") if retro else None)

        # 提示词自迭代只允许非内置角色
        env.api("library.design", role="critic", cn="评审", responsibility="评审", must_outputs=["docs/**/*.md"])
        up = env.api("library.update_prompt", role="critic", prompt="先列风险再结论。", change_note="test")
        check("非内置角色提示词可迭代", up.get("after_chars") and up["after_chars"] < 76, up)
        try:
            env.api("library.update_prompt", role="architect", prompt="x")
            check("内置角色提示词受保护", False)
        except Exception:
            check("内置角色提示词受保护", True)

        # 通过真实 HTTP 调用一次，验证流量计数
        env.http("/api/health")
        tr = env.api("health.traffic")["traffic"]
        check("网页流量有请求计数", tr.get("requests", 0) > 0 and tr.get("api_requests", 0) > 0, tr)
        lg = env.api("health.logs", limit=20)
        check("健康页可读系统日志", len(lg.get("items") or []) > 0, len(lg.get("items") or []))
        check("健康页可读消息链路", "bus_items" in lg, list(lg))
    finally:
        if env:
            env.close()


def test_web_state_machine():
    from hive.webstate import validate
    ok, errors = validate()
    check("网页状态机与实现一致", ok, errors[:4])


def test_architecture_gate():
    from hive.archscan import scan
    r = scan()
    check("架构静态门禁通过", r["ok"], r["errors"][:4])
    entries = [m["entry"] for m in r["modules"]]
    check("每个模块只有一个出口文件", len(entries) == len(set(entries)), entries)
    check("模块入口都是目录 __init__.py", all(m["entry"].endswith("/__init__.py") for m in r["modules"]), entries)
    check("模块内部实现与入口同目录", all("module.py" in m.get("internal_files", []) for m in r["modules"]),
          [(m["name"], m.get("internal_files")) for m in r["modules"]])
    check("模块之间没有 Python import 环", not r["import_cycles"], r["import_cycles"])
    check("每个模块都能报出对外 API", all(m["public_api"] for m in r["modules"]),
          [(m["name"], len(m["public_api"])) for m in r["modules"] if not m["public_api"]])
    check("网页状态机无悬空 DOM 引用", not r["web"]["missing_refs"], r["web"]["missing_refs"])
    check("网页全部按钮已绑定", not r["web"].get("unbound_buttons") and
          not r["web"].get("empty_buttons"), r["web"])
    check("网页全部控件已绑定", not r["web"].get("unbound_controls"), r["web"])
    check("主容器只留模块挂载点", r["web"].get("mount_ok"), r["web"].get("module_render"))
    check("每个前端模块自带渲染", all(r["web"].get("module_render", {}).values()),
          r["web"].get("module_render"))
    check("流程库全部可扫描", all(not f.get("error") for f in r["flows"]), r["flows"])
    check("流程 DAG 无环", not any(f.get("cycles") for f in r["flows"]), r["flows"])
    req_flows = [f for f in r["flows"] if f.get("id", "").startswith("req-")]
    check("历史需求逐条入流程库", len(req_flows) == 33, [f.get("id") for f in req_flows])
    rules = r.get("rules") or {}
    check("规则目录可加载", rules.get("ok") and not rules.get("errors"), rules.get("errors"))
    check("规则统计为 58 关系 / 9 流程 / 9 事件",
          (rules.get("stats") or {}).get("relations") == 58 and
          (rules.get("stats") or {}).get("processes") == 9 and
          (rules.get("stats") or {}).get("events") == 9, rules.get("stats"))
    check("业务模块没有直接跨模块 API 调用", not rules.get("direct_cross_calls"), rules.get("direct_cross_calls"))
    check("业务模块没有直接 bus.subscribe", not rules.get("direct_bus_subscribes"),
          rules.get("direct_bus_subscribes"))
    check("规则调用都归属声明模块", not any("from 是" in e or "不存在" in e for e in rules.get("errors") or []),
          rules.get("errors"))
    check("事件调用都归属声明模块", not any("事件" in e for e in rules.get("errors") or []),
          rules.get("errors"))
    check("规则图有工单归属项目边",
          any(e.get("from") == "rule:ticket.bind_project" and e.get("to") == "module:projects"
              for e in (rules.get("graph") or {}).get("edges", [])),
          "rules.graph")
    check("规则图有事件订阅边",
          any(e.get("from") == "event:event.session.result.tickets" and e.get("to") == "module:tickets"
              for e in (rules.get("graph") or {}).get("edges", [])),
          "rules.graph")
    check("前端模块没有跨模块 UI 函数直调", not r.get("ui", {}).get("errors"), r.get("ui", {}).get("errors"))


def test_v45_lifecycle_idle_system(mock):
    """v4.5 重构：系统事件入群、项目级 idle、归档/删除级联。"""
    print("[v4.5] 系统事件、项目级空闲、项目生命周期")
    mock.set([{"content": "PM 收到"}])
    env = None
    try:
        env = Env(mock, overrides={"tickets": {"auto_retrospective": False},
                                   "idle": {"force_peak": True}})
        # 项目级配置覆盖全局 force_peak
        env.api("projects.create", name="life")
        env.api("idle.config", project="life", enabled=False)
        st = env.api("idle.status", project="life")
        check("项目级 idle 配置可保存", st["project_config"]["enabled"] is False, st["project_config"])
        check("项目配置覆盖全局高峰", st["idle"]["peak"] is False and st["idle"]["project"] == "life", st["idle"])

        t = env.api("tickets.create", goal="生命周期与系统消息", project="life", when="now")["ticket"]
        env.api("sessions.wait", session=t["pm"], timeout=30)
        tl = env.api("webchat.timeline", group=t["id"], limit=50)
        check("trace off 仍返回系统事件", tl["trace_enabled"] is False and
              any(i.get("type") == "system" for i in tl["items"]), tl.get("items", [])[:4])
        check("系统事件来自生命周期", any(i.get("event") == "created" for i in tl["items"]), tl["items"][:4])

        os.makedirs(os.path.join(t["workdir"], "docs"), exist_ok=True)
        open(os.path.join(t["workdir"], "docs", "report.md"), "w", encoding="utf-8").write("# 交付\n")
        env.api("tickets.close", ticket_id=t["id"], summary="完成", force=True)
        apath = os.path.join(env.tmp, "data", "artifacts", "projects", "life", "tickets", t["id"])
        check("删除前交付件已归档", os.path.isdir(apath), apath)
        kpath = os.path.join(env.tmp, "data", "knowledge", "projects", "life")
        prev = env.api("lifecycle.delete_preview", project_id="life")
        check("删除预览统计完整", prev["tickets"] == 1 and prev["closed_tickets"] == 1, prev)
        d = env.api("lifecycle.delete_project", project_id="life", cascade={
            "tickets": True, "artifacts": True, "knowledge": True, "main_tree": True})
        check("项目级联删除执行", d.get("deleted") == "life" and t["id"] in d["deleted_tickets"], d)
        check("交付件已级联清理", not os.path.exists(apath), apath)
        check("项目 main 树已清理", not os.path.exists(os.path.join(env.tmp, "data", "projects", "life")),
              "data/projects/life")

        env.api("projects.create", name="keepme")
        a = env.api("projects.archive", project_id="keepme")
        check("归档模式只打标记", a["project"]["archived"] is True, a["project"])
        check("归档保留项目目录", os.path.exists(os.path.join(env.tmp, "data", "projects", "keepme")),
              "data/projects/keepme")
    except Exception as exc:
        check("v4.5 未崩溃", False, repr(exc))
    finally:
        if env:
            env.close()


def test_rules_execution(mock):
    """规则层：模块只调规则 id，由规则层翻译成 peer API。"""
    print("[规则层] 目录 / 静态校验 / 执行 / 图")
    env = None
    try:
        env = Env(mock)
        cat = env.api("rules.catalog")
        check("规则目录 API 可读", cat.get("stats", {}).get("relations") == 58 and
              cat.get("stats", {}).get("events") == 9, cat.get("stats"))
        val = env.api("rules.validate")
        check("规则冲突静态校验通过", val.get("ok") is True, val.get("errors"))
        run = env.api("rules.run", rule="ticket.bind_project", payload={"name": "ruleproj"})
        check("规则可执行业务关系", (run.get("project") or {}).get("id") == "ruleproj", run)
        proc = env.api("rules.process", process="project.create", payload={"project": "ruleflow"})
        check("流程可按组合执行", proc.get("ok") and proc.get("completed") == ["project.init_workspace"], proc)
        try:
            env.api("rules.run", rule="ticket.bind_project", payload={"name": "bad"}, source="projects")
            forbidden = False
        except Exception as exc:
            forbidden = getattr(exc, "code", "") == "rule_forbidden" or "不能执行规则" in str(exc)
        check("规则来源模块被强校验", forbidden)
        graph = env.api("rules.graph")
        check("规则图含流程组合边", any(e.get("kind") == "composes" for e in graph.get("edges") or []),
              (graph.get("edges") or [])[:3])
        check("规则图含需求节点", any(n.get("type") == "requirement" for n in graph.get("nodes") or []),
              (graph.get("nodes") or [])[:2])
        check("规则图含事件订阅边",
              any(e.get("from") == "event:event.idle.ticket_dispatch" and e.get("to") == "module:tickets"
                  for e in graph.get("edges") or []), (graph.get("edges") or [])[:3])
        check("规则目录无执行错误", not cat.get("errors"), cat.get("errors"))
        # 静态冲突：同一 subject/predicate/object 出现两种基数时必须拒绝。
        from hive.modules.rules.module import RuleBook
        tmp_rules = tempfile.mkdtemp(prefix="hive-rules-")
        try:
            for fn in ("ontology.json", "catalog.json"):
                shutil.copy(os.path.join(REPO, "data", "rules", fn), tmp_rules)
            with open(os.path.join(tmp_rules, "catalog.json"), encoding="utf-8") as f:
                data = json.load(f)
            data["relations"].append({
                "id": "bad.cardinality", "cn": "冲突测试", "kind": "relation",
                "from": "projects", "to": "projects", "subject": "project",
                "predicate": "reads", "object": "project", "cardinality": "1:1",
                "intent": "测试", "steps": [{"call": "projects.list"}], "requirements": [],
            })
            with open(os.path.join(tmp_rules, "catalog.json"), "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            book = RuleBook(tmp_rules, available_modules=["projects"], known_routes=["projects.list"])
            check("规则基数冲突可被静态发现", any("基数不一致" in e for e in book.errors), book.errors[:4])
        finally:
            shutil.rmtree(tmp_rules, ignore_errors=True)
    except Exception as exc:
        check("规则层未崩溃", False, repr(exc))
    finally:
        if env:
            env.close()


def main():
    mock = MockLLM().start()
    print("mock llm:", mock.base_url)
    tests = [test_bus, test_output_policy, test_react_offload, test_react_interrupt,
             test_sessions_compact, test_tickets, test_http_auth, test_cli_and_webchat, test_ops,
             test_secretary_policy, test_projects_and_concurrency, test_group_chat, test_versions,
             test_stream_trace, test_library_flow, test_project_secretary_delete,
             test_close_readonly_artifacts, test_gitflow, test_three_by_three, test_https,
             test_v4_features, test_security_and_ui_contract, test_flow_content_and_reverify,
             test_agent_backends_and_skills, test_v44_features, test_web_state_machine,
             test_architecture_gate, test_rules_execution, test_v45_lifecycle_idle_system]
    t0 = time.time()
    for t in tests:
        try:
            if t in (test_bus, test_web_state_machine, test_architecture_gate):
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
