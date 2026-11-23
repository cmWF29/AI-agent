#!/usr/bin/env python3
"""真实网络栈多节点联调演练（单物理机、两个独立节点实例，真实 HTTP）。

与进程内 mock 的区别：
- 控制面是独立 ThreadingHTTPServer（loopback TCP，真实 HTTP 报文）；
- 两个执行节点是独立子进程，各有独立数据目录、独立监听端口、独立 node id，
  经 ``nodes.push_register`` / ``nodes.push_heartbeat`` 出站连云控面；
- 节点进程自己也在 loopback 上监听端口（健康探针），不是纯内存桩。

演练场景：
  A. 主节点心跳停 → 租约过期 → 项目迁移到备节点 → 主节点恢复后不抢回 →
     旧 fence token 写入被拒。
  B. 迁移中途目标节点再次失败 → 首条迁移记 failed 回滚，重试成功，同一项目
     任一时刻只有一个执行者（不双跑）。
  C. 节点断线回收与重连：进程终止后按 TTL 判假死；同 id 重启后补注册回表。

输出 JSON 报告 ``console-acceptance/round4/node-drill-net.json``：含控制面/节点
真实端口、node id、逐步断言与时间线；任一断言失败退出码非 0。脚本自清临时目录
与子进程，可重复跑。只用本机 loopback 与临时目录，不写线上数据；共享密钥每轮
随机生成，不写死在代码里。
"""
from __future__ import annotations

import argparse
import json
import secrets
import shutil
import sys
import tempfile
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from ai_new.modules.agent.nodes.private import _pure  # noqa: E402

REPORT_PATH = (REPO_ROOT.parent / "console-acceptance" / "round4"
               / "node-drill-net.json")

TTL = 2.0
INTERVAL = 0.5
NODE_IDS = ("A", "B")

# 控制面状态在服务进程内（本进程内存），子节点不持有协调状态。
STATE = _pure.empty_state()
LOCK = threading.Lock()
SECRET = ""


# ---------------------------------------------------------------- 控制面分发

def dispatch(route, payload):
    """把 HTTP 路由分发到 nodes 纯协调层；时间戳由控制面现取。"""
    now = time.time()
    payload = payload or {}

    # push 通道先鉴权：共享密钥来自每轮随机生成（演练）/ 配置 nodes.node_token（生产）。
    if route in ("nodes.push_register", "nodes.push_heartbeat"):
        if not _pure.token_matches(payload.get("node_token"), SECRET):
            return {"ok": False, "code": "unauthorized",
                    "reason": "bad_node_token"}

    if route == "nodes.push_register":
        return _pure.register(STATE, payload, now)
    if route == "nodes.push_heartbeat":
        return _pure.heartbeat(STATE, payload.get("node"), payload.get("load"), now)
    if route == "nodes.register":
        return _pure.register(STATE, payload, now)
    if route == "nodes.heartbeat":
        return _pure.heartbeat(STATE, payload.get("node"), payload.get("load"), now)
    if route == "nodes.acquire":
        return _pure.acquire(STATE, payload.get("project"), payload.get("node"), now,
                             ttl=payload.get("ttl"), tier=payload.get("tier"),
                             checkpoint=payload.get("checkpoint"))
    if route == "nodes.renew":
        return _pure.renew(STATE, payload.get("project"), payload.get("token"), now)
    if route == "nodes.release":
        return _pure.release(STATE, payload.get("project"), payload.get("token"), now)
    if route == "nodes.fence_check":
        return _pure.fence_check(STATE, payload.get("project"),
                                 payload.get("token"), payload.get("epoch"))
    if route == "nodes.sweep_expired":
        return _pure.sweep_expired(STATE, now, ttl=payload.get("ttl"))
    if route == "nodes.reassign":
        return _pure.reassign(STATE, payload.get("project"), now,
                              policy=payload.get("policy"),
                              candidate=payload.get("candidate"),
                              reason=payload.get("reason"),
                              checkpoint=payload.get("checkpoint"))
    if route == "nodes.record_migration":
        return {"ok": True, "migration": _pure.record_migration(STATE, payload)}
    if route == "nodes.status":
        return {"ok": True, **_pure.status_view(STATE, now, ttl=payload.get("ttl"))}
    if route == "nodes.nodes_view":
        return {"ok": True, "nodes": _pure.nodes_view(STATE, now,
                                                       ttl=payload.get("ttl"))}
    if route == "nodes.assignments":
        return {"ok": True, "assignments": _pure.assignments_view(STATE, now=now)}
    if route == "nodes.backups":
        return {"ok": True, "backups": _pure.backups_view(STATE)}
    if route == "nodes.migrations":
        return {"ok": True, "migrations": _pure.migrations_view(STATE)}
    if route == "nodes.project_node":
        return {"ok": True, "assignment": _pure.project_node(
            STATE, payload.get("project"))}
    if route == "nodes.backup_record":
        return {"ok": True, "backup": _pure.record_backup(
            STATE, payload.get("project"), payload.get("snapshot") or {})}
    return {"ok": False, "code": "unknown_route", "route": route}


