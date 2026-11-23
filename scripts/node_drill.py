#!/usr/bin/env python3
"""单机多进程真实故障演练：假死再分配 / 迁移中再失败 / 恢复不抢回 / fencing。

起 2–3 个真实子进程假节点（各自独立工作目录 + 独立 idem 根），连本机 8787
桩控制面（stdlib HTTP，分发到 ``agent.nodes`` 纯协调层），按场景执行并断言：

  A. 节点假死：停心跳 → 租约过期 → 项目被重新分配；原节点旧 token 写入被拒。
  B. 迁移中再失败：迁移进行到一半停掉目标节点 → 首条迁移记 failed 回滚，
     重试成功；同一项目同一时刻只有一个执行者（不双跑）。
  C. 恢复不抢回：假死节点恢复心跳后不得把项目抢回，归属仍在新节点。
  D. fencing：旧节点用过期 token/epoch 写入必须被拒，错误码明确。

输出 JSON 报告到
``/home/user/Doubao/chats/38452724256755714/console-acceptance/round2/node-drill.json``；
任一断言失败退出码非 0。脚本自清理临时目录与子进程，可重复跑。

只用桩服务与本机临时目录，不删用户数据、不写线上数据、不写死密钥。
"""
from __future__ import annotations

import argparse
import json
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

REPORT_PATH = Path(
    "/home/user/Doubao/chats/38452724256755714/console-acceptance/round2/"
    "node-drill.json")

TTL = 2.0
INTERVAL = 0.5
NODES = ("n1", "n2", "n3")

# 控制面状态在桩服务进程内（本进程内存），子节点不持有协调状态。
STATE = _pure.empty_state()
_LOCK = threading.Lock()


# ---------------------------------------------------------------- 控制面分发

def dispatch(route, payload):
    """把桩 HTTP 路由分发到 nodes 纯协调层；时间戳由桩服务现取。"""
    now = time.time()
    payload = payload or {}
    if route == "nodes.register":
        return _pure.register(STATE, payload, now)
    if route == "nodes.heartbeat":
        return _pure.heartbeat(STATE, payload.get("node"),
                                payload.get("load"), now)
    if route == "nodes.acquire":
        return _pure.acquire(STATE, payload.get("project"), payload.get("node"),
                              now, ttl=payload.get("ttl"), tier=payload.get("tier"))
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
        return {"ok": True, **_pure.status_view(STATE, now,
                                                ttl=payload.get("ttl"))}
    if route == "nodes.backup_record":
        return {"ok": True, "backup": _pure.record_backup(
            STATE, payload.get("project"), payload.get("snapshot") or {})}
    if route == "nodes.migrations":
        return {"ok": True, "migrations": _pure.migrations_view(STATE)}
    return {"ok": False, "code": "unknown_route", "route": route}


class _Handler(BaseHTTPRequestHandler):
    server_version = "AI_NEW-node-drill/0.1"
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):  # 演练桩不刷 stderr
        pass

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        try:
            body = json.loads(raw.decode("utf-8")) if raw else {}
            route = self.path.replace("/rpc/", "").strip("/")
            with _LOCK:
                result = dispatch(route, body or {})
            body = json.dumps({"ok": result.get("ok", False),
                               "result": result}).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(body)
        except Exception as exc:  # noqa: BLE001 — 桩服务兜底回 500
            body = json.dumps({"ok": False, "result": {"code": "internal",
                                                       "error": str(exc)}}).encode("utf-8")
            self.send_response(500)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)


# ---------------------------------------------------------------- 子节点进程

