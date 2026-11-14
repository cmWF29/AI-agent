#!/usr/bin/env python3
"""宿主机资源门禁单测：全部用注入的假 probe，不依赖真实机器负载。

跑法：python3 tests/test_hostres.py
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from hive.kernel.hostres import check_host_resources, guard_config  # noqa: E402

HEALTHY = {"cpu_count": 8, "loadavg1": 0.5, "mem_available_mb": 8192, "claude_procs": 0}


def _cfg(**guard):
    return {"agents": {"claude_code": {"guard": guard}}}


def run():
    errors = []

    def expect(name, cond, detail=""):
        if not cond:
            errors.append("%s %s" % (name, detail))

    # 1) 健康机器放行
    r = check_host_resources({}, probe=HEALTHY)
    expect("健康机器放行", r["ok"] and r["action"] == "allow", r)
    expect("放行时 reason 为空", r["reason"] == "", r["reason"])

    # 2) 内存不足 -> reject（默认策略）
    r = check_host_resources({}, probe=dict(HEALTHY, mem_available_mb=512))
    expect("内存不足拒绝", not r["ok"] and r["code"] == "low_mem", r)
    expect("默认策略是 reject", r["action"] == "reject", r["action"])
    expect("拒绝带可读原因", "512" in r["reason"] and "1024" in r["reason"], r["reason"])

    # 3) 负载按核数归一：8 核 9.0 负载 = 1.125/核，未超 1.5
    r = check_host_resources({}, probe=dict(HEALTHY, loadavg1=9.0))
    expect("负载按核数归一后放行", r["ok"], r)
    # 2 核 4.0 负载 = 2.0/核，超限
    r = check_host_resources({}, probe=dict(HEALTHY, cpu_count=2, loadavg1=4.0))
    expect("负载超限拒绝", not r["ok"] and r["code"] == "high_load", r)

    # 4) claude 进程数达到上限
    r = check_host_resources({}, probe=dict(HEALTHY, claude_procs=3))
    expect("进程数达上限拒绝", not r["ok"] and r["code"] == "too_many_procs", r)
    r = check_host_resources({}, probe=dict(HEALTHY, claude_procs=2))
    expect("进程数未达上限放行", r["ok"], r)

    # 5) fallback_api 策略
    r = check_host_resources(_cfg(on_insufficient="fallback_api"),
                             probe=dict(HEALTHY, mem_available_mb=100))
    expect("fallback_api 策略生效", not r["ok"] and r["action"] == "fallback_api", r)

    # 6) 非法策略回落到 reject
    r = check_host_resources(_cfg(on_insufficient="explode"),
                             probe=dict(HEALTHY, mem_available_mb=100))
    expect("非法策略回落 reject", r["action"] == "reject", r["action"])

    # 7) enabled=false 时一律放行
    r = check_host_resources(_cfg(enabled=False), probe=dict(HEALTHY, mem_available_mb=1))
    expect("关闭门禁后放行", r["ok"], r)

    # 8) 阈值可配置
    r = check_host_resources(_cfg(min_free_mem_mb=256), probe=dict(HEALTHY, mem_available_mb=512))
    expect("自定义内存下限生效", r["ok"], r)

    # 9) 探测值未知（None）时 fail-open，不能因为读不到 /proc 就全关
    r = check_host_resources({}, probe={"cpu_count": 4, "loadavg1": None,
                                        "mem_available_mb": None, "claude_procs": None})
    expect("未知探测值放行", r["ok"], r)

    # 10) resources 字段结构（前端/日志要用）
    r = check_host_resources({}, probe=HEALTHY)
    res = r["resources"]
    expect("resources 含 load_ratio", res.get("load_ratio") == round(0.5 / 8, 3), res)
    expect("resources 含 limits", set(res.get("limits", {})) ==
           {"min_free_mem_mb", "max_load_ratio", "max_claude_procs"}, res)

    # 11) guard_config 兼容“整份配置”和“claude_code 段”两种入参
    g1 = guard_config({"agents": {"claude_code": {"guard": {"max_claude_procs": 7}}}})
    g2 = guard_config({"guard": {"max_claude_procs": 7}})
    expect("guard_config 两种入参一致", g1["max_claude_procs"] == g2["max_claude_procs"] == 7,
           (g1, g2))
    expect("guard_config 补齐默认值", g1["min_free_mem_mb"] == 1024, g1)

    return not errors, errors


if __name__ == "__main__":
    ok, errs = run()
    print("PASS" if ok else "FAIL")
    for e in errs:
        print("  -", e)
    sys.exit(0 if ok else 1)
