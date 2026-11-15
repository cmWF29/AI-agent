"""主机资源能力：内存、磁盘、负载这类"这台机器怎样了"的读数。

guard/health 以前各自 `import shutil`、自己读 `/proc/meminfo` —— 这就是把"机器观测"
这件公共能力塞进业务模块。收编后它们只调 `host.info`。
"""
from __future__ import annotations

from .private import _probe


def setup(ctx):
    ctx.host = _probe
    ctx.api.register("host.info", lambda c, p: _probe.info(c),
                     "内存/磁盘/负载读数", module="host")
    ctx.api.register("host.env", lambda c, p: _probe.env(p.get("name")),
                     "读环境变量", module="host")
    return True


def info(ctx):
    return _probe.info(ctx)
