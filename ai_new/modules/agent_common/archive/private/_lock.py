"""源文件跨进程锁：压缩期间排他持有，避免两个进程压同一文件。

OS 排他锁原语收口到 plat 平台适配层（POSIX ``fcntl.flock`` /
Windows ``msvcrt.locking``）；进程内再叠一把互斥锁，同进程并发压缩串行化。

做不到的档位不冒充已支持：跨进程锁只在对应 OS 上接入，Windows 路径未验证，
capability 里显式标 verified=false。
"""
from __future__ import annotations

import os
import threading

from ai_new.modules.agent_common.plat.private import _lock as plat_lock

_inproc: dict = {}
_guard = threading.Lock()


class source_lock:
    """对源文件持排他锁的上下文管理器。"""

    def __init__(self, path):
        self._path = str(path)
        self._fd = None
        self._oslock = None
        self._in = None

    def __enter__(self):
        with _guard:
            self._in = _inproc.setdefault(self._path, threading.Lock())
        self._in.acquire()
        if plat_lock.PLATFORM == "nt":
            self._fd = os.open(self._path, os.O_RDWR | os.O_BINARY)
        else:
            self._fd = os.open(self._path, os.O_RDONLY)
        try:
            self._oslock = plat_lock.ExclusiveLock(self._fd, path=self._path)
            self._oslock.acquire()
        except OSError:
            os.close(self._fd)
            self._fd = None
            self._in.release()
            raise
        return self

    def __exit__(self, *_exc):
        try:
            if self._oslock is not None:
                self._oslock.release()
        finally:
            if self._fd is not None:
                os.close(self._fd)
                self._fd = None
            self._oslock = None
            self._in.release()
        return False


def lock_capability():
    """锁档位上报：进程内锁具备；跨进程 OS 锁按 OS 分支接入，均未在对端验证。"""
    base = plat_lock.lock_capability()
    cross = dict(base["cross_process"])
    # 归档锁未在跨进程场景单独实测：覆盖 verified 与说明，不冒充已验证。
    cross["verified"] = False
    if plat_lock.PLATFORM == "nt":
        cross["mechanism"] = "msvcrt.locking 排他句柄锁"
        cross["note"] = "Windows 跨进程锁分支未在 Windows 实测验证。"
    else:
        cross["mechanism"] = "fcntl.flock 排他锁"
        cross["note"] = "posix flock 已接入压缩路径；未在跨进程场景实测。"
    return {"in_process": dict(base["in_process"]), "cross_process": cross}
