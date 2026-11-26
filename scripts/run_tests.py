#!/usr/bin/env python3
"""本地全量巡检 runner：按测试模块分发到多进程，隔离每个分片的数据目录。

为什么不是一条 ``python -m unittest``：31 个模块全串行在本机也要 4 分钟，云端单核
更久；模块之间本来就可独立跑，缺的只是隔离与分发。这里给每个子进程独立的
``AI_NEW_DATA``，避免共享仓库 data 互相污染，再按模块并行收结果。

用法：
  python scripts/run_tests.py --jobs 4
  python scripts/run_tests.py --jobs 8 --modules test_core,test_api
  python scripts/run_tests.py --jobs 4 --json-out run.json

口径：任一模块非零即整体失败；逐模块耗时都打印，慢模块一眼可见。
"""
from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TESTDIR = ROOT / "ai_new" / "modules" / "agent_test" / "private"

DEFAULT_MODULES = [
    "test_core", "test_architecture", "test_demands", "test_demand_engine",
    "test_demand_engine_routes", "test_boot_graph", "test_transport", "test_idem",
    "test_stub_proto", "test_stub_faults", "test_graph_patterns", "test_isolation",
    "test_knowledge_concurrency", "test_node_profile", "test_nodes",
    "test_distributed", "test_isolation_tiers", "test_archive", "test_secretary",
    "test_timer", "test_role_gates", "test_skill_decompose", "test_plat", "test_plat_edges",
    "test_isolation_windows", "test_cloud", "test_cloud_guard", "test_cloud_seal",
    "test_cloud_sync", "test_cloud_s3", "test_s3_edges", "test_api_routes",
    "test_host_probe", "test_http_server", "test_react_pure", "test_react_routes", "test_channel_routes", "test_web_panel", "test_sandbox_host_routes", "test_exec_edges", "test_artifacts_routes", "test_cloud_webdav",
    "test_react_mechanisms",
    "test_gate_diff_coverage", "test_security_boundaries", "test_api",
    "test_deadcode", "test_docsync", "test_levels",
    "test_asr", "test_platform_branches", "test_pure_edges", "test_tickets_routes",
    "test_decompose_pure", "test_archive_engine", "test_archive_backend_routes", "test_archive_edges", "test_store_files_edges", "test_store_panel", "test_common_small_pkgs", "test_store_misc_edges", "test_trace",
    "test_knowledge_pure", "test_knowledge_routes", "test_decompose_routes", "test_webdav_client", "test_clock",
    "test_nodes_edges", "test_nodes_routes", "test_timer_edges",
    "test_timer_routes_edges", "test_cloud_edges2", "test_artifacts_pure_edges",
    "test_tools_pure_edges", "test_sessions_pure_edges", "test_registry_edges",
    "test_transport_edges", "test_lock_edges", "test_hooks_edges", "test_net_client",
    "test_serve_edges", "test_runtime_core", "test_exec_runner",
    "test_store_isolate", "test_cloud_provider_adapters", "test_boot_edges",
    "test_demand_engine_edges", "test_boot_graph_edges", "test_tools_routes",
    "test_secretary_routes", "test_pure_batch", "test_sess_proj_routes",
    "test_run_pure", "test_llm_auth", "test_idem_edges",
]

# 会占用固定端口 / 拉起 sidecar 的模块：并行必抢 8790/9000，单独串行跑。
SERIAL_MODULES = {"test_transport", "test_distributed",
                  "test_cloud_s3", "test_cloud_webdav"}


