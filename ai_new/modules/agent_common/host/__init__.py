"""主机资源能力：内存、磁盘、负载这类"这台机器怎样了"的读数。

health 以前自己 `import shutil`、读 `/proc/meminfo` —— 这就是把"机器观测"
这件公共能力塞进业务模块。收编后只调 `host.info`。
"""
from __future__ import annotations

from .private import _probe


def setup(ctx):
    ctx.host = _probe
    ctx.api.register("host.info", lambda c, p: _probe.info(c),
                     "内存/磁盘/负载读数", module="host")
    ctx.api.register("host.which", lambda c, p: _probe.which(c, p),
                     "探测 CLI 命令是否在 PATH", module="host")
    ctx.api.register("host.importable", lambda c, p: _probe.importable(c, p),
                     "探测 Python 包当前解释器可否导入", module="host")
    ctx.api.register("host.env", lambda c, p: _probe.env((p or {}).get("name")),
                     "读一个环境变量", module="host")
    ctx.api.register("host.executable", lambda c, p: _probe.executable(c),
                     "当前 Python 解释器路径", module="host")
    return True


def info(ctx):
    return _probe.info(ctx)
