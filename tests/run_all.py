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


def main():
    mock = MockLLM().start()
    print("mock llm:", mock.base_url)
    tests = [test_bus, test_output_policy, test_react_offload, test_react_interrupt,
             test_sessions_compact, test_tickets, test_http_auth, test_cli_and_webchat, test_ops]
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
