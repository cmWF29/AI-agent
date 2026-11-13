"""模块装配表 —— 唯一的“组装点”。

模块之间不许互相 import；这里按启动顺序实例化，仅此而已。
加新模块 = 在这里加一行 + 在 modules/ 下加一个文件，内核不用改。
"""
from __future__ import annotations

from .health import Health
from .knowledge import Knowledge
from .memory import Memory
from .observability import Observability
from .ops import Ops
from .projects import Projects
from .sessions import Sessions
from .tickets import Tickets
from .toolpack import ToolPack
from .webchat import WebChat

ORDER = [
    Observability,   # 先起来，好观察后面所有人的事件
    Knowledge,       # 知识层要先能读，秘书/PM 的提示词靠它
    Memory,
    Projects,        # 项目是一等公民：工单挂在项目下
    ToolPack,        # 基础执行工具
    Sessions,        # 会话/agent 管理（注册 agent_* 工具）
    Tickets,         # 工单（依赖 sessions / projects 的 API，不依赖其实现）
    WebChat,         # 网页对话桥（群聊时间线）
    Ops,             # 固定命令 / 版本管理
    Health,          # 最后挂，确保能检查前面所有人
]


def build_modules(ctx):
    return [cls(ctx) for cls in ORDER]
