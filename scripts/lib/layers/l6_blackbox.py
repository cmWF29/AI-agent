"""L6 HTTP 黑盒业务 E2E（ST）：真服务、真 RPC、真并发，不走进程内装配。

两段口径：
- 转调 ``scripts/verify_api_e2e.py``（26 个场景），把逐场景 OK/FAIL 翻成层内检查项；
- 真网络故障演练：本层自己起一台会翻脸的上游（500 → 正常 SSE），另引导一份
  ``stub_net=False`` 的装配，让它经真实 socket 打这台上游，验证「上游炸了不挂死、
  不伪造回复；上游恢复后同一服务自动可用；上游直接断连也只降级不假成功」。

覆盖口径（写死端口、跑在默认 8787 之外的装配里都是 bug，本层端口一律取引导结果）：
项目改名与工单引用改挂、知识库版本冲突/追加作用域、定时器增改删/到点建单/守卫、
节点申领与错 token 释放、12 路并发建删、拆单上限、多岗位并发不串扰、结单级联只读与
会话回收、鉴权关闭/拒绝、越权与路径穿越、坏 YAML/405/404/ETag 304 的壳层协议、
上游 5xx 与断连的真网络降级。
"""
from __future__ import annotations

import os
import re
import socketserver
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler
from pathlib import Path

from report import LayerResult, Timer

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "assert"))
from recorder import Recorder  # noqa: E402

from layers import _bootstrap  # noqa: E402

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "scripts" / "verify_api_e2e.py"
_LINE = re.compile(r"^  (OK|FAIL)\s+([^\s]+)")

sys.path.insert(0, str(ROOT / "scripts"))
from perf_http import Client  # noqa: E402


class _Upstream:
    """会翻脸的真上游：fail=True 回 500，fail=False 回一段 OpenAI 形状的 SSE。"""

    def __init__(self) -> None:
        self.fail = True
        self.hits = 0
        outer = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *args):  # noqa: D401 —— 免得每次故障演练刷屏
                return

            def do_POST(self):  # noqa: N802 —— BaseHTTPRequestHandler 约定
                outer.hits += 1
                self.rfile.read(int(self.headers.get("Content-Length") or 0))
                if outer.fail:
                    body = b'{"error":{"message":"upstream boom","code":"server_error"}}'
                    self.send_response(500)
                    self.send_header("Content-Type", "application/json")
                else:
                    body = ('data: {"choices":[{"delta":{"content":"（真上游）已完成"},'
                            '"finish_reason":"stop"}]}\n\ndata: [DONE]\n\n').encode("utf-8")
                    self.send_response(200)
                    self.send_header("Content-Type", "text/event-stream")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        self.server = socketserver.ThreadingTCPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def stop(self) -> None:
        try:
            self.server.shutdown()
        except Exception:  # noqa: BLE001 —— 关停失败不该污染结论
            pass


def _closed_port() -> int:
    """拿一个刚释放的本机端口：连上去必然拒绝，用来演「上游断连」。"""
    import socket

    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return port


def _rpc(port: int, demand: str, payload=None):
    client = Client("http://127.0.0.1:%d" % port, "t")
    try:
        sample, data = client.rpc(demand, payload or {})
        if not sample.ok:
            raise AssertionError("%s 失败: %s" % (demand, sample.code))
        outer = (data or {}).get("result") or {}
        if not isinstance(outer, dict) or outer.get("ok") is False:
            raise AssertionError("%s 失败: %s" % (demand, outer))
        value = outer.get("result")
        return value if isinstance(value, dict) else {}
    finally:
        client.close()


def _wait(port: int, tid: str, limit: float = 30.0):
    """等工单回到 idle：故障演练只认「有限时间内收口」，不接受一直 running。"""
    started = time.time()
    thread = {}
    while time.time() - started < limit:
        thread = _rpc(port, "ticket-thread", {"id": tid}).get("thread") or {}
        if thread.get("status") == "idle":
            return thread, time.time() - started
        time.sleep(0.5)
    return None, time.time() - started


def _assistant(thread: dict) -> list[str]:
    return [str(m.get("content") or "") for m in (thread.get("messages") or [])
            if m.get("role") == "assistant" and str(m.get("content") or "").strip()]


