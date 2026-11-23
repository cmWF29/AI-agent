#!/usr/bin/env python3
"""多节点模拟的执行节点进程。

经既有报文协议（4 字节长度前缀 + UTF-8 JSON，见 agent_common/api/private/_wire.py）
连控制面 UNIX socket，执行脚本化动作：登记 / 心跳 / 申领 / 续租 / 释放 / fencing / 视图。
本进程不持有协调状态，状态全部在控制面；它只是一个远端执行体。
"""
from __future__ import annotations

import argparse
import json
import socket
import struct
import sys


def _read_frame(sock):
    head = b""
    while len(head) < 4:
        chunk = sock.recv(4 - len(head))
        if not chunk:
            return None
        head += chunk
    (length,) = struct.unpack("!i", head)
    data = b""
    while len(data) < length:
        chunk = sock.recv(length - len(data))
        if not chunk:
            return None
        data += chunk
    return data


def rpc(sock, route, payload):
    body = json.dumps({"v": 1, "route": route, "payload": payload or {}}).encode("utf-8")
    sock.sendall(struct.pack("!i", len(body)) + body)
    resp = _read_frame(sock)
    if resp is None:
        return {"ok": False, "code": "disconnect"}
    return json.loads(resp.decode("utf-8"))


def _projects(csv):
    return [p.strip() for p in (csv or "").split(",") if p.strip()]


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--socket", required=True)
    ap.add_argument("--node", required=True)
    ap.add_argument("--action", required=True,
                    choices=["register", "heartbeat", "acquire", "renew",
                             "release", "fence", "view", "project", "reassign"])
    ap.add_argument("--projects", default="")
    ap.add_argument("--ttl", type=float, default=30.0)
    ap.add_argument("--token", default="")
    ap.add_argument("--epoch", type=int, default=0)
    ap.add_argument("--load", default="")
    ap.add_argument("--reason", default="node_lost")
    args = ap.parse_args(argv)

    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.connect(args.socket)
    try:
        if args.action == "register":
            result = rpc(sock, "nodes.register", {
                "id": args.node, "endpoint": "unix://" + args.node,
                "transport": "unix",
                "capacity": {"cpu": 2, "memory_mb": 2048},
                "lease_ttl": args.ttl})
        elif args.action == "heartbeat":
            load = json.loads(args.load) if args.load else {"running": 0}
            result = rpc(sock, "nodes.heartbeat", {"node": args.node, "load": load})
        elif args.action == "acquire":
            leases = []
            last = {}
            for project in _projects(args.projects):
                last = rpc(sock, "nodes.acquire", {
                    "project": project, "node": args.node,
                    "ttl": args.ttl, "tier": "weak"})
                leases.append(last)
            result = {"ok": all(l.get("ok") for l in leases), "leases": leases}
        elif args.action == "renew":
            result = rpc(sock, "nodes.renew",
                         {"project": _projects(args.projects)[0], "token": args.token})
        elif args.action == "release":
            result = rpc(sock, "nodes.release",
                         {"project": _projects(args.projects)[0], "token": args.token})
        elif args.action == "fence":
            result = rpc(sock, "nodes.fence_check",
                         {"project": _projects(args.projects)[0],
                          "token": args.token, "epoch": args.epoch})
        elif args.action == "view":
            result = rpc(sock, "nodes.nodes_view", {})
        elif args.action == "reassign":
            result = rpc(sock, "nodes.reassign",
                         {"project": _projects(args.projects)[0],
                          "candidate": args.node, "reason": args.reason})
        else:  # project
            result = rpc(sock, "nodes.project_node",
                         {"project": _projects(args.projects)[0]})
    finally:
        sock.close()

    print(json.dumps({"node": args.node, "action": args.action, "result": result},
                     ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
