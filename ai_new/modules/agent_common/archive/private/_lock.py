"""源文件跨进程锁：压缩期间排他持有，避免两个进程压同一文件。

- Linux/macOS：``fcntl.flock`` 排他锁；
- Windows：``msvcrt.locking`` 排他句柄锁分支（本机未在 Windows 实测，档位上报标未验证）；
- 进程内再叠一把互斥锁，同进程并发压缩串行化。

做不到的档位不冒充已支持：跨进程锁只在对应 OS 上接入，Windows 路径未验证。
"""
from __future__ import annotations

import os
import threading

_inproc: dict = {}
_guard = threading.Lock()


class source_lock:
    """对源文件持排他锁的上下文管理器。"""

    def __init__(self, path):
        self._path = str(path)
        self._fd = None
        self._in = None

    def __enter__(self):
        with _guard:
            self._in = _inproc.setdefault(self._path, threading.Lock())
        self._in.acquire()
        if os.name == "nt":
            import msvcrt
            self._fd = os.open(self._path, os.O_RDWR)
            try:
                msvcrt.locking(self._fd, msvcrt.LK_LOCK, 1)
            except OSError:
                os.close(self._fd)
                self._in.release()
                raise
        else:
            import fcntl
            self._fd = os.open(self._path, os.O_RDONLY)
            fcntl.flock(self._fd, fcntl.LOCK_EX)
        return self

    def __exit__(self, *_exc):
        try:
            if self._fd is not None:
                if os.name == "nt":
                    import msvcrt
                    msvcrt.locking(self._fd, msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(self._fd, fcntl.LOCK_UN)
        finally:
            if self._fd is not None:
                os.close(self._fd)
                self._fd = None
            self._in.release()
        return False


def lock_capability():
    """锁档位上报：进程内锁具备；跨进程 OS 锁按 OS 分支接入，均未在对端验证。"""
    if os.name == "nt":
        return {
            "in_process": {"supported": True, "verified": False},
            "cross_process": {
                "supported": True,
                "verified": False,
                "mechanism": "msvcrt.locking 排他句柄锁",
                "note": "Windows 跨进程锁分支未在 Windows 实测验证。",
            },
        }
    return {
        "in_process": {"supported": True, "verified": False},
        "cross_process": {
            "supported": True,
            "verified": False,
            "mechanism": "fcntl.flock 排他锁",
            "note": "posix flock 已接入压缩路径；未在跨进程场景实测。",
        },
    }
