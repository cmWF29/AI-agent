#!/usr/bin/env python3
"""黑盒 HTTP 压测：真实网络服务、真实 RPC、真实并发，不走进程内捷径。

用法：
  python scripts/perf_http.py --base http://127.0.0.1:8787 --levels 1,8,32 --duration 20
  python scripts/perf_http.py --base http://127.0.0.1:8787 --levels 8 --duration 5 \
      --max-p95-ms 800 --min-rps 5            # CI 冒烟
  python scripts/perf_http.py --base ... --soak-seconds 300

口径：
- 每个并发档位固定时长，统计成功请求的 p50/p95/p99、吞吐 RPS、错误率；
- 失败包括连接错误、非 2xx、`ok:false`、返回体不是对象/形状不符，不能只看出没出 200；
- 所有请求都打 HTTP API：健康检查、项目列表/详情、工单列表、登录态；
- 读多写少，写只在 setup 建一个临时项目，结束后删除，不污染业务档案。
"""
from __future__ import annotations

import argparse
import http.client
import json
import math
import random
import sys
import threading
import time
import urllib.parse
from dataclasses import dataclass, field
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BASE = "http://127.0.0.1:8787"


@dataclass
class Sample:
    ok: bool
    ms: float
    code: str = ""


@dataclass
class Stats:
    level: int
    total: int = 0
    errors: int = 0
    ms: list[float] = field(default_factory=list)
    codes: dict[str, int] = field(default_factory=dict)
    by_op: dict[str, dict] = field(default_factory=dict)
    started: float = 0.0
    ended: float = 0.0

    def reset(self):
        self.total = 0
        self.errors = 0
        self.ms = []
        self.codes = {}
        self.by_op = {}

    def add(self, sample: Sample, op: str = ""):
        self.total += 1
        self.ms.append(sample.ms)
        bucket = self.by_op.setdefault(op or "unknown",
                                        {"requests": 0, "errors": 0, "ms": [],
                                         "codes": {}})
        bucket["requests"] += 1
        bucket["ms"].append(sample.ms)
        if not sample.ok:
            self.errors += 1
            code = sample.code or "error"
            self.codes[code] = self.codes.get(code, 0) + 1
            bucket["errors"] += 1
            bucket["codes"][code] = bucket["codes"].get(code, 0) + 1

    @staticmethod
    def _pct(vals, p):
        if not vals:
            return 0.0
        idx = min(len(vals) - 1, max(0, int(math.ceil(p * len(vals)) - 1)))
        return round(vals[idx], 2)

    def as_dict(self):
        elapsed = max(self.ended - self.started, 0.001)
        vals = sorted(self.ms)

        def pct(p):
            return self._pct(vals, p)

        ops = {}
        for name, b in sorted(self.by_op.items()):
            ops[name] = {
                "requests": b["requests"],
                "errors": b["errors"],
                "error_rate": round(b["errors"] / b["requests"], 4) if b["requests"] else 1.0,
                "p50_ms": self._pct(sorted(b["ms"]), 0.50),
                "p95_ms": self._pct(sorted(b["ms"]), 0.95),
                "p99_ms": self._pct(sorted(b["ms"]), 0.99),
                "codes": dict(b["codes"]),
            }
        return {
            "level": self.level,
            "requests": self.total,
            "errors": self.errors,
            "error_rate": round(self.errors / self.total, 4) if self.total else 1.0,
            "rps": round(self.total / elapsed, 2),
            "p50_ms": pct(0.50),
            "p95_ms": pct(0.95),
            "p99_ms": pct(0.99),
            "max_ms": round(vals[-1], 2) if vals else 0.0,
            "codes": dict(self.codes),
            "by_op": ops,
        }