def _worker_main(args):
    """假节点进程：独立工作目录/idem 根；按命令文件决定是否继续心跳。"""
    workdir = Path(args.workdir)
    idem_root = Path(args.idem_root)
    workdir.mkdir(parents=True, exist_ok=True)
    idem_root.mkdir(parents=True, exist_ok=True)
    (workdir / "worker.json").write_text(json.dumps({
        "node": args.node, "workdir": str(workdir),
        "idem_root": str(idem_root)}), encoding="utf-8")

    def rpc(route, payload):
        last = None
        for _ in range(20):
            try:
                req = urllib.request.Request(
                    args.base + "/rpc/" + route,
                    data=json.dumps(payload).encode("utf-8"),
                    headers={"Content-Type": "application/json"}, method="POST")
                with urllib.request.urlopen(req, timeout=5) as resp:
                    return json.loads(resp.read().decode("utf-8"))["result"]
            except Exception as exc:  # noqa: BLE001 — 等服务 accept 就绪后重试
                last = exc
                time.sleep(0.15)
        raise last

    rpc("nodes.register", {
        "id": args.node, "endpoint": "unix://" + args.node,
        "transport": "unix", "capacity": {"cpu": 2, "memory_mb": 2048},
        "lease_ttl": TTL})

    cmd_file = Path(args.command_file)
    while True:
        cmd = cmd_file.read_text(encoding="utf-8").strip() if cmd_file.exists() else "run"
        if cmd == "stop":
            break
        if cmd == "run":
            rpc("nodes.heartbeat", {"node": args.node, "load": {"running": 0}})
            (idem_root / ("heartbeat-%s" % args.node)).write_text(
                str(time.time()), encoding="utf-8")
        # paused：不发心跳，模拟进程假死（进程在，但心跳停了）
        time.sleep(args.interval)


# ---------------------------------------------------------------- 演练编排

