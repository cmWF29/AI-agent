"""组合根模块（不参与装配图）。

它不是被装配的：装配从它开始。识别方式不是标签，而是结构 —— 它是唯一
没有 `setup(ctx)` 的模块，扫描器据此把它从图里剔除，剩下的模块照常排序。

对外只有 main。
"""
from __future__ import annotations

from .private._boot import main
