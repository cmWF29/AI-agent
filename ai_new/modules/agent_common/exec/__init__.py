"""进程能力：把"跑一个外部程序"收成一处。

平台设施，不认识业务：给 argv、给 stdin、给时限与打断位，交回退出码与输出。
- 不经过 shell（argv 直传），不给命令拼接留口子；
- 运行期轮询打断位：外部 agent 跑得久，用户一打断就 kill；
- 只有它能起进程，其余模块一律经它。
"""
from __future__ import annotations

from .private import _runner


def setup(ctx):
    ctx.api.register("exec.run", _runner.run, "跑外部进程：argv+stdin → 退出码+输出", module="exec")
    return True