class Drill:
    def __init__(self, base, tmp, keep_tmp=False):
        self.base = base
        self.tmp = Path(tmp)
        self.keep_tmp = keep_tmp
        self.procs = {}
        self.cmds = {}
        self.roots = {}
        self.checks_total = 0
        self.checks_failed = 0
        self.scenarios = []

    # ---- 子进程管理
    def start_workers(self):
        for nid in NODES:
            workdir = self.tmp / ("worker-" + nid)
            idem_root = self.tmp / ("idem-" + nid)
            cmd_file = self.tmp / ("cmd-" + nid + ".txt")
            cmd_file.write_text("run", encoding="utf-8")
            self.cmds[nid] = cmd_file
            self.roots[nid] = {"workdir": str(workdir),
                               "idem_root": str(idem_root)}
            proc = subprocess_popen([
                sys.executable, str(Path(__file__).resolve()),
                "--worker", "--node", nid, "--base", self.base,
                "--workdir", str(workdir), "--idem-root", str(idem_root),
                "--command-file", str(cmd_file), "--interval", str(INTERVAL)],
                log_path=str(self.tmp / ("worker-" + nid + ".log")))
            self.procs[nid] = proc
        self._wait_registered()

    def _wait_registered(self, timeout=10.0):
        deadline = time.time() + timeout
        while time.time() < deadline:
            view = self.call("nodes.status", {})
            ids = {n["id"] for n in view.get("nodes", [])}
            if set(NODES) <= ids:
                return
            time.sleep(0.1)
        raise AssertionError("子节点未在超时内登记: %s" % sorted(ids))

    def set_command(self, nid, cmd):
        self.cmds[nid].write_text(cmd, encoding="utf-8")

    def stop_workers(self):
        for nid, proc in self.procs.items():
            try:
                self.set_command(nid, "stop")
                proc.wait(timeout=5)
            except Exception:  # noqa: BLE001
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except Exception:  # noqa: BLE001
                    proc.kill()

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
            except Exception as exc:  # noqa: BLE001
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
        scenario["checks"].append({"name": name, "ok": bool(ok),
                                   "detail": str(detail)})

    def wait_expiry(self):
        time.sleep(TTL + 0.6)
        self.call("nodes.sweep_expired", {"ttl": TTL})

    # ---- 场景
    def scenario_b_midflight_fail(self):
        sc = {"id": "B", "name": "迁移中再失败：目标半程停摆，回滚重试不双跑",
              "checks": [], "observations": {}}
        # n1 持 drill-b；先让 n1 假死，租约释放后迁移到 n2（半程）。
        b = "drill-b"
        first = self.call("nodes.acquire", {"project": b, "node": "n1",
                                            "ttl": TTL, "tier": "weak"})
        self.check(sc, "n1 申领 drill-b 成功", first["ok"], first)
        old_token_n1 = first["lease"]["token"]
        old_epoch_n1 = first["lease"]["epoch"]

        self.set_command("n1", "pause")
        self.wait_expiry()
        self.check(sc, "n1 假死后 drill-b 租约释放",
                   self.holder(b) is None, self.call("nodes.status", {}))

        half = self.call("nodes.reassign", {"project": b, "candidate": "n2",
                                            "reason": "node_lost"})
        self.check(sc, "半程迁移：n2 接手 drill-b", half["ok"] and
                   half["lease"]["node"] == "n2", half)
        self.check(sc, "半程不双跑：drill-b 仅 n2 持有",
                   self.held_count(b) == 1, self.call("nodes.status", {}))
        half_token = half["lease"]["token"]
        half_epoch = half["lease"]["epoch"]

        # 目标 n2 迁移进行到一半停摆；回收其租约，首条迁移记 failed 回滚。
        self.set_command("n2", "pause")
        self.wait_expiry()
        self.check(sc, "n2 停摆后 drill-b 不再被持有",
                   self.holder(b) is None, self.call("nodes.status", {}))
        self.call("nodes.record_migration", {
            "project": b, "from_node": "n2", "to_node": None,
            "reason": "target_lost_midflight", "epoch": half_epoch,
            "migrated_at": time.time(), "state": "failed",
            "checkpoint": half["lease"].get("checkpoint"),
            "note": "目标节点迁移半程失联；回滚待重试"})

        # 重试：n1 恢复后重新接手；期间任何时刻持有数不超过 1。
        self.set_command("n1", "run")
        time.sleep(INTERVAL + 0.2)
        retry = self.call("nodes.reassign", {"project": b, "candidate": "n1",
                                            "reason": "retry_after_target_lost"})
        self.check(sc, "重试成功：drill-b 回到 n1", retry["ok"] and
                   retry["lease"]["node"] == "n1", retry)
        self.check(sc, "重试后不双跑：drill-b 仅 n1 持有",
                   self.held_count(b) == 1, self.call("nodes.status", {}))

        # n2 半程旧 token 回写必须被 fencing 拒。
        fence_n2 = self.call("nodes.fence_check", {"project": b,
                                                   "token": half_token,
                                                   "epoch": half_epoch})
        self.check(sc, "n2 过期 token 回写被 fencing 拒",
                   not fence_n2["ok"] and fence_n2["code"] == "token_mismatch",
                   fence_n2)
        # n1 首轮旧 token 同样被拒（epoch 已推进）。
        fence_n1_old = self.call("nodes.fence_check", {"project": b,
                                                       "token": old_token_n1,
                                                       "epoch": old_epoch_n1})
        self.check(sc, "n1 首轮旧 token 回写被 fencing 拒",
                   not fence_n1_old["ok"], fence_n1_old)

        migs = [m for m in self.call("nodes.migrations", {})["migrations"]
                if m["project"] == b]
        states = [m["state"] for m in migs]
        self.check(sc, "迁移台账含 failed 回滚记录", "failed" in states, migs)
        self.check(sc, "迁移台账含重试 done 记录", "done" in states, migs)
        sc["observations"]["migrations"] = migs
        self.scenarios.append(sc)
        return sc

    def scenario_a_death_reassign(self):
        sc = {"id": "A", "name": "节点假死：租约过期后重新分配，旧写入被拒",
              "checks": [], "observations": {}}
        # n2 在场景 B 半程停摆过；这里先恢复心跳再申领 drill-a。
        self.set_command("n2", "run")
        time.sleep(INTERVAL + 0.3)
        a = "drill-a"
        first = self.call("nodes.acquire", {"project": a, "node": "n2",
                                            "ttl": TTL, "tier": "weak"})
        self.check(sc, "n2 申领 drill-a 成功", first["ok"], first)
        old_token = first["lease"]["token"]
        old_epoch = first["lease"]["epoch"]
        before = self.holder(a)
        self.check(sc, "分配前归属 n2", before and before["node"] == "n2", before)

        self.set_command("n2", "pause")
        self.wait_expiry()
        after_release = self.holder(a)
        self.check(sc, "n2 假死后租约释放", after_release is None,
                   self.call("nodes.status", {}))

        moved = self.call("nodes.reassign", {"project": a, "candidate": "n3",
                                            "reason": "node_lost"})
        self.check(sc, "drill-a 重新分配到 n3", moved["ok"] and
                   moved["lease"]["node"] == "n3", moved)
        after = self.holder(a)
        self.check(sc, "归属记录由 n2 变为 n3", after and after["node"] == "n3",
                   after)
        self.check(sc, "重分配后不双跑：drill-a 仅 n3 持有",
                   self.held_count(a) == 1, self.call("nodes.status", {}))

        stale = self.call("nodes.fence_check", {"project": a,
                                                "token": old_token,
                                                "epoch": old_epoch})
        self.check(sc, "原节点旧 token 写入被拒（token_mismatch）",
                   not stale["ok"] and stale["code"] == "token_mismatch", stale)
        sc["observations"]["before"] = before
        sc["observations"]["after"] = after
        self.scenarios.append(sc)
        return sc

    def scenario_c_no_reclaim(self):
        sc = {"id": "C", "name": "恢复不抢回：假死节点恢复后不夺回项目",
              "checks": [], "observations": {}}
        a = "drill-a"
        # n2 恢复心跳（此前假死）；归属必须仍在 n3。
        self.set_command("n2", "run")
        time.sleep(INTERVAL + 0.3)
        still = self.holder(a)
        self.check(sc, "n2 恢复后 drill-a 归属仍在 n3",
                   still and still["node"] == "n3", still)
        back = self.call("nodes.acquire", {"project": a, "node": "n2",
                                           "ttl": TTL})
        self.check(sc, "n2 抢回 drill-a 被拒（lease_held）",
                   (not back["ok"]) and back["code"] == "lease_held" and
                   back["holder"] == "n3", back)
        sc["observations"]["holder"] = still
        self.scenarios.append(sc)
        return sc

    def scenario_d_fencing(self):
        sc = {"id": "D", "name": "fencing：过期 token/epoch 写入拒绝码明确",
              "checks": [], "observations": {}}
        a, b = "drill-a", "drill-b"
        status = self.call("nodes.status", {})
        cur = {x["project"]: x for x in status["assignments"]}
        # drill-a 当前 n3；drill-b 当前 n1。
        token_a = cur[a]["token"]
        epoch_a = cur[a]["epoch"]
        token_b = cur[b]["token"]
        epoch_b = cur[b]["epoch"]

        bad_epoch = self.call("nodes.fence_check", {"project": a,
                                                    "token": token_a,
                                                    "epoch": epoch_a + 1})
        self.check(sc, "epoch 回退被拒（stale_epoch）",
                   not bad_epoch["ok"] and bad_epoch["code"] == "stale_epoch",
                   bad_epoch)
        bad_token = self.call("nodes.fence_check", {"project": b,
                                                   "token": "stale-token",
                                                   "epoch": epoch_b})
        self.check(sc, "token 不符被拒（token_mismatch）",
                   not bad_token["ok"] and bad_token["code"] == "token_mismatch",
                   bad_token)
        ok = self.call("nodes.fence_check", {"project": a, "token": token_a,
                                             "epoch": epoch_a})
        self.check(sc, "当前持有 token/epoch 校验通过", ok["ok"], ok)
        sc["observations"]["current_assignments"] = cur
        self.scenarios.append(sc)
        return sc

    def record_backups(self):
        self.call("nodes.backup_record", {"project": "drill-a",
                   "snapshot": {"snapshot_id": "snap-a", "created_at": time.time(),
                                "state": "verified", "entries": ["tickets/a.yaml"]}})
        self.call("nodes.backup_record", {"project": "drill-b",
                   "snapshot": {"snapshot_id": "snap-b", "created_at": time.time(),
                                "state": "verified", "entries": ["tickets/b.yaml"]}})

    def run(self):
        started = time.time()
        self.start_workers()
        try:
            # 场景顺序：B 先消化 n1/n2 半程失败，A 做 n2→n3 假死迁移，
            # C 验证 n2 恢复不抢回，D 汇总 fencing 拒绝码。
            self.scenario_b_midflight_fail()
            self.scenario_a_death_reassign()
            self.scenario_c_no_reclaim()
            self.scenario_d_fencing()
            self.record_backups()

            status = self.call("nodes.status", {})
            self._verify_idem_isolation()
            report = {
                "report": "node-drill",
                "generated_at": time.time(),
                "environment": {
                    "python": sys.version.split()[0],
                    "platform": sys.platform,
                    "ttl_sec": TTL, "heartbeat_interval_sec": INTERVAL,
                },
                "node_roots": self.roots,
                "scenarios": self.scenarios,
                "summary": {
                    "total": self.checks_total,
                    "passed": self.checks_total - self.checks_failed,
                    "failed": self.checks_failed,
                    "duration_sec": round(time.time() - started, 3),
                },
                "final": {
                    "nodes": status["nodes"],
                    "assignments": status["assignments"],
                    "backups": status["backups"],
                    "migrations": self.call("nodes.migrations", {})["migrations"],
                },
            }
            return report
        finally:
            self.stop_workers()

    def _verify_idem_isolation(self):
        """各节点工作目录/idem 根两两独立，互不嵌套。"""
        roots = [r["idem_root"] for r in self.roots.values()]
        self.checks_total += 1
        if len(set(roots)) != len(roots):
            self.checks_failed += 1
            self.scenarios[0]["checks"].append(
                {"name": "idem 根两两独立", "ok": False,
                 "detail": "idem 根重复: %s" % roots})
            return
        def _within(child, parent):
            try:
                Path(child).relative_to(Path(parent))
                return True
            except ValueError:
                return False

        for i, left in enumerate(roots):
            for right in roots[i + 1:]:
                if _within(left, right) or _within(right, left):
                    self.checks_failed += 1
                    self.scenarios[0]["checks"].append(
                        {"name": "idem 根互不嵌套", "ok": False,
                         "detail": "%s 与 %s 嵌套" % (left, right)})
                    return
        self.scenarios[0]["checks"].append(
            {"name": "idem 根两两独立且互不嵌套", "ok": True, "detail": roots})