def run_one(mod: str, timeout: int, base_port: int, cov_dir: str = "") -> dict:
    workdir = Path(tempfile.mkdtemp(prefix="hive-test-%s-" % mod))
    # AI_NEW_DATA 是"部署覆盖"布局，不是空目录：按 modules/ 镜像把各模块 data 暂存进去，
    # 否则读 checks/demands 的模块会把空目录当数据根。
    sys.path.insert(0, str(TESTDIR))
    from _fixtures import stage  # noqa: E402
    stage(workdir)
    env = dict(os.environ)
    env.update({
        "AI_NEW_STUB": "1",
        "AI_NEW_DATA": str(workdir),
        "PYTHONUNBUFFERED": "1",
    })
    if cov_dir:
        cmd = [sys.executable, "-m", "coverage", "run",
               "--rcfile", str(ROOT / "scripts" / "coverage.ini"),
               "--branch", "--parallel-mode",
               "--source", str(ROOT / "ai_new" / "modules"),
               "--data-file", str(Path(cov_dir) / ".coverage"),
               "-m", "unittest", mod]
    else:
        cmd = [sys.executable, "-m", "unittest", mod]
    started = time.perf_counter()
    try:
        proc = subprocess.run(cmd, cwd=str(TESTDIR), env=env, text=True,
                              capture_output=True, timeout=timeout)
        out = (proc.stdout or "") + (proc.stderr or "")
        return {"module": mod, "ok": proc.returncode == 0, "code": proc.returncode,
                "seconds": round(time.perf_counter() - started, 2),
                "tail": "\n".join(out.strip().splitlines()[-20:])}
    except subprocess.TimeoutExpired as exc:
        def _txt(v):
            if isinstance(v, bytes):
                return v.decode("utf-8", "replace")
            return v or ""
        out = _txt(exc.stdout) + _txt(exc.stderr)
        return {"module": mod, "ok": False, "code": "timeout",
                "seconds": round(time.perf_counter() - started, 2),
                "tail": "\n".join(str(out).strip().splitlines()[-20:])}
    finally:
        # 每个分片的暂存目录必须回收，否则全量跑会把 /tmp inode 打满。
        shutil.rmtree(workdir, ignore_errors=True)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--jobs", type=int, default=4)
    ap.add_argument("--modules", default="")
    ap.add_argument("--timeout", type=int, default=900)
    ap.add_argument("--base-port", type=int, default=18700)
    ap.add_argument("--coverage", action="store_true",
                    help="每分片 coverage run --parallel-mode，结束后自动 combine")
    ap.add_argument("--coverage-dir", default="")
    ap.add_argument("--coverage-out", default="docs/reports/coverage.json")
    ap.add_argument("--json-out", default="")
    args = ap.parse_args(argv)

    mods = ([x.strip() for x in args.modules.split(",") if x.strip()]
            if args.modules else DEFAULT_MODULES)
    jobs = max(1, min(args.jobs, len(mods)))
    serial = [m for m in mods if m in SERIAL_MODULES]
    parallel = [m for m in mods if m not in SERIAL_MODULES]
    cov_dir = ""
    if args.coverage:
        cov_dir = Path(args.coverage_dir or tempfile.mkdtemp(prefix="hive-cov-"))
        cov_dir.mkdir(parents=True, exist_ok=True)
        for old in cov_dir.glob(".coverage*"):
            old.unlink()
    started = time.perf_counter()
    rows = []

    def emit(row):
        rows.append(row)
        print("%s %-30s %6.2fs  %s" % ("OK  " if row["ok"] else "FAIL",
                                      row["module"], row["seconds"], row["code"]))
        if not row["ok"]:
            print(row["tail"])

    with concurrent.futures.ThreadPoolExecutor(max_workers=min(jobs, max(1, len(parallel)))) as pool:
        futs = {pool.submit(run_one, mod, args.timeout, args.base_port + i * 10, cov_dir): mod
                for i, mod in enumerate(parallel)}
        for fut in concurrent.futures.as_completed(futs):
            emit(fut.result())
    for i, mod in enumerate(serial):
        emit(run_one(mod, args.timeout,
                     args.base_port + (len(parallel) + i) * 10, cov_dir))

    rows.sort(key=lambda r: r["seconds"], reverse=True)
    total = round(time.perf_counter() - started, 2)
    print("\n合计 %d 个模块，%d 失败，墙钟 %.2fs（jobs=%d）"
          % (len(rows), sum(1 for r in rows if not r["ok"]), total, jobs))
    print("最慢 5 个：" + "，".join("%s %.1fs" % (r["module"], r["seconds"]) for r in rows[:5]))
    if cov_dir:
        data = str(cov_dir / ".coverage")
        combine = subprocess.run(
            [sys.executable, "-m", "coverage", "combine",
             "--rcfile", str(ROOT / "scripts" / "coverage.ini"), "--data-file", data],
            cwd=str(ROOT), text=True, capture_output=True)
        if combine.returncode != 0:
            print("coverage combine 失败: %s" % (combine.stdout + combine.stderr))
            return 1
        out = Path(args.coverage_out)
        out.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run([sys.executable, "-m", "coverage", "json",
                        "--rcfile", str(ROOT / "scripts" / "coverage.ini"),
                        "--data-file", data, "--pretty-print", "-o", str(out)],
                       cwd=str(ROOT), check=True)
        print("覆盖率 JSON：%s（%s）" % (out, data))
    if args.json_out:
        Path(args.json_out).write_text(json.dumps(
            {"jobs": jobs, "total_seconds": total, "runs": rows}, ensure_ascii=False, indent=2),
            encoding="utf-8")
    return 0 if all(r["ok"] for r in rows) else 1


if __name__ == "__main__":
    raise SystemExit(main())
