"""时间能力：现在几点、睡多久、把时间戳和文本互相换。

时钟是外界（它自己会走，模块管不了它）。以前 `health` 算 uptime、`channel` 打 ts、
`tickets` 判停滞、`sessions` 等超时，各自 `import time`/`datetime` —— 同一个"现在"
被十几个模块各拿一份。收编后只在这里读一次，别处一律问 `clock.*`。
"""
from __future__ import annotations

from .private import _clock


def setup(ctx):
    ctx.clock = _clock
    return _clock.setup(ctx)
