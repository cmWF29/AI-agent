"""文档级进程内互斥锁：按 realpath 归一登记。

跨进程 / 跨主机的 OS 级锁（posix flock、nt 独占句柄）是待接档位；本文件先
提供进程内临界区原语，供文档读写串行化使用。做不到的档位不在此冒充已支持。
"""
from __future__ import annotations

import threading

_locks = {}
_guard = threading.Lock()


def lock_for(real):
    """按归一后的 realpath 取一把进程内互斥锁。"""
    with _guard:
        return _locks.setdefault(str(real), threading.Lock())


class locked:
    """临界区上下文管理器：``with locked(real): ...``。"""

    def __init__(self, real):
        self._lock = lock_for(real)

    def __enter__(self):
        self._lock.acquire()
        return self

    def __exit__(self, *_exc):
        self._lock.release()
        return False


def lock_capability():
    """文档锁档位上报；跨进程 OS 锁口径与 _xlock 保持一致。"""
    from . import _xlock
    return _xlock.capability()
