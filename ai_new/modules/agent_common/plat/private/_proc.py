"""进程/信号的平台适配：fork 语义、停止信号在 POSIX 与 Windows 的差异收口。

- fork：仅 POSIX；Windows 报 ``unsupported_platform``，调用方走 subprocess 路径。
- 停止信号：POSIX 注册 SIGINT/SIGTERM；Windows 只注册 SIGINT（SIGTERM 经
  TerminateProcess 直达进程，不跑 Python 处理器）。

所有探测结果结构化返回；导入期不碰信号原语，平台缺失不崩装配。
"""
from __future__ import annotations

import os

PLATFORM = "nt" if os.name == "nt" else "posix"


def proc_capability():
    """进程/信号档位上报；不支持的能力显式标 supported=false 与降级码。"""
    return {
        "ok": True,
        "platform": PLATFORM,
        "fork": {
            "supported": PLATFORM != "nt",
            "code": "" if PLATFORM != "nt" else "unsupported_platform",
            "note": "Windows 无 os.fork；子进程走 subprocess。" if PLATFORM == "nt"
                    else "POSIX 可 os.fork。",
        },
        "stop_signals": {
            "posix": ["SIGINT", "SIGTERM"],
            "windows": ["SIGINT"],
        },
    }


def supports_fork():
    return PLATFORM != "nt"


def install_stop_handler(handler):
    """注册优雅关停处理器；返回 ``{ok, installed, unsupported}``。

    处理器签名固定为 ``handler(signum, frame)``。装不上的信号进 unsupported，
    不抛异常掀翻装配。
    """
    import signal
    installed, unsupported = [], []
    if PLATFORM == "nt":
        # Windows 只对 SIGINT 跑 Python 处理器；SIGTERM 走 TerminateProcess。
        try:
            signal.signal(signal.SIGINT, handler)
            installed.append("SIGINT")
        except (OSError, ValueError):
            unsupported.append("SIGINT")
        unsupported.append("SIGTERM")
    else:
        for name, signum in (("SIGINT", signal.SIGINT),
                              ("SIGTERM", signal.SIGTERM)):
            try:
                signal.signal(signum, handler)
                installed.append(name)
            except (OSError, ValueError):
                unsupported.append(name)
    return {"ok": bool(installed), "installed": installed,
            "unsupported": unsupported}
