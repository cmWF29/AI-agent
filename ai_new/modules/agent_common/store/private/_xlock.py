"""跨进程项目锁：POSIX flock / Windows msvcrt.locking 双分支。

进程内临界区见 _doclock；本文件补跨进程 OS 锁档位。锁句柄由执行进程持有，
进程退出后 OS 自动释放（flock 随 fd 关闭释放；msvcrt 锁随句柄关闭释放），
不会出现进程死后锁残留。

做不到的平台在 capability() 里显式标 supported/verified=false，不冒充已支持。
本文件属 store 能力层，允许直接用标准库文件/锁原语。
"""
from __future__ import annotations

import os

if os.name == "nt":  # pragma: nt-cover — Windows 分支不在本机执行
    import msvcrt
else:
    import fcntl


class _CrossProcessLock:
    """项目级跨进程锁上下文管理器。"""

    def __init__(self, handle, path, platform):
        self._fh = handle
        self._path = path
        self._platform = platform
        self._held = False

    def acquire(self):
        if self._platform == "nt":  # pragma: nt-cover
            # msvcrt.locking 锁 1 字节；LK_LOCK 阻塞重试直到拿到
            msvcrt.locking(self._fh.fileno(), msvcrt.LK_LOCK, 1)
        else:
            fcntl.flock(self._fh.fileno(), fcntl.LOCK_EX)
        self._held = True
        return self

    def release(self):
        if not self._held:
            return
        if self._platform == "nt":  # pragma: nt-cover
            msvcrt.locking(self._fh.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            fcntl.flock(self._fh.fileno(), fcntl.LOCK_UN)
        self._held = False
        self._fh.close()

    def __enter__(self):
        return self.acquire()

    def __exit__(self, *_exc):
        self.release()
        return False


def lock_file(path):
    """按路径打开锁文件并返回跨进程锁上下文管理器。

    父目录须已由 store 能力准备好；本函数不创建目录、不写业务数据。
    """
    handle = open(path, "a+b")  # noqa: SIM115 — store 能力层持句柄至释放
    return _CrossProcessLock(handle, path, os.name)


def capability():
    """锁档位上报：跨进程锁机制入口与本机验证状态。"""
    if os.name == "nt":  # pragma: nt-cover
        return {
            "platform": "nt",
            "in_process": {"supported": True, "verified": False},
            "cross_process": {
                "supported": True,
                "verified": False,
                "mechanism": "msvcrt.locking",
                "note": "Windows 跨进程锁分支未在 Windows 实测；verified=false。",
            },
        }
    return {
        "platform": "posix",
        "in_process": {"supported": True, "verified": False},
        "cross_process": {
            "supported": True,
            "verified": True,
            "mechanism": "fcntl.flock",
            "note": "POSIX flock 已在本机靶向单测中验证跨进程互斥。",
        },
    }
