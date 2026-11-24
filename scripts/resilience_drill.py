#!/usr/bin/env python3
"""L4 韧性演练：真实子进程、真实文件锁台账、真实 kill -9。

覆盖四类生产故障：
1. 执行体被 kill -9：已写台账仍可读；租约到期后只有新执行体接管，结算后复用；
2. 多进程同时抢同一业务键：只允许一个 claimed，其余看到 in_flight；
3. 租约过期 + sweep：在途记录被标 abandoned，后来者不自动接管，交人工；
4. 在途恢复不双跑：原执行体在途时第二个执行体被拒；杀掉并等租约过期后
   只允许一次接管，结算 done 后再来直接复用。

只写临时 AI_NEW_DATA 目录，不碰源码树；每个子进程独立进程，kill 用 SIGKILL。
输出 JSON（--json）或人读摘要，任一断言失败退出码非 0。
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ai_new.modules.agent_common.store.private import _idem  # noqa: E402

MODULE = "agent_test"
BUCKET = "resilience"


class _Clock:
    def now(self):
        ts = time.time()
        return {"ts": ts, "iso": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(ts))}


class _Ctx:
    clock = _Clock()


CTX = _Ctx()


def _claim(key, lease=60):
    return _idem._route_claim(CTX, {
        "module": MODULE, "bucket": BUCKET, "key": key,
        "route": "resilience.probe", "scope": "drill", "lease_seconds": lease})


def _settle(key, status="done", digest="", code=""):
    return _idem._route_settle(CTX, {
        "module": MODULE, "bucket": BUCKET, "key": key, "status": status,
        "result_digest": digest, "error_code": code})


def _sweep(mark=True):
    return _idem._route_sweep(CTX, {
        "module": MODULE, "bucket": BUCKET, "mark": mark})


def _record(key):
    try:
        return json.loads(_idem._rec_path(MODULE, BUCKET, key).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _wait_file(path: Path, timeout=4.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if path.is_file():
            return True
        time.sleep(0.05)
    return False


def _check(checks, name, ok, detail=""):
    checks.append({"name": str(name), "ok": bool(ok), "detail": str(detail)})


def _spawn_child(base: Path, key: str, *, lease: float, hold: float = 0.0,
                 start_delay: float = 0.0):
    result = base / ("child-%s-%d.json" % (key, time.time_ns()))
    result.unlink(missing_ok=True)
    cmd = [sys.executable, str(Path(__file__).resolve()),
           "--child", "--key", key, "--lease", str(lease),
           "--hold", str(hold), "--start-delay", str(start_delay),
           "--result", str(result)]
    env = os.environ.copy()
    env["AI_NEW_DATA"] = str(base)
    return subprocess.Popen(cmd, stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL, env=env), result


def _child(args):
    """子进程模式：占位、写结果文件、可选持有；父进程负责 kill。"""
    if args.start_delay > 0:
        time.sleep(args.start_delay)
    out = _claim(args.key, lease=args.lease)
    Path(args.result).write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
    if args.hold > 0:
        time.sleep(args.hold)
    return 0


def _kill(proc):
    if proc is None:
        return
    if proc.poll() is None:
        proc.kill()
    try:
        proc.wait(timeout=3)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=3)


def scenario_kill_and_takeover(base: Path):
    checks = []
    proc, result = _spawn_child(base, "kill-restart", lease=2, hold=30)
    try:
        assert _wait_file(result, 4.0), "子进程未写出占位结果"
        _kill(proc)
        rec = _record("kill-restart")
        _check(checks, "kill -9 后台账仍可读",
               rec.get("status") == "claimed",
               "status=%s attempt=%s" % (rec.get("status"), rec.get("attempt")))
        early = _claim("kill-restart", lease=2)
        _check(checks, "租约未过期时拒绝接管",
               early.get("claimed") is False,
               "status=%s in_flight=%s" % (early.get("status"), early.get("in_flight")))
        time.sleep(2.3)
        takeover = _claim("kill-restart", lease=30)
        _check(checks, "租约过期后只接管一次",
               takeover.get("claimed") is True and int(takeover.get("attempt") or 0) == 2,
               "claimed=%s attempt=%s" % (takeover.get("claimed"), takeover.get("attempt")))
        _settle("kill-restart", "done", digest="ticket:T-1")
        again = _claim("kill-restart", lease=30)
        _check(checks, "结算后复用不重跑",
               again.get("status") == "done" and again.get("reused") is True,
               "status=%s reused=%s" % (again.get("status"), again.get("reused")))
    finally:
        _kill(proc)
    return checks


def scenario_concurrent_claim(base: Path):
    checks = []
    procs = []
    try:
        for index in range(6):
            proc, result = _spawn_child(base, "race", lease=60,
                                        start_delay=0.15 + index * 0.02)
            procs.append((proc, result))
        claimed = 0
        for proc, result in procs:
            proc.wait(timeout=5)
            assert result.is_file(), "并发子进程未返回结果"
            out = json.loads(result.read_text(encoding="utf-8"))
            claimed += 1 if out.get("claimed") else 0
        _check(checks, "6 进程并发只一个执行权", claimed == 1, "claimed=%d" % claimed)
        _settle("race", "done", digest="race:done")
        after = _claim("race", lease=60)
        _check(checks, "并发胜者结算后复用",
               after.get("status") == "done",
               "status=%s reused=%s" % (after.get("status"), after.get("reused")))
    finally:
        for proc, _ in procs:
            _kill(proc)
    return checks


def scenario_lease_sweep_abandon(base: Path):
    checks = []
    first = _claim("sweep-abandon", lease=1)
    _check(checks, "首次占位成功", first.get("claimed") is True,
           "claimed=%s" % first.get("claimed"))
    time.sleep(1.25)
    swept = _sweep(mark=True)
    _check(checks, "sweep 标记过期在途",
           "sweep-abandon" in (swept.get("expired") or []) and swept.get("marked") == 1,
           "expired=%s marked=%s" % (swept.get("expired"), swept.get("marked")))
    later = _claim("sweep-abandon", lease=30)
    _check(checks, "abandoned 不自动接管",
           later.get("claimed") is False and later.get("status") == "abandoned",
           "claimed=%s status=%s" % (later.get("claimed"), later.get("status")))
    return checks


def scenario_no_double_after_recover(base: Path):
    checks = []
    holder, holder_result = _spawn_child(base, "no-double", lease=2, hold=30)
    intruder = None
    try:
        assert _wait_file(holder_result, 4.0), "持有者未写出结果"
        intruder, intruder_result = _spawn_child(base, "no-double", lease=2, hold=0.5)
        intruder.wait(timeout=4)
        out = json.loads(intruder_result.read_text(encoding="utf-8"))
        _check(checks, "在途时第二个执行体被拒",
               out.get("claimed") is False and out.get("in_flight") is True,
               "claimed=%s status=%s" % (out.get("claimed"), out.get("status")))
        _kill(holder)
        time.sleep(2.3)
        recover, recover_result = _spawn_child(base, "no-double", lease=30)
        recover.wait(timeout=4)
        out2 = json.loads(recover_result.read_text(encoding="utf-8"))
        _check(checks, "恢复后只接管一次",
               out2.get("claimed") is True and int(out2.get("attempt") or 0) == 2,
               "claimed=%s attempt=%s" % (out2.get("claimed"), out2.get("attempt")))
        _settle("no-double", "done", digest="recovered")
        final, final_result = _spawn_child(base, "no-double", lease=30)
        final.wait(timeout=4)
        out3 = json.loads(final_result.read_text(encoding="utf-8"))
        _check(checks, "结算后不二次执行",
               out3.get("status") == "done" and out3.get("reused") is True,
               "status=%s reused=%s" % (out3.get("status"), out3.get("reused")))
    finally:
        _kill(holder)
        _kill(intruder)
    return checks


def run_drill():
    checks = []
    with tempfile.TemporaryDirectory(prefix="resilience-drill-") as tmp:
        base = Path(tmp)
        os.environ["AI_NEW_DATA"] = str(base)
        try:
            checks.extend(scenario_kill_and_takeover(base))
            checks.extend(scenario_concurrent_claim(base))
            checks.extend(scenario_lease_sweep_abandon(base))
            checks.extend(scenario_no_double_after_recover(base))
        finally:
            os.environ.pop("AI_NEW_DATA", None)
    return {"ok": all(c["ok"] for c in checks), "checks": checks}


def main(argv=None):
    parser = argparse.ArgumentParser(description="L4 韧性演练")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--child", action="store_true")
    parser.add_argument("--key", default="")
    parser.add_argument("--lease", type=float, default=60.0)
    parser.add_argument("--hold", type=float, default=0.0)
    parser.add_argument("--start-delay", type=float, default=0.0)
    parser.add_argument("--result", default="")
    args = parser.parse_args(argv)
    if args.child:
        return _child(args)
    report = run_drill()
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        for c in report["checks"]:
            print("  %s %s（%s）" % ("OK" if c["ok"] else "FAIL", c["name"], c["detail"]))
        print("L4 韧性演练：%d/%d 通过" % (sum(1 for c in report["checks"] if c["ok"]),
                                           len(report["checks"])))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
