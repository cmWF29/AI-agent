"""Agent 循环后端注册表。

架构位置：kernel。它只描述“一个会话怎么跑一轮”，不关心业务。
  * api      ：内核自带 ReactLoop（调 OpenAI 兼容 API + 工具）
  * claude-code：把同一轮交给已有 agent CLI，工作目录相同，产物仍落在工单工作树

业务模块通过 Context 注册后端，Sessions 按会话记录选择后端；新增后端不需要改 Sessions。
"""
from __future__ import annotations


class BackendRegistry:
    def __init__(self):
        self._items = {}

    def register(self, name, backend, label="", description=""):
        if not name:
            raise ValueError("backend name required")
        backend.name = name
        backend.meta = {"name": name, "label": label or name, "description": description}
        self._items[name] = backend
        return backend

    def get(self, name):
        return self._items.get(name)

    def list(self):
        return [dict(getattr(b, "meta", {"name": n})) for n, b in sorted(self._items.items())]

    def has(self, name):
        return name in self._items


class ApiLoopBackend:
    """现有 React 循环的薄适配器；行为与 v4.1 完全一致。"""

    name = "api"
    meta = {"name": "api", "label": "API React 循环", "description": "内核自己调 LLM + 工具"}

    def __init__(self, react):
        self.react = react

    def run(self, session, user_text=None, drain=None, hooks=None, max_steps=None):
        return self.react.run(session=session, user_text=user_text, drain=drain,
                              hooks=hooks, max_steps=max_steps)
