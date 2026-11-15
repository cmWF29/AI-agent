"""统一错误类型。由 api 模块装配到 ctx.ApiError，http 模块负责转成 JSON 响应。"""
from __future__ import annotations


class ApiError(Exception):
    """跨模块统一错误。"""

    def __init__(self, message, code="error", status=400, payload=None):
        super().__init__(message)
        self.message = message
        self.code = code
        self.status = status
        self.payload = payload