class Client:
    def __init__(self, base, token=""):
        self.base = base.rstrip("/")
        parsed = urllib.parse.urlparse(self.base)
        self.host = parsed.hostname
        self.port = parsed.port or (443 if parsed.scheme == "https" else 80)
        self.https = parsed.scheme == "https"
        self.token = token
        self.conn = None

    def _open(self):
        cls = http.client.HTTPSConnection if self.https else http.client.HTTPConnection
        self.conn = cls(self.host, self.port, timeout=20)
        self.conn.connect()

    def close(self):
        if self.conn is not None:
            self.conn.close()
            self.conn = None

    def call(self, path, payload=None):
        """返回 (Sample, parsed); 非 2xx / 非 YAML 对象都记失败。"""
        body = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers = {"Content-Type": "application/json", "Connection": "keep-alive"}
        if self.token:
            headers["X-Auth-Token"] = self.token
        if self.conn is None:
            self._open()
        t0 = time.perf_counter()
        try:
            self.conn.request("POST" if body is not None else "GET", path, body=body, headers=headers)
            resp = self.conn.getresponse()
            raw = resp.read()
            elapsed = (time.perf_counter() - t0) * 1000.0
            if resp.status < 200 or resp.status >= 300:
                return Sample(False, elapsed, "http_%d" % resp.status), None
            try:
                data = yaml.safe_load(raw.decode("utf-8"))
            except Exception:
                return Sample(False, elapsed, "bad_yaml"), None
            if not isinstance(data, dict):
                return Sample(False, elapsed, "bad_shape"), None
            return Sample(True, elapsed, ""), data
        except Exception as exc:  # noqa: BLE001
            elapsed = (time.perf_counter() - t0) * 1000.0
            self.close()
            return Sample(False, elapsed, type(exc).__name__), None

    def rpc(self, demand_id, inp=None):
        sample, data = self.call("/api/rpc/demand_engine/run",
                                 {"id": demand_id, "input": inp or {}})
        if not sample.ok:
            return sample, None
        # 顶层失败与内层失败都要拦：只读 200 会把业务错误算成成功。
        if data.get("ok") is False:
            return Sample(False, sample.ms, "rpc_%s" % (data.get("code") or "false")), data
        inner = data.get("result")
        if isinstance(inner, dict) and inner.get("ok") is False:
            return Sample(False, sample.ms,
                          "rpc_%s" % (inner.get("code") or "false")), data
        if "result" not in data:
            return Sample(False, sample.ms, "bad_shape"), data
        return sample, data


def demand(base, demand_id, inp=None, token=""):
    c = Client(base, token)
    try:
        return c.rpc(demand_id, inp)
    finally:
        c.close()


def login(base, username, password):
    """优先标准登录；auth 关闭时返回空 token，服务本身按本机开发放行。"""
    if not username:
        return ""
    c = Client(base)
    try:
        s, data = c.call("/api/auth/login", {"username": username, "password": password})
        if not s.ok:
            raise SystemExit("登录失败: %s" % s.code)
        if data.get("ok") is False:
            raise SystemExit("登录失败: %s" % (data.get("code") or "false"))
        return data.get("token") or ""
    finally:
        c.close()


def create_probe_project(base, token):
    name = "perf-probe-%d" % int(time.time())
    s, _ = demand(base, "projects-create", {"name": name}, token)
    if not s.ok:
        raise SystemExit("建压测项目失败: %s" % s.code)
    s2, data = demand(base, "projects-list", {}, token)
    if not s2.ok:
        raise SystemExit("列项目失败: %s" % s2.code)
    rows = ((data.get("result") or {}).get("result") or {}).get("items") or []
    for row in rows:
        if isinstance(row, dict) and row.get("name") == name:
            return row.get("id") or name, name
    return name, name


def delete_probe_project(base, token, project_id):
    # 压测夹具必须真删：默认 remove 会归档，反复压测会在数据目录堆垃圾。
    demand(base, "projects-delete", {"id": project_id, "purge": True}, token)


WORK = [
    ("health", "GET", "/api/health/live", None, 10),
    ("rpc", "RPC", "projects-list", {}, 30),
    ("rpc", "RPC", "ticket-list", {}, 20),
    ("rpc", "RPC", "projects-get", None, 20),
    ("rpc", "RPC", "auth-status", {}, 10),
    ("page", "PAGE", "/api/rpc/demand_engine/resolve", {"view": "projects-list"}, 10),
]


def one_request(client, item, project_id, rng):
    kind, _action, path, payload, _weight = item
    if kind == "health":
        sample, data = client.call(path)
        if sample.ok and data.get("ok") is not True:
            return Sample(False, sample.ms, "health_false")
        return sample
    if kind == "page":
        sample, data = client.call(path, payload)
        if sample.ok and data.get("ok") is False:
            return Sample(False, sample.ms, "page_false")
        return sample
    inp = dict(payload or {})
    if path == "projects-get":
        inp["id"] = project_id
    if path == "ticket-list":
        inp["project"] = project_id
    return client.rpc(path, inp)[0]


def op_name(item) -> str:
    kind, action, path = item[0], item[1], item[2]
    if kind == "rpc":
        return "rpc:" + str(path)
    if kind == "page":
        return "page:" + str((item[3] or {}).get("view") or path)
    return str(path)