def _upstream_5xx_checks(rec: Recorder) -> list[str]:
    """真网络三段：上游 500 降级不挂死 → 恢复后同一服务可用 → 上游断连不假成功。"""
    out = []
    upstream = _Upstream()
    boot = None
    try:
        boot = _bootstrap.boot(
            overrides={"llm": {"base_url": "http://127.0.0.1:%d/v1" % upstream.port}},
            stub_net=False)
        port = boot.port
        pid = _rpc(port, "projects-create", {"name": "l6-upstream-%d" % time.time_ns()})["id"]
        try:
            tid = _rpc(port, "ticket-create", {"project": pid, "title": "上游 5xx 演练",
                                               "goal": "验证上游故障降级"})["id"]
            _rpc(port, "ticket-message", {"id": tid, "text": "在吗"})
            thread, cost = _wait(port, tid)
            replies = _assistant(thread or {})
            out.append("  上游 500：真实请求 %d 次，%.1fs 内回到 idle，assistant 回复 %d 条"
                       % (upstream.hits, cost, len(replies)))
            rec.check("上游 5xx 时降级不挂死", thread is not None and upstream.hits >= 1,
                      "hits=%d idle=%s cost=%.1fs" % (upstream.hits, thread is not None, cost))
            # 5xx 下绝不能拿桩文案冒充成功回复
            rec.check("上游 5xx 时不伪造回复", not replies,
                      "assistant=%r" % [r[:40] for r in replies])

            upstream.fail = False
            _rpc(port, "ticket-message", {"id": tid, "text": "再试一次"})
            thread2, cost2 = _wait(port, tid)
            replies2 = [r for r in _assistant(thread2 or {}) if r not in replies]
            out.append("  上游恢复：%.1fs 内收到真回复 %r" % (cost2, [r[:20] for r in replies2]))
            rec.check("上游恢复后同一服务自动可用", bool(replies2),
                      "新增 assistant=%r cost=%.1fs" % ([r[:40] for r in replies2], cost2))
        finally:
            try:
                _rpc(port, "projects-delete", {"id": pid, "purge": True})
            except Exception:  # noqa: BLE001 —— 清理失败不留假绿
                rec.check("上游演练项目清理", False, "projects-delete 失败: %s" % pid)
    except Exception as exc:  # noqa: BLE001 —— 层失败要留原因，不吞异常
        rec.check("上游 5xx 真网络演练", False, repr(exc))
    finally:
        if boot is not None:
            boot.cleanup()
        upstream.stop()

    # 断连：端口上没有任何监听，连接直接拒绝，只许降级、不许假成功、不许挂死
    boot2 = None
    try:
        boot2 = _bootstrap.boot(
            overrides={"llm": {"base_url": "http://127.0.0.1:%d/v1" % _closed_port()}},
            stub_net=False)
        port = boot2.port
        pid = _rpc(port, "projects-create", {"name": "l6-drop-%d" % time.time_ns()})["id"]
        try:
            tid = _rpc(port, "ticket-create", {"project": pid, "title": "上游断连演练",
                                               "goal": "验证断连降级"})["id"]
            _rpc(port, "ticket-message", {"id": tid, "text": "在吗"})
            thread, cost = _wait(port, tid)
            replies = _assistant(thread or {})
            out.append("  上游断连：%.1fs 内回到 idle，assistant 回复 %d 条" % (cost, len(replies)))
            rec.check("上游断连时降级不挂死", thread is not None,
                      "idle=%s cost=%.1fs" % (thread is not None, cost))
            rec.check("上游断连时不伪造回复", not replies,
                      "assistant=%r" % [r[:40] for r in replies])
        finally:
            try:
                _rpc(port, "projects-delete", {"id": pid, "purge": True})
            except Exception:  # noqa: BLE001
                rec.check("断连演练项目清理", False, "projects-delete 失败: %s" % pid)
    except Exception as exc:  # noqa: BLE001
        rec.check("上游断连真网络演练", False, repr(exc))
    finally:
        if boot2 is not None:
            boot2.cleanup()
    return out


def run(timeout: float = 300.0) -> LayerResult:
    rec = Recorder()
    output = []
    boot = None
    with Timer() as t:
        try:
            # 定时器场景要自己走后台扫描：把 tick 间隔压到 1s，并允许 6s 后的 once。
            boot = _bootstrap.boot(overrides={"timer": {"tick_interval_s": 1,
                                                        "min_interval_s": 0}})
            env = os.environ.copy()
            env["HIVE_TOKEN"] = "t"
            proc = subprocess.run(
                [sys.executable, str(SCRIPT), "--scenario", "all",
                 "--base", "http://127.0.0.1:%d" % boot.port, "--token", "t"],
                cwd=str(ROOT), env=env, capture_output=True, text=True,
                timeout=max(60.0, timeout))
            text = (proc.stdout or "") + (proc.stderr or "")
            output.append(text)
            seen = 0
            tail = {}
            for line in (proc.stdout or "").splitlines():
                m = _LINE.match(line)
                if not m:
                    continue
                seen += 1
                status, name = m.group(1), m.group(2)
                rec.check("黑盒 %s" % name, status == "OK", line.strip()[:600])
                if status == "FAIL":
                    tail[name] = line
            if seen == 0:
                rec.check("黑盒场景产出", False, text[-1200:])
            if proc.returncode != 0 and not tail:
                rec.check("黑盒脚本退出码", False, text[-1200:])
        except Exception as exc:  # noqa: BLE001 —— 层失败要留原因，不吞异常
            rec.check("HTTP 黑盒业务 E2E", False, repr(exc))
        finally:
            if boot is not None:
                boot.cleanup()
        try:
            output.extend(_upstream_5xx_checks(rec))
        except Exception as exc:  # noqa: BLE001 —— 演练整体崩了也要留证据
            rec.check("真网络降级演练", False, repr(exc))
    return LayerResult(
        layer="L6", title="HTTP 黑盒业务 E2E（真服务 + 真 RPC + 真并发）",
        ok=rec.ok, duration=t.elapsed, checks=rec.checks, output="\n".join(output),
        note="26 场景：项目/工单/知识/定时到点建单/节点/并发/多岗位串扰/权限/交付件/壳层边界，"
             "外加真网络上游 5xx 与断连两段降级演练。",
    )