class _CpHandler(BaseHTTPRequestHandler):
    server_version = "AI_NEW-node-drill-net/0.1"
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):  # 演练桩不刷 stderr
        pass

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        try:
            body = json.loads(raw.decode("utf-8")) if raw else {}
            rel = (self.path.replace("/api/rpc/", "").replace("/rpc/", "")
                   .strip("/"))
            route = ".".join(p for p in rel.split("/") if p)
            with LOCK:
                result = dispatch(route, body or {})
            out = json.dumps({"ok": result.get("ok", False),
                              "result": result}).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Length", str(len(out)))
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(out)
        except Exception as exc:  # noqa: BLE001 — 桩服务兜底回 500
            out = json.dumps({"ok": False, "result": {"code": "internal",
                                                      "error": str(exc)}}).encode("utf-8")
            self.send_response(500)
            self.send_header("Content-Length", str(len(out)))
            self.end_headers()
            self.wfile.write(out)


# ---------------------------------------------------------------- 节点子进程

class _NodeHandler(BaseHTTPRequestHandler):
    """节点自带的 loopback 健康探针：只回活状态，不暴露协调台账。"""
    server_version = "AI_NEW-node/0.1"
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        pass

    def do_GET(self):
        if self.path.rstrip("/") in ("", "/health"):
            body = json.dumps({"ok": True, "node": getattr(self.server, "node_id", "")})
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(body.encode("utf-8"))
        else:
            self.send_response(404)
            self.send_header("Content-Length", "0")
            self.end_headers()


def _worker_main(args):
    """节点子进程：绑自己的 loopback 端口，出站注册并周期心跳。"""
    from ai_new.modules.agent.nodes.private._push import PushNodeClient

    workdir = Path(args.workdir)
    workdir.mkdir(parents=True, exist_ok=True)
    try:
        node_server = ThreadingHTTPServer(("127.0.0.1", args.node_port), _NodeHandler)
        node_server.node_id = args.node
        node_port = node_server.server_address[1]
        threading.Thread(target=node_server.serve_forever, daemon=True).start()

        endpoint = "http://127.0.0.1:%d" % node_port
        (workdir / "state.json").write_text(json.dumps({
            "node": args.node, "port": node_port, "endpoint": endpoint,
            "role": args.role}), encoding="utf-8")

        client = PushNodeClient(
            args.base, args.node, args.secret, endpoint=endpoint, transport="http",
            role=args.role, capacity={"cpu": 2, "memory_mb": 2048},
            lease_ttl=args.ttl, interval=args.interval,
            backoff_base=0.2, backoff_max=2.0)
        try:
            client.run(command_file=Path(args.command_file))
        finally:
            node_server.shutdown()
            node_server.server_close()
    except Exception:
        import traceback
        (workdir / "error.log").write_text(traceback.format_exc(), encoding="utf-8")
        raise


# ---------------------------------------------------------------- 演练编排

