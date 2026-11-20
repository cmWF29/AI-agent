"""进程能力：把"跑一个外部程序"收成一处。

平台设施，不认识业务：给 argv、给 stdin、给时限与打断位，交回退出码与输出。
- 不经过 shell（argv 直传），不给命令拼接留口子；
- 运行期轮询打断位：进程跑得久，用户一打断就 kill；
- 只有它能起进程，其余模块一律经它。
"""
from __future__ import annotations

from .private import _runner


async def _route_run(ctx, payload):
    """进程执行走异步轨：阻塞的 subprocess 实现经执行器桥接，不占事件循环线程。"""
    loop = ctx.api._ensure_loop()
    return await loop.run_in_executor(None, _runner.run, ctx, payload)


def setup(ctx):
    ctx.api.register("exec.run", _route_run, "跑外部进程：argv+stdin → 退出码+输出",
                     module="exec", internal=True)
    return True
