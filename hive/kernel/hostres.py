"""宿主机资源门禁：在把一轮任务交给“已有 agent 进程”之前先看本机还剩多少。

为什么放在 kernel：它只描述“这台机器现在能不能再起一个重进程”，
不关心业务，也不关心是哪个后端；agents 模块只是它的调用方。

设计要点：
- 探测与判定分离。`probe_host()` 负责读 /proc、ps、os 等真实数据；
  `check_host_resources(cfg, probe=None)` 是纯函数，probe 可注入假数据，
  单测不需要真的把机器压满。
- 判定只做“够不够”，不做“要不要降级”。降级策略由调用方按
  `agents.claude_code.guard.on_insufficient` 决定（reject / fallback_api）。
- 任何探测失败都按“未知”处理并放行（fail-open）：门禁是为了避免把机器
  打爆，不是为了在容器里因为读不到 /proc 就把功能全关掉。
"""
from __future__ import annotations

import os
import shutil
import subprocess

DEFAULTS = {
    "enabled": True,
    "min_free_mem_mb": 1024,
    "max_load_ratio": 1.5,
    "max_claude_procs": 3,
    "on_insufficient": "reject",
}

VALID_ACTIONS = ("reject", "fallback_api")


def guard_config(cfg):
    """从整份配置里取出 guard 段，并补齐默认值。

    cfg 可以是整份配置，也可以是 agents.claude_code 段本身（方便单测）。
    """
    if not isinstance(cfg, dict):
        cfg = {}
    agents = cfg.get("agents") if isinstance(cfg.get("agents"), dict) else None
    if agents is not None:
        cc = agents.get("claude_code") if isinstance(agents.get("claude_code"), dict) else {}
    elif "guard" in cfg or "command" in cfg:
        cc = cfg
    else:
        cc = {}
    raw = cc.get("guard") if isinstance(cc.get("guard"), dict) else {}
    out = dict(DEFAULTS)
    for key in DEFAULTS:
        if key in raw and raw[key] is not None:
            out[key] = raw[key]
    out["enabled"] = bool(out["enabled"])
    try:
        out["min_free_mem_mb"] = int(out["min_free_mem_mb"])
    except (TypeError, ValueError):
        out["min_free_mem_mb"] = DEFAULTS["min_free_mem_mb"]
    try:
        out["max_load_ratio"] = float(out["max_load_ratio"])
    except (TypeError, ValueError):
        out["max_load_ratio"] = DEFAULTS["max_load_ratio"]
    try:
        out["max_claude_procs"] = int(out["max_claude_procs"])
    except (TypeError, ValueError):
        out["max_claude_procs"] = DEFAULTS["max_claude_procs"]
    if out["on_insufficient"] not in VALID_ACTIONS:
        out["on_insufficient"] = DEFAULTS["on_insufficient"]
    return out


def _read_mem_available_mb():
    """Linux 优先读 /proc/meminfo 的 MemAvailable（比 free 更准）。"""
    try:
        with open("/proc/meminfo", "r", encoding="utf-8") as f:
            for line in f:
                if line.startswith("MemAvailable:"):
                    kb = int(line.split()[1])
                    return kb / 1024.0
    except (OSError, ValueError, IndexError):
        pass
    return None


def _read_mem_total_mb():
    try:
        with open("/proc/meminfo", "r", encoding="utf-8") as f:
            for line in f:
                if line.startswith("MemTotal:"):
                    return int(line.split()[1]) / 1024.0
    except (OSError, ValueError, IndexError):
        pass
    return None


def _count_claude_procs():
    """数本机正在跑的 claude 进程（含 npm 包装的 node 进程）。

    用 ps 而不是 /proc 遍历，是为了 macOS 也能用；ps 不可用时返回 None（未知）。
    """
    exe = shutil.which("ps")
    if not exe:
        return None
    try:
        p = subprocess.run([exe, "-A", "-o", "command="], capture_output=True,
                           text=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return None
    if p.returncode != 0:
        return None
    n = 0
    for line in (p.stdout or "").splitlines():
        cmd = line.strip()
        if not cmd:
            continue
        # 只认“可执行名是 claude”或“node .../claude”这类，避免把
        # 命令行里恰好带 claude 字样的 shell/grep 也算进去。
        head = cmd.split()[0].rsplit("/", 1)[-1].rsplit("\\", 1)[-1].lower()
        if head in ("claude", "claude.exe", "claude.cmd"):
            n += 1
            continue
        if head in ("node", "node.exe") and "claude" in cmd.lower():
            n += 1
    return n


def probe_host():
    """真实探测。返回的字段缺失（None）表示“未知”，判定时按放行处理。"""
    try:
        cpu = os.cpu_count() or 1
    except Exception:
        cpu = 1
    load = None
    try:
        load = float(os.getloadavg()[0])
    except (OSError, AttributeError, ValueError):
        load = None
    return {
        "cpu_count": cpu,
        "loadavg1": load,
        "mem_available_mb": _read_mem_available_mb(),
        "mem_total_mb": _read_mem_total_mb(),
        "claude_procs": _count_claude_procs(),
    }


def check_host_resources(cfg, probe=None):
    """判定本机是否还有余量再起一个 agent 进程。

    返回 dict：
      ok        : bool，True 表示可以起
      action    : "allow" / "reject" / "fallback_api"
      reason    : 人类可读原因（ok 时为空串）
      code      : 机器可读原因码（ok 时为空串）
      resources : 本次判定用到的探测值 + 阈值，便于前端/日志展示
      guard     : 生效的 guard 配置
    """
    guard = guard_config(cfg)
    data = dict(probe_host() if probe is None else probe)
    cpu = data.get("cpu_count") or 1
    try:
        cpu = int(cpu)
    except (TypeError, ValueError):
        cpu = 1
    if cpu <= 0:
        cpu = 1
    load = data.get("loadavg1")
    mem = data.get("mem_available_mb")
    procs = data.get("claude_procs")

    resources = {
        "cpu_count": cpu,
        "loadavg1": load,
        "load_ratio": (round(float(load) / cpu, 3) if load is not None else None),
        "mem_available_mb": (round(float(mem), 1) if mem is not None else None),
        "claude_procs": procs,
        "limits": {
            "min_free_mem_mb": guard["min_free_mem_mb"],
            "max_load_ratio": guard["max_load_ratio"],
            "max_claude_procs": guard["max_claude_procs"],
        },
    }

    def result(ok, code="", reason=""):
        action = "allow"
        if not ok:
            action = guard["on_insufficient"]
        return {"ok": ok, "action": action, "code": code, "reason": reason,
                "resources": resources, "guard": guard}

    if not guard["enabled"]:
        return result(True)

    # 1) 空闲内存
    if mem is not None and float(mem) < guard["min_free_mem_mb"]:
        return result(False, "low_mem",
                      "可用内存 %.0fMB 低于下限 %dMB" % (float(mem), guard["min_free_mem_mb"]))
    # 2) 负载（按核数归一）
    if load is not None:
        ratio = float(load) / cpu
        if ratio > guard["max_load_ratio"]:
            return result(False, "high_load",
                          "1 分钟负载 %.2f（%.2f/核）超过上限 %.2f/核" % (
                              float(load), ratio, guard["max_load_ratio"]))
    # 3) 已有 claude 进程数
    if procs is not None and int(procs) >= guard["max_claude_procs"]:
        return result(False, "too_many_procs",
                      "已有 %d 个 claude 进程，达到上限 %d" % (
                          int(procs), guard["max_claude_procs"]))
    return result(True)
