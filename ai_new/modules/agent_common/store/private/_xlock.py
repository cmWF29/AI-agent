"""跨进程项目锁：原语收口到 plat 平台适配层（POSIX flock / Windows msvcrt）。

进程内临界区见 _doclock；本文件补跨进程 OS 锁档位。锁句柄由执行进程持有，
进程退出后 OS 自动释放，不会出现进程死后锁残留。

做不到的平台在 capability() 里显式标 supported/verified=false，不冒充已支持。
"""
from __future__ import annotations

from ai_new.modules.agent_common.plat.private import _lock as plat_lock


def lock_file(path):
    """按路径打开锁文件并返回跨进程锁上下文管理器。

    父目录须已由 store 能力准备好；本函数不创建目录、不写业务数据。
    """
    return plat_lock.lock_file(path)


def capability():
    """锁档位上报：跨进程锁机制入口与本机验证状态。"""
    return plat_lock.lock_capability()
