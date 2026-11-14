"""模块装配表 —— 唯一的“组装点”。

模块之间不许互相 import；这里按启动顺序实例化，仅此而已。
新增模块 = 在 modules/ 下加一个目录 + 在 MODULE_SPECS 加一行；
移除模块 = 删除目录即可，装配器会跳过缺失目录，不需要改其他业务模块。
"""
from __future__ import annotations

import importlib

MODULE_SPECS = [
    ("observability", "Observability"),   # 先起来，好观察后面所有人的事件
    ("knowledge", "Knowledge"),           # 知识层要先能读，秘书/PM 的提示词靠它
    ("memory", "Memory"),
    ("library", "Library"),               # 角色库/流程库/技能库：PM 派活前先查这里
    ("skills", "Skills"),                 # 开源 Skill 安装/来源/拆解（元数据仍写 library.skills）
    ("artifacts", "Artifacts"),           # 三层交付件归档
    ("projects", "Projects"),             # 项目是一等公民：工单挂在项目下
    ("toolpack", "ToolPack"),             # 基础执行工具
    ("agents", "Agents"),                 # 已有 agent 后端（Claude Code 等）
    ("sessions", "Sessions"),             # 会话/agent 管理（按记录选择后端）
    ("gitflow", "GitFlow"),               # 工单级 git（依赖 projects/tickets 的目录约定）
    ("tickets", "Tickets"),               # 工单
    ("lifecycle", "Lifecycle"),           # 项目生命周期编排
    ("webchat", "WebChat"),               # 网页对话桥
    ("idle", "Idle"),                     # 空闲/高峰判断 + 需求排队
    ("archgate", "ArchGate"),             # 架构门禁
    ("testrunner", "TestRunner"),         # 回归测试编排
    ("gitsync", "GitSync"),               # 仓库状态与 fetch
    ("ops", "Ops"),                       # 固定命令 / 版本管理（非核心，可移除）
    ("health", "Health"),                 # 最后挂，确保能检查前面所有人
    ("rules", "Rules"),                   # 业务规则/流程层：模块关系的唯一来源
]


def build_modules(ctx):
    modules = []
    for dirname, clsname in MODULE_SPECS:
        try:
            pkg = importlib.import_module("." + dirname, __name__)
            cls = getattr(pkg, clsname)
        except (ImportError, AttributeError):
            # 可插拔：目录被删除时不阻断其他模块启动。
            continue
        modules.append(cls(ctx))
    return modules