def run_level(base, token, level, duration, project_id, warmup=3.0):
    stats = Stats(level)
    stop = threading.Event()
    weights = [item[4] for item in WORK]

    def worker(idx):
        c = Client(base, token)
        rng = random.Random(1000 + idx)
        try:
            while not stop.is_set():
                item = WORK[rng.choices(range(len(WORK)), weights=weights, k=1)[0]]
                stats.add(one_request(c, item, project_id, rng), op_name(item))
        finally:
            c.close()

    threads = [threading.Thread(target=worker, args=(i,), name="perf-%d-%d" % (level, i))
               for i in range(level)]
    for t in threads:
        t.start()
    if warmup:
        time.sleep(warmup)
    stats.reset()
    stats.started = time.perf_counter()
    time.sleep(duration)
    stop.set()
    for t in threads:
        t.join(timeout=5)
    stats.ended = time.perf_counter()
    return stats.as_dict()


def run_burst(base, token, clients, per_client, project_id):
    """突发：N 个连接同时放开，每个固定打 M 次，考验收站/排队而不是稳态吞吐。"""
    stats = Stats(clients)
    weights = [item[4] for item in WORK]
    barrier = threading.Barrier(clients)

    def worker(idx):
        c = Client(base, token)
        rng = random.Random(2000 + idx)
        try:
            barrier.wait(timeout=10)
            for _ in range(per_client):
                item = WORK[rng.choices(range(len(WORK)), weights=weights, k=1)[0]]
                stats.add(one_request(c, item, project_id, rng), op_name(item))
        except threading.BrokenBarrierError:
            stats.add(Sample(False, 0.0, "burst_barrier"), "burst")
        finally:
            c.close()

    threads = [threading.Thread(target=worker, args=(i,), name="burst-%d" % i)
               for i in range(clients)]
    stats.started = time.perf_counter()
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    stats.ended = time.perf_counter()
    out = stats.as_dict()
    out["mode"] = "burst"
    out["per_client"] = per_client
    return out


def parse_levels(raw):
    out = []
    for part in raw.split(","):
        part = part.strip()
        if part:
            n = int(part)
            if n < 1 or n > 512:
                raise argparse.ArgumentTypeError("并发档位必须在 1..512")
            out.append(n)
    return out or [1, 8, 32]


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default=DEFAULT_BASE)
    ap.add_argument("--username", default="")
    ap.add_argument("--password", default="")
    ap.add_argument("--levels", default="1,8,32")
    ap.add_argument("--duration", type=float, default=20.0)
    ap.add_argument("--warmup", type=float, default=3.0)
    ap.add_argument("--soak-seconds", type=float, default=0.0)
    ap.add_argument("--burst", type=int, default=0,
                    help="突发连接数（0 关闭）；所有连接同一时刻放开")
    ap.add_argument("--burst-reqs", type=int, default=3)
    ap.add_argument("--max-p95-ms", type=float, default=300.0)
    ap.add_argument("--max-p99-ms", type=float, default=1500.0)
    ap.add_argument("--max-error-rate", type=float, default=0.001)
    ap.add_argument("--min-rps", type=float, default=20.0)
    ap.add_argument("--json-out", default="")
    args = ap.parse_args(argv)

    token = login(args.base, args.username, args.password)
    project_id, project_name = create_probe_project(args.base, token)
    rows = []
    try:
        for level in parse_levels(args.levels):
            rows.append(run_level(args.base, token, level, args.duration, project_id,
                                  warmup=args.warmup))
        if args.soak_seconds:
            rows.append(run_level(args.base, token, max(parse_levels(args.levels)),
                                  args.soak_seconds, project_id, warmup=args.warmup))
        if args.burst:
            rows.append(run_burst(args.base, token, args.burst, args.burst_reqs, project_id))
    finally:
        delete_probe_project(args.base, token, project_id)

    payload = {"base": args.base, "project": project_name, "runs": rows}
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    if args.json_out:
        Path(args.json_out).write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                                       encoding="utf-8")

    bad = []
    for row in rows:
        if row["requests"] <= 0:
            bad.append("并发 %d 没有收到任何响应" % row["level"])
            continue
        if row["error_rate"] > args.max_error_rate:
            bad.append("并发 %d 错误率 %.3f > %.3f" % (row["level"], row["error_rate"],
                                                    args.max_error_rate))
        if row["p95_ms"] > args.max_p95_ms:
            bad.append("并发 %d p95 %.1fms > %.1fms" % (row["level"], row["p95_ms"],
                                                       args.max_p95_ms))
        if row["p99_ms"] > args.max_p99_ms:
            bad.append("并发 %d p99 %.1fms > %.1fms" % (row["level"], row["p99_ms"],
                                                       args.max_p99_ms))
        if row["rps"] < args.min_rps:
            bad.append("并发 %d RPS %.1f < %.1f" % (row["level"], row["rps"], args.min_rps))
    if bad:
        print("\n性能门禁失败：", file=sys.stderr)
        for item in bad:
            print(" - " + item, file=sys.stderr)
        return 1
    print("\n性能门禁通过", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
