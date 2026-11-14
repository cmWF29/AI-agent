"""模块装配表 —— 唯一的“组装点”。

模块之间不许互相 import；这里按启动顺序实例化，仅此而已。
加新模块 = 在这里加一行 + 在 modules/ 下加一个文件，内核不用改。
"""
from __future__ import annotations

from .agents import Agents
from .artifacts import Artifacts
from .health import Health
from .idle import Idle
from .gitflow import GitFlow
from .knowledge import Knowledge
from .library import Library
from .lifecycle import Lifecycle
from .memory import Memory
from .observability import Observability
from .ops import Ops
from .projects import Projects
from .sessions import Sessions
from .skills import Skills
from .tickets import Tickets
from .toolpack import ToolPack
from .webchat import WebChat

ORDER = [
    Observability,   # 先起来，好观察后面所有人的事件
    Knowledge,       # 知识层要先能读，秘书/PM 的提示词靠它
    Memory,
    Library,         # 角色库/流程库/技能库：PM 派活前先查这里
    Skills,          # 开源 Skill 安装/来源/拆解（元数据仍写 library.skills）
    Artifacts,       # 三层交付件归档
    Projects,        # 项目是一等公民：工单挂在项目下
    ToolPack,        # 基础执行工具
    Agents,          # 已有 agent 后端（Claude Code 等），注册到 kernel BackendRegistry
    Sessions,        # 会话/agent 管理（按记录选择后端）
    GitFlow,         # 工单级 git（依赖 projects/tickets 的目录约定）
    Tickets,          # 工单（依赖 sessions / projects / library / artifacts / gitflow 的 API）
    Lifecycle,        # 项目生命周期编排：唯一把 projects 与 tickets 拼起来的层
    WebChat,         # 网页对话桥（群聊时间线 + 流式 + 透明化）
    Ops,             # 固定命令 / 版本管理
    Idle,            # 空闲/高峰判断 + 需求排队（工单/消息都往这里问）
    Health,          # 最后挂，确保能检查前面所有人
]


def build_modules(ctx):
    return [cls(ctx) for cls in ORDER]