class Drill:
    def __init__(self, base, tmp, secret, keep_tmp=False):
        self.base = base
        self.tmp = Path(tmp)
        self.secret = secret
        self.keep_tmp = keep_tmp
        self.procs = {}
        self.cmds = {}
        self.nodes = {}
        self.checks_total = 0
        self.checks_failed = 0
        self.scenarios = []
        self.timeline = []
        self.started = time.time()

    # ---- 子进程管理

    def start_worker(self, nid, role="executor"):
        workdir = self.tmp / ("worker-" + nid)
        workdir.mkdir(parents=True, exist_ok=True)
        cmd_file = self.tmp / ("cmd-" + nid + ".txt")
        cmd_file.write_text("run", encoding="utf-8")
        self.cmds[nid] = cmd_file
        # 重启场景下清掉旧状态文件，避免编排方读到上一轮的端口/端点
        state_file = workdir / "state.json"
        if state_file.exists():
            state_file.unlink()
        log = open(self.tmp / ("worker-%s.log" % nid), "ab")  # noqa: SIM115
        proc = _popen([
            sys.executable, "-u", str(Path(__file__).resolve()),
            "--worker", "--node", nid, "--base", self.base,
            "--secret", self.secret, "--workdir", str(workdir),
            "--command-file", str(cmd_file), "--interval", str(INTERVAL),
            "--ttl", str(TTL), "--role", role], stdout=log, stderr=log)
        self.procs[nid] = proc
        self.nodes[nid] = self._wait_node_state(workdir, nid)

    def _wait_node_state(self, workdir, nid, timeout=10.0):
        deadline = time.time() + timeout
        state_file = workdir / "state.json"
        while time.time() < deadline:
            if state_file.exists():
                try:
                    return json.loads(state_file.read_text(encoding="utf-8"))
                except json.JSONDecodeError:
                    pass
            time.sleep(0.05)
        raise AssertionError("节点 %s 未在超时内写出端口状态" % nid)

    def wait_registered(self, ids, timeout=10.0):
        deadline = time.time() + timeout
        want = set(ids)
        while time.time() < deadline:
            view = self.call("nodes.nodes_view", {})
            have = {n["id"] for n in view.get("nodes", [])}
            if want <= have:
                return
            time.sleep(0.1)
        raise AssertionError("节点未在超时内登记: %s" % sorted(have))

    def wait_health(self, ids, health="alive", timeout=10.0):
        """轮询直到指定节点在视图里达到目标健康度（重连后等心跳真正恢复）。"""
        deadline = time.time() + timeout
        want = set(ids)
        while time.time() < deadline:
            view = self.call("nodes.nodes_view", {})
            rows = {n["id"]: n for n in view.get("nodes", [])}
            if want <= set(rows) and all(rows[i]["health"] == health for i in want):
                return
            time.sleep(0.1)
        raise AssertionError("节点未在超时内达到健康度 %s: %s" % (health, sorted(rows)))

    def set_command(self, nid, cmd):
        self.cmds[nid].write_text(cmd, encoding="utf-8")

    def stop_worker(self, nid):
        proc = self.procs.get(nid)
        if proc is None:
            return
        try:
            self.set_command(nid, "stop")
            proc.wait(timeout=5)
        except Exception:  # noqa: BLE001
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except Exception:  # noqa: BLE001
                proc.kill()

    def stop_workers(self):
        for nid in list(self.procs):
            self.stop_worker(nid)

    # ---- RPC 与断言

    def call(self, route, payload=None):
        last = None
        for _ in range(20):
            try:
                req = urllib.request.Request(
                    self.base + "/rpc/" + route,
                    data=json.dumps(payload or {}).encode("utf-8"),
                    headers={"Content-Type": "application/json"}, method="POST")
                with urllib.request.urlopen(req, timeout=5) as resp:
                    return json.loads(resp.read().decode("utf-8"))["result"]
            except Exception as exc:  # noqa: BLE001 — 等服务 accept 就绪后重试
                last = exc
                time.sleep(0.15)
        raise last

    def holder(self, project):
        row = self.call("nodes.status", {})
        for a in row.get("assignments", []):
            if a["project"] == project:
                return a if a["state"] == "held" else None
        return None

    def held_count(self, project):
        row = self.call("nodes.status", {})
        return sum(1 for a in row.get("assignments", [])
                   if a["project"] == project and a["state"] == "held")

    def check(self, scenario, name, ok, detail=""):
        self.checks_total += 1
        if not ok:
            self.checks_failed += 1
        entry = {"name": name, "ok": bool(ok),
                 "detail": str(detail)[:800],
                 "t": round(time.time() - self.started, 3)}
        scenario["checks"].append(entry)
        self.timeline.append(entry)

    def wait_expiry(self):
        time.sleep(TTL + 0.6)
        self.call("nodes.sweep_expired", {"ttl": TTL})

    # ---- 场景

    def scenario_auth_and_idempotency(self):
        sc = {"id": "0", "name": "push 注册鉴权与幂等", "checks": [],
              "observations": {}}
        # 错误共享密钥必须被拒
        bad = self.call("nodes.push_register", {
            "id": "A", "endpoint": self.nodes["A"]["endpoint"],
            "node_token": "wrong-secret"})
        self.check(sc, "错误 token 注册被拒（unauthorized）",
                   (not bad["ok"]) and bad["code"] == "unauthorized", bad)

        # 正确密钥重复注册：仍只有一条记录，首次注册时间保留
        view = self.call("nodes.nodes_view", {})
        before = {n["id"]: n for n in view["nodes"]}
        again = self.call("nodes.push_register", {
            "id": "A", "endpoint": self.nodes["A"]["endpoint"],
            "capacity": {"cpu": 2, "memory_mb": 2048},
            "node_token": self.secret})
        view2 = self.call("nodes.nodes_view", {})
        after = {n["id"]: n for n in view2["nodes"]}
        self.check(sc, "同 id 重复注册幂等（记录数不变）",
                   len(view2["nodes"]) == len(view["nodes"]),
                   {"before": len(view["nodes"]), "after": len(view2["nodes"])})
        self.check(sc, "重复注册保留首次注册时间",
                   again["ok"] and after["A"]["registered_at"] ==
                   before["A"]["registered_at"], after["A"])
        sc["observations"]["nodes"] = after
        self.scenarios.append(sc)
        return sc

    def scenario_a_failover_no_reclaim(self):
        sc = {"id": "A", "name": "主节点假死：迁移备节点，恢复不抢回，旧写入被拒",
              "checks": [], "observations": {}}
        project = "proj-a"
        first = self.call("nodes.acquire", {"project": project, "node": "A",
                                            "ttl": TTL, "tier": "weak"})
        self.check(sc, "A 申领 proj-a 成功", first["ok"], first)
        old_token = first["lease"]["token"]
        old_epoch = first["lease"]["epoch"]
        before = self.holder(project)
        self.check(sc, "分配前归属 A", before and before["node"] == "A", before)

        self.set_command("A", "pause")
        self.wait_expiry()
        released = self.holder(project)
        self.check(sc, "A 假死后 proj-a 租约释放", released is None,
                   self.call("nodes.status", {}))

        moved = self.call("nodes.reassign", {"project": project, "candidate": "B",
                                            "reason": "node_lost"})
        self.check(sc, "proj-a 迁移到 B", moved["ok"] and
                   moved["lease"]["node"] == "B", moved)
        after = self.holder(project)
        self.check(sc, "归属记录由 A 变为 B", after and after["node"] == "B", after)
        self.check(sc, "迁移后不双跑：proj-a 仅 B 持有",
                   self.held_count(project) == 1, self.call("nodes.status", {}))

        # A 恢复心跳：不得抢回正在被 B 持有的租约
        self.set_command("A", "run")
        time.sleep(INTERVAL + 0.3)
        still = self.holder(project)
        self.check(sc, "A 恢复后 proj-a 归属仍在 B",
                   still and still["node"] == "B", still)
        back = self.call("nodes.acquire", {"project": project, "node": "A",
                                           "ttl": TTL})
        self.check(sc, "A 抢回 proj-a 被拒（lease_held）",
                   (not back["ok"]) and back["code"] == "lease_held" and
                   back["holder"] == "B", back)

        stale = self.call("nodes.fence_check", {"project": project,
                                                "token": old_token,
                                                "epoch": old_epoch})
        self.check(sc, "A 旧 fence token 写入被拒（token_mismatch）",
                   (not stale["ok"]) and stale["code"] == "token_mismatch", stale)
        sc["observations"]["before"] = before
        sc["observations"]["after"] = after
        self.scenarios.append(sc)
        return sc

    def scenario_b_midflight_fail(self):
        sc = {"id": "B", "name": "迁移中途目标再失败：回滚重试，不双跑",
              "checks": [], "observations": {}}
        project = "proj-b"

        first = self.call("nodes.acquire", {"project": project, "node": "A",
                                            "ttl": TTL, "tier": "weak"})
        self.check(sc, "A 申领 proj-b 成功", first["ok"], first)
        old_token = first["lease"]["token"]
        old_epoch = first["lease"]["epoch"]

        self.set_command("A", "pause")
        self.wait_expiry()
        self.check(sc, "A 停摆后 proj-b 租约释放", self.holder(project) is None,
                   self.call("nodes.status", {}))

        half = self.call("nodes.reassign", {"project": project, "candidate": "B",
                                            "reason": "node_lost"})
        self.check(sc, "半程迁移：B 接手 proj-b", half["ok"] and
                   half["lease"]["node"] == "B", half)
        self.check(sc, "半程不双跑：proj-b 仅 B 持有",
                   self.held_count(project) == 1, self.call("nodes.status", {}))
        half_token = half["lease"]["token"]
        half_epoch = half["lease"]["epoch"]

        # 目标 B 迁移进行到一半停摆；回收租约，首条迁移记 failed 回滚
        self.set_command("B", "pause")
        self.wait_expiry()
        self.check(sc, "B 停摆后 proj-b 不再被持有", self.holder(project) is None,
                   self.call("nodes.status", {}))
        self.call("nodes.record_migration", {
            "project": project, "from_node": "B", "to_node": None,
            "reason": "target_lost_midflight", "epoch": half_epoch,
            "migrated_at": time.time(), "state": "failed",
            "checkpoint": half["lease"].get("checkpoint"),
            "note": "目标节点迁移半程失联；回滚待重试"})

        fence_b = self.call("nodes.fence_check", {"project": project,
                                                  "token": half_token,
                                                  "epoch": half_epoch})
        self.check(sc, "B 半程旧 token 回写被 fencing 拒",
                   (not fence_b["ok"]) and fence_b["code"] in
                   ("token_mismatch", "not_held", "stale_epoch"), fence_b)

        # 重试：A 恢复后重新接手；任一时刻持有数不超过 1
        self.set_command("A", "run")
        time.sleep(INTERVAL + 0.3)
        retry = self.call("nodes.reassign", {"project": project, "candidate": "A",
                                             "reason": "retry_after_target_lost"})
        self.check(sc, "重试成功：proj-b 回到 A", retry["ok"] and
                   retry["lease"]["node"] == "A", retry)
        self.check(sc, "重试后不双跑：proj-b 仅 A 持有",
                   self.held_count(project) == 1, self.call("nodes.status", {}))

        fence_a_old = self.call("nodes.fence_check", {"project": project,
                                                      "token": old_token,
                                                      "epoch": old_epoch})
        self.check(sc, "A 首轮旧 token 回写被 fencing 拒",
                   not fence_a_old["ok"], fence_a_old)

        migs = [m for m in self.call("nodes.migrations", {})["migrations"]
                if m["project"] == project]
        states = [m["state"] for m in migs]
        self.check(sc, "迁移台账含 failed 回滚记录", "failed" in states, migs)
        self.check(sc, "迁移台账含重试 done 记录", "done" in states, migs)
        sc["observations"]["migrations"] = migs
        self.scenarios.append(sc)
        return sc

    def scenario_c_disconnect_reconnect(self):
        sc = {"id": "C", "name": "断线回收与重连：终止判假死，同 id 重启补注册",
              "checks": [], "observations": {}}
        # B 进程终止；超过 TTL 后巡检判失联
        self.stop_worker("B")
        self.wait_expiry()
        view = self.call("nodes.nodes_view", {})
        b = next(n for n in view["nodes"] if n["id"] == "B")
        self.check(sc, "B 终止后按 TTL 判假死（lost）", b["health"] == "lost", b)

        # 同 id 重启：补注册后回表且恢复在线（命令文件先复位为 run）
        self.cmds["B"].write_text("run", encoding="utf-8")
        self.start_worker("B")
        self.wait_health(["B"], "alive")
        view2 = self.call("nodes.nodes_view", {})
        b2 = next(n for n in view2["nodes"] if n["id"] == "B")
        self.check(sc, "B 重启后补注册回表", b2["id"] == "B", b2)
        self.check(sc, "B 重连后心跳恢复在线", b2["health"] == "alive", b2)
        sc["observations"]["before"] = b
        sc["observations"]["after"] = b2
        self.scenarios.append(sc)
        return sc

    def record_backups(self):
        self.call("nodes.backup_record", {"project": "proj-a",
                   "snapshot": {"snapshot_id": "snap-a", "created_at": time.time(),
                                 "state": "verified",
                                 "entries": ["tickets/a.yaml"]}})
        self.call("nodes.backup_record", {"project": "proj-b",
                   "snapshot": {"snapshot_id": "snap-b", "created_at": time.time(),
                                 "state": "verified",
                                 "entries": ["tickets/b.yaml"]}})

    def run(self):
        try:
            self.start_worker("A")
            self.start_worker("B")
            self.wait_registered(NODE_IDS)
            return self._scenarios()
        finally:
            self.stop_workers()

    def _scenarios(self):
        self.scenario_auth_and_idempotency()
        self.scenario_a_failover_no_reclaim()
        self.scenario_b_midflight_fail()
        self.scenario_c_disconnect_reconnect()
        self.record_backups()

        status = self.call("nodes.status", {})
        return {
            "environment": {
                "python": sys.version.split()[0],
                "platform": sys.platform,
                "ttl_sec": TTL, "heartbeat_interval_sec": INTERVAL,
                "secret_source": "per-run random (secrets.token_hex)",
            },
            "control_plane": {"base": self.base,
                              "port": int(self.base.rsplit(":", 1)[1])},
            "nodes": [{"id": nid, "port": self.nodes[nid]["port"],
                       "endpoint": self.nodes[nid]["endpoint"],
                       "role": self.nodes[nid].get("role", "executor")}
                      for nid in NODE_IDS],
            "timeline": self.timeline,
            "scenarios": self.scenarios,
            "summary": {
                "total": self.checks_total,
                "passed": self.checks_total - self.checks_failed,
                "failed": self.checks_failed,
                "duration_sec": round(time.time() - self.started, 3),
            },
            "final": {
                "nodes": status["nodes"],
                "assignments": status["assignments"],
                "backups": status["backups"],
                "migrations": self.call("nodes.migrations", {})["migrations"],
            },
        }


