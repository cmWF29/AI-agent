#!/usr/bin/env python3
"""多节点分布式本地模拟：控制面 + 多个执行节点进程，走既有 UNIX 报文通道。

覆盖场景：
  1. 节点登记 / 心跳 / 容量上报；
  2. 项目→节点分配（项目固定落一个节点，项目内工单在该节点执行）；
  3. 并发申领同一项目：恰好一个持有，另一个 lease_held（不双跑）；
  4. 节点失联：租约 TTL 过期后回收，待命节点接手重调度，epoch 单调递增；
  5. fencing：旧节点凭旧 token/epoch 回写被拒；
  6. 越权不可见：节点视图只列自己持有的项目；
  7. 目录级快照 + 摘要清单 + 校验 + 恢复演练。

说明：控制面状态在本进程内存中；执行体是独立子进程，报文通道复用
agent_common/api 的 4 字节长度前缀 + JSON 帧格式。跨主机真实部署不在本轮范围。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import socket
import struct
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ai_new.modules.agent.nodes.private import _pure  # noqa: E402
from ai_new.modules.agent.sandbox.private import _pure as _spure  # noqa: E402

WORKER = ROOT / "scripts" / "node_worker.py"
TTL = 2.0
STATE = _pure.empty_state()
_LOCK = threading.Lock()


# ---------------------------------------------------------------- 控制面分发

def dispatch(route, payload):
    now = time.time()
    if route == "nodes.register":
        return _pure.register(STATE, payload, now)
    if route == "nodes.heartbeat":
        return _pure.heartbeat(STATE, payload.get("node"), payload.get("load"), now)
    if route == "nodes.acquire":
        return _pure.acquire(STATE, payload.get("project"), payload.get("node"), now,
                             ttl=payload.get("ttl"), tier=payload.get("tier"))
    if route == "nodes.renew":
        return _pure.renew(STATE, payload.get("project"), payload.get("token"), now)
    if route == "nodes.release":
        return _pure.release(STATE, payload.get("project"), payload.get("token"), now)
    if route == "nodes.fence_check":
        return _pure.fence_check(STATE, payload.get("project"), payload.get("token"),
                                 payload.get("epoch"))
    if route == "nodes.nodes_view":
        return {"ok": True, "nodes": _pure.nodes_view(STATE, now, ttl=payload.get("ttl"))}
    if route == "nodes.assignments":
        return {"ok": True, "assignments": _pure.assignments_view(STATE)}
    if route == "nodes.project_node":
        return {"ok": True, "assignment": _pure.project_node(STATE, payload.get("project"))}
    if route == "nodes.backups":
        return {"ok": True, "backups": _pure.backups_view(STATE)}
    if route == "nodes.backup_record":
        return {"ok": True, "backup": _pure.record_backup(
            STATE, payload.get("project"), payload.get("snapshot") or {})}
    if route == "nodes.snapshot_plan":
        return _pure.plan_snapshot(payload.get("project"), payload.get("entries"), now)
    if route == "nodes.verify_snapshot":
        return _pure.verify_manifest(payload.get("manifest") or {}, payload.get("digests") or {})
    if route == "nodes.sweep":
        return _pure.sweep_expired(STATE, now, ttl=payload.get("ttl"))
    if route == "nodes.pick_node":
        return {"ok": True, **_pure.pick_node(STATE, payload.get("project"), now,
                                              payload.get("policy"))}
    if route == "nodes.reassign":
        return _pure.reassign(STATE, payload.get("project"), now,
                              policy=payload.get("policy"),
                              candidate=payload.get("candidate"),
                              reason=payload.get("reason"),
                              checkpoint=payload.get("checkpoint"))
    if route == "nodes.migrations":
        return {"ok": True, "migrations": _pure.migrations_view(STATE)}
    if route == "sandbox.pick_tier":
        return {"ok": True, **_spure.pick_tier(payload or {})}
    if route == "sandbox.plan":
        return _spure.plan(payload.get("project"), payload.get("tier"),
                           payload.get("workspace") or {})
    return {"ok": False, "code": "unknown_route", "route": route}


def _read_frame(conn):
    head = b""
    while len(head) < 4:
        chunk = conn.recv(4 - len(head))
        if not chunk:
            return None
        head += chunk
    (length,) = struct.unpack("!i", head)
    data = b""
    while len(data) < length:
        chunk = conn.recv(length - len(data))
        if not chunk:
            return None
        data += chunk
    return data


def _serve(conn):
    try:
        while True:
            frame = _read_frame(conn)
            if frame is None:
                break
            req = json.loads(frame.decode("utf-8"))
            with _LOCK:
                result = dispatch(req.get("route"), req.get("payload") or {})
            body = json.dumps({"ok": result.get("ok", False), "result": result}).encode("utf-8")
            conn.sendall(struct.pack("!i", len(body)) + body)
    finally:
        conn.close()


def start_server(sock_path):
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(sock_path)
    server.listen(8)

    def loop():
        while True:
            try:
                conn, _ = server.accept()
            except OSError:
                return
            threading.Thread(target=_serve, args=(conn,), daemon=True).start()

    threading.Thread(target=loop, daemon=True).start()
    return server


# ---------------------------------------------------------------- 执行体调用

def worker(node, action, **kwargs):
    cmd = [sys.executable, str(WORKER), "--socket", SOCK_PATH, "--node", node,
           "--action", action, "--ttl", str(TTL)]
    for key, value in kwargs.items():
        cmd += ["--" + key.replace("_", "-"), str(value)]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
    if proc.returncode != 0:
        raise RuntimeError("worker %s %s 失败: %s" % (node, action, proc.stderr))
    return json.loads(proc.stdout.strip().splitlines()[-1])["result"]


def race_acquire(node, project):
    return worker(node, "acquire", projects=project)


# ---------------------------------------------------------------- 备份/恢复

def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def backup_restore_demo(src_root: Path, backup_root: Path, restore_root: Path):
    """目录级快照：清单 + 摘要 + 复制 + 校验 + 恢复 + 逐文件比对。"""
    project = "p1"
    tree = src_root / project
    (tree / "tickets").mkdir(parents=True)
    (tree / "knowledge").mkdir(parents=True)
    (tree / "artifacts").mkdir(parents=True)
    (tree / "tickets" / "t1.yaml").write_text("status: open\n", encoding="utf-8")
    (tree / "knowledge" / "doc.md").write_text("# 项目知识\n", encoding="utf-8")
    (tree / "artifacts" / "a.bin").write_bytes(bytes(range(256)))

    rels = ["tickets/t1.yaml", "knowledge/doc.md", "artifacts/a.bin"]
    plan = dispatch("nodes.snapshot_plan", {"project": project, "entries": rels})
    assert plan["ok"], plan["rejected"]
    manifest = plan["manifest"]

    digests = {rel: _sha256(tree / rel) for rel in rels}
    ver = dispatch("nodes.verify_snapshot", {"manifest": manifest, "digests": digests})
    assert ver["ok"], ver
    for entry in manifest["entries"]:
        entry["digest"] = digests[entry["rel"]]

    # 复制进备份目录（保留相对布局）
    snap_dir = backup_root / project
    for rel in rels:
        dest = snap_dir / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(tree / rel, dest)
    dispatch("nodes.backup_record", {"project": project,
                                     "snapshot": {"snapshot_id": str(manifest["created_at"]),
                                                  "state": "verified",
                                                  "entries": manifest["entries"]}})

    # 恢复：调独立恢复脚本，还原到 restore_root，再逐文件比对摘要
    restore_script = ROOT / "scripts" / "restore_node_snapshot.py"
    subprocess.run([sys.executable, str(restore_script), "--snapshot-dir", str(snap_dir),
                    "--project", project, "--dest", str(restore_root)],
                   check=True, capture_output=True, text=True)
    restored = restore_root / project
    restored_digests = {rel: _sha256(restored / rel) for rel in rels}
    assert restored_digests == digests, "恢复后摘要不一致"
    return {"manifest": manifest, "digests": digests, "restored": str(restored)}


# ---------------------------------------------------------------- 场景编排

def main():
    global SOCK_PATH
    ap = argparse.ArgumentParser()
    ap.add_argument("--keep-tmp", action="store_true")
    args = ap.parse_args()

    tmp = tempfile.mkdtemp(prefix="nodes-sim-")
    SOCK_PATH = str(Path(tmp) / "ctrl.sock")
    server = start_server(SOCK_PATH)
    report = {"steps": []}

    try:
        # 1. 登记 + 心跳
        a = worker("node-A", "register")
        b = worker("node-B", "register")
        assert a["ok"] and b["ok"]
        worker("node-A", "heartbeat", load='{"running": 2}')
        worker("node-B", "heartbeat", load='{"running": 0}')
        report["steps"].append("1. 两节点登记并心跳完成")

        # 2. 项目分配：A 持 p1,p2；B 持 p3
        ra = race_acquire("node-A", "p1,p2")
        rb = race_acquire("node-B", "p3")
        assert ra["ok"] and rb["ok"]
        report["steps"].append("2. 分配：A→p1,p2；B→p3")

        # 3. 并发申领 p4：两个进程同时抢，恰好一个持有
        race_results = []
        def _race(node):
            race_results.append(race_acquire(node, "p4"))
        t1 = threading.Thread(target=_race, args=("node-A",))
        t2 = threading.Thread(target=_race, args=("node-B",))
        t1.start(); t2.start(); t1.join(); t2.join()
        oks = [r for r in race_results if r["ok"]]
        held = [r["leases"][0]["result"]["lease"]["node"] for r in oks]
        assert len(oks) == 1, race_results
        report["steps"].append("3. 并发抢 p4：恰好一个持有 → %s" % held[0])

        # 4. A 失联：先等过 TTL 让 A 过期；待命 B 扫前立即心跳刷新，回收 A 的租约
        time.sleep(TTL + 0.2)
        worker("node-B", "heartbeat", load='{"running": 1}')
        sweep = dispatch("nodes.sweep", {"ttl": TTL})
        assert "node-A" in sweep["expired"], sweep
        assert "node-B" not in sweep["expired"], sweep
        assert set(sweep["released"]) >= {"p1", "p2"}, sweep
        failover = race_acquire("node-B", "p1,p2")
        assert failover["ok"], failover
        epochs = [l["result"]["lease"]["epoch"] for l in failover["leases"]]
        report["steps"].append("4. A 失联回收；B 接手 p1,p2，epoch=%s" % epochs)

        # 5. fencing：A 旧 token 回写 p1 必须被拒
        old_token = ra["leases"][0]["result"]["lease"]["token"]
        fence = worker("node-A", "fence", projects="p1", token=old_token, epoch=1)
        assert not fence["ok"], fence
        report["steps"].append("5. 旧 token/epoch 回写被 fencing 拒：%s"
                               % fence["result"]["code"])

        # 6. 越权不可见：B 视图只含自己持有项目；A 视图为空
        view_b = worker("node-B", "view")
        view_a = worker("node-A", "view")
        b_projects = sorted(p for n in view_b["result"]["nodes"] if n["id"] == "node-B"
                            for p in n["projects"])
        a_projects = [p for n in view_a["result"]["nodes"] if n["id"] == "node-A"
                      for p in n["projects"]]
        assert a_projects == [], a_projects
        report["steps"].append("6. 不可见：A 无可见项目；B 持有 %s" % b_projects)

        # 7. 备份 / 恢复演练
        backup = backup_restore_demo(Path(tmp) / "src", Path(tmp) / "backup",
                                     Path(tmp) / "restore")
        report["steps"].append("7. 快照校验通过；恢复后 %d 个文件摘要一致"
                               % len(backup["digests"]))

        # 8. 假死回收后自动回迁：A 重新报到持 p5、p6；停心跳过 TTL 后 B 接手 p5
        worker("node-A", "register")
        worker("node-A", "heartbeat", load='{"running": 1}')
        ra5 = race_acquire("node-A", "p5")
        ra6 = race_acquire("node-A", "p6")
        assert ra5["ok"] and ra6["ok"]
        old_p5_token = ra5["leases"][0]["result"]["lease"]["token"]
        time.sleep(TTL + 0.2)
        worker("node-B", "heartbeat", load='{"running": 1}')
        sweep = dispatch("nodes.sweep", {"ttl": TTL})
        assert "node-A" in sweep["expired"], sweep
        assert "node-B" not in sweep["expired"], sweep
        rea5 = dispatch("nodes.reassign", {"project": "p5", "reason": "node_lost"})
        assert rea5["ok"], rea5
        assert rea5["lease"]["node"] == "node-B"
        assert rea5["lease"]["epoch"] == 2
        assert rea5["migration"]["state"] == "done"
        assert rea5["migration"]["from_node"] == "node-A"
        assert rea5["migration"]["to_node"] == "node-B"
        report["steps"].append("8. A 假死回收；自动回迁 p5 → B，epoch=2，台账 done")

        # 9. 迁移中再次失败：p6 历史在 A，候选 B 也置不可用 → no_candidate，台账 failed
        STATE["nodes"]["node-B"]["status"] = "lost"
        rea6 = dispatch("nodes.reassign", {"project": "p6", "reason": "node_lost"})
        assert not rea6["ok"], rea6
        assert rea6["code"] == "no_candidate"
        assert rea6["migration"]["state"] == "failed"
        assert rea6["migration"]["to_node"] is None
        assert STATE["leases"]["p6"]["state"] == "released"
        STATE["nodes"]["node-B"]["status"] = "alive"
        report["steps"].append("9. 迁移中候选再失败：p6 记 failed 待调度，无第二持有者")

        # 10. A 恢复后不抢回 p5；旧 token/epoch 回写被 fencing 拒
        worker("node-A", "heartbeat", load='{"running": 0}')
        back = dispatch("nodes.acquire", {"project": "p5", "node": "node-A"})
        assert (not back["ok"]) and back["code"] == "lease_held", back
        assert back["holder"] == "node-B"
        fence = dispatch("nodes.fence_check", {"project": "p5",
                                                "token": old_p5_token, "epoch": 1})
        assert not fence["ok"]
        report["steps"].append("10. A 恢复后不抢回 p5（lease_held）；旧 epoch 回写被拒：%s"
                               % fence["code"])

        # 汇总视图
        report["nodes"] = dispatch("nodes.nodes_view", {})["nodes"]
        report["assignments"] = dispatch("nodes.assignments", {})["assignments"]
        report["backups"] = dispatch("nodes.backups", {})["backups"]
        report["migrations"] = dispatch("nodes.migrations", {})["migrations"]
        report["backup_restore"] = backup
    finally:
        server.close()
        if not args.keep_tmp:
            shutil.rmtree(tmp, ignore_errors=True)

    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