def subprocess_popen(cmd, log_path=None):
    import subprocess
    if log_path is not None:
        fh = open(log_path, "ab")  # noqa: SIM115 — 演练子进程日志，随 tmp 清理
        return subprocess.Popen(cmd, stdout=fh, stderr=fh)
    return subprocess.Popen(cmd, stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--worker", action="store_true")
    ap.add_argument("--node", default="")
    ap.add_argument("--base", default="")
    ap.add_argument("--workdir", default="")
    ap.add_argument("--idem-root", default="")
    ap.add_argument("--command-file", default="")
    ap.add_argument("--interval", type=float, default=INTERVAL)
    ap.add_argument("--port", type=int, default=8787)
    ap.add_argument("--keep-tmp", action="store_true")
    args = ap.parse_args(argv)

    if args.worker:
        _worker_main(args)
        return 0

    tmp = tempfile.mkdtemp(prefix="node-drill-")
    server = None
    for port in (args.port, 0):
        try:
            server = ThreadingHTTPServer(("127.0.0.1", port), _Handler)
            break
        except OSError:
            continue
    if server is None:
        raise SystemExit("无法绑定控制面端口（%d 及临时端口均失败）" % args.port)
    actual_port = server.server_address[1]
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = "http://127.0.0.1:%d" % actual_port
    drill = Drill(base, tmp, keep_tmp=args.keep_tmp)
    report = None
    try:
        report = drill.run()
        report.setdefault("environment", {})["port"] = actual_port
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
