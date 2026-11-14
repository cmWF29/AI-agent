"""library 模块入口：只导出模块类，内部实现在 module.py。"""
from .module import Library

__all__ = ["Library"]

from .module import BUILTIN_ROLES, BUILTIN_FLOWS, REQUIREMENT_FLOWS
__all__ += ["BUILTIN_ROLES", "BUILTIN_FLOWS", "REQUIREMENT_FLOWS"]
