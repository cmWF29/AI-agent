"""模块共享上下文（组合根的私有件）。

只有组合根会构造它；模块只是把它当参数收着，谁都不 import 它。
放在这里是因为它是"装配者的工具"，不是模块之间的共享件。

Context 只做两件事：
1. 装配期接线板 —— 各模块 setup 时把自己的面装上来（api/ApiError/hooks/tools/
   react/llm/http/storage），彼此不 import；
2. 给模块一个共同根：root 路径、merged cfg、已装配模块名。

它不实现任何存储、不定义错误类型、不含业务，也**不提供日志**：记日志是运维的
业务，模块想留下痕迹只能在自己的 hook 点上 emit，由运维模块按 rules 订阅。
ctx 上有哪些面、谁提供的，不需要声明：某个模块在 setup 里写 `ctx.X = ...`，
它就是 X 的提供方；组合根扫描这些赋值点后按依赖图装配。
"""
from __future__ import annotations

from pathlib import Path


class Context:
    def __init__(self, root: Path):
        self.root = Path(root)
        self.cfg = {}
        self.api = None      # api 模块装填
        self.ApiError = None  # api 模块装填
        self.hooks = None    # hooks 模块装填
        self.tools = None    # tools 模块装填
        self.loaded = {}     # module name -> module object
