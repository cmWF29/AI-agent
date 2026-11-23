"""共享扫描库：模块/能力/调用关系、函数引用图、前端控件与需求→测试映射。

两道门禁（gate_deadcode / gate_docsync）只消费本库的结构化结果；
上层测试金字塔可复用同一套解析能力。
"""
from __future__ import annotations

from . import demand, js_scan, python_scan  # noqa: F401

__all__ = ["demand", "js_scan", "python_scan"]