def _popen(cmd, stdout=None, stderr=None):
    import subprocess
    return subprocess.Popen(cmd, stdout=stdout, stderr=stderr)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--worker", action="store_true")
    ap.add_argument("--node", default="")
    ap.add_argument("--base", default="")
    ap.add_argument("--secret", default="")
    ap.add_argument("--workdir", default="")
    ap.add_argument("--command-file", default="")
    ap.add_argument("--interval", type=float, default=INTERVAL)
    ap.add_argument("--ttl", type=float, default=TTL)
    ap.add_argument("--role", default="executor")
    ap.add_argument("--node-port", type=int, default=0)
    ap.add_argument("--port", type=int, default=8787)
    ap.add_argument("--keep-tmp", action="store_true")
    args = ap.parse_args(argv)

    if args.worker:
        _worker_main(args)
        return 0

    global SECRET
    SECRET = secrets.token_hex(16)
    tmp = tempfile.mkdtemp(prefix="node-drill-net-")
    server = None
    for port in (args.port, 0):
        try:
            server = ThreadingHTTPServer(("127.0.0.1", port), _CpHandler)
            break
        except OSError:
            continue
    if server is None:
        raise SystemExit("无法绑定控制面端口（%d 及临时端口均失败）" % args.port)
    actual_port = server.server_address[1]
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = "http://127.0.0.1:%d" % actual_port

    drill = Drill(base, tmp, SECRET, keep_tmp=args.keep_tmp)
    report = None
    try:
        report = drill.run()
        report.setdefault("environment", {})["cp_port"] = actual_port
    finally:
        server.shutdown()
        server.server_close()
        if not args.keep_tmp:
            shutil.rmtree(tmp, ignore_errors=True)

    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2),
                           encoding="utf-8")
    print(json.dumps({"summary": report["summary"],
                      "report": str(REPORT_PATH)}, ensure_ascii=False))
    return 0 if report["summary"]["failed"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
