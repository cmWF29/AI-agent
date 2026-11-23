"""断言记录助手：纯收集，不抛异常；失败项进失败摘要。

分层用例不直接调 ``unittest.assert*`` 汇总，而是往 :class:`Recorder` 里记账，
这样一层可以一次跑完再统一报红，避免首条失败就中断整层。
"""
from __future__ import annotations

from typing import List

from report import Check


class Recorder:
    def __init__(self) -> None:
        self._checks: List[Check] = []

    def check(self, name: str, ok: bool, detail: str = "") -> None:
        self._checks.append(Check(name, bool(ok), detail))

    def expect(self, name: str, cond: bool, detail: str = "") -> None:
        """语义别名：cond 为真记通过。"""
        self.check(name, cond, detail)

    def equal(self, name: str, actual, expected, detail: str = "") -> None:
        ok = actual == expected
        self.check(name, ok, detail or "实际 %r ≠ 期望 %r" % (actual, expected))

    def truthy(self, name: str, value, detail: str = "") -> None:
        self.check(name, bool(value), detail or "值为假: %r" % (value,))

    def check_true(self, name: str, cond: bool, detail: str = "") -> None:
        self.check(name, cond, detail)

    @property
    def ok(self) -> bool:
        return all(c.ok for c in self._checks)

    @property
    def checks(self) -> List[Check]:
        return list(self._checks)

    def failed(self) -> List[Check]:
        return [c for c in self._checks if not c.ok]
