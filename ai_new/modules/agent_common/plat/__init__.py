"""平台适配层：锁 / 本机传输 / 进程信号的 OS 差异收口。

业务模块不再各自 ``import fcntl``/``msvcrt``/``socket fork``；跨平台原语一律问这里。
能力做探测与显式降级：不支持的档位返回结构化 ``unsupported_platform``，导入期不崩、
不冒充已验证。
"""
from __future__ import annotations

from .private import _lock, _net, _proc


def capability():
    """汇总锁 / 传输 / 进程信号三档能力上报。"""
    return {
        "platform": _lock.PLATFORM,
        "lock": _lock.lock_capability(),
        "transport": _net.transport_capability(),
        "proc": _proc.proc_capability(),
    }


class _Plat:
    """ctx.plat 面：把三个私有子模块与汇总能力挂到一起。"""

    def __init__(self):
        self.lock = _lock
        self.net = _net
        self.proc = _proc
        self.capability = capability


def setup(ctx):
    ctx.plat = _Plat()
    ctx.api.register(
        "plat.capability",
        lambda c, p: capability(),
        "平台适配层能力上报（锁/传输/进程信号，按 OS 显式降级）",
        module="plat")
    return True
