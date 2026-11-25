"""钩子：点声明冲突、同步/延迟派发、队列上限、runtime 队列与异常留痕。"""
from __future__ import annotations

import asyncio
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))

from ai_new.modules.agent_common.hooks.private import _hooks as h  # noqa: E402


class Engine:
    def __init__(self):
        self.calls = []
        self.fail = False

    def dispatch(self, name, envelope):
        if self.fail:
            raise ValueError("bad")
        self.calls.append(("sync", name, envelope))
        return [{"ok": True}]

    async def adispatch(self, name, envelope):
        if self.fail:
            raise ValueError("bad")
        self.calls.append(("async", name, envelope))
        return [{"ok": True}]


class Runtime:
    def __init__(self):
        self.queued = []
        self.claimed = []
        self.cleared = 0

    def enqueue_hook(self, name, envelope):
        self.queued.append((name, envelope))

    def claim_hooks(self, limit):
        out = self.claimed[:limit]
        del self.claimed[:len(out)]
        return out

    def pending_hooks(self):
        return len(self.claimed)

    def clear_hooks(self):
        self.cleared += 1
        self.claimed.clear()


class Ctx:
    def __init__(self):
        self.runtime = None


class HooksTest(unittest.TestCase):
    def test_point(self):
        hooks = h.Hooks(Ctx(), Engine())
        with self.assertRaises(ValueError):
            hooks.point("bad")
        with self.assertRaises(ValueError):
            hooks.point("x.y", params=("a",))
            hooks.point("x.y", params=("a",))
            hooks.point("x.y", params=("b",))
        with self.assertRaises(ValueError):
            hooks.point("x.y", defer=True)
            hooks.point("x.y")
        hooks.point("x.z", defer=True)
        hooks.point("x.z", defer=True)
        self.assertEqual([p["name"] for p in hooks.points()], ["x.y", "x.z"])

    def test_emit_sync_and_unknown(self):
        eng = Engine()
        hooks = h.Hooks(Ctx(), eng)
        self.assertEqual(hooks.emit("no.such")[0]["error"], "未声明的 hook 点")
        hooks.point("a.b")
        self.assertEqual(hooks.emit("a.b", {"x": 1})[0]["ok"], True)
        self.assertEqual(eng.calls[0][2]["data"], {"x": 1})

    def test_defer_with_runtime_and_limit(self):
        rt = Runtime()
        hooks = h.Hooks(Ctx(), Engine())
        hooks.point("a.d", defer=True)
        hooks.ctx.runtime = rt
        self.assertEqual(hooks.emit("a.d")[0]["deferred"], True)
        self.assertEqual(len(rt.queued), 1)
        self.assertEqual(hooks.pending(), 0)
        hooks.clear()
        self.assertEqual(rt.cleared, 1)

        hooks.ctx.runtime = None
        for _ in range(h.PENDING_LIMIT):
            hooks.emit("a.d")
        self.assertEqual(hooks.emit("a.d")[0]["error"], "延迟队列已满")
        self.assertEqual(hooks.pending(), h.PENDING_LIMIT)
        self.assertEqual(hooks.clear(), h.PENDING_LIMIT)

    def test_drain_and_errors(self):
        eng = Engine()
        hooks = h.Hooks(Ctx(), eng)
        hooks.point("a.d", defer=True)
        hooks.emit("a.d")
        hooks.emit("a.d")
        self.assertEqual(len(hooks.drain(1)), 1)
        eng.fail = True
        self.assertEqual(hooks.drain(), [])
        self.assertEqual(hooks.errors[0]["hook"], "a.d")

    def test_drain_async_and_runtime_claim(self):
        eng = Engine()
        hooks = h.Hooks(Ctx(), eng)
        hooks.point("a.d", defer=True)
        hooks.emit("a.d")
        self.assertEqual(asyncio.run(hooks.drain_async(1)), [{"ok": True}])
        eng.fail = True
        hooks.emit("a.d")
        self.assertEqual(asyncio.run(hooks.drain_async(1)), [])
        self.assertEqual(len(hooks.errors), 1)

        eng.fail = False
        rt = Runtime()
        rt.claimed = [{"hook": "a.d"}]
        hooks.ctx.runtime = rt
        self.assertEqual(hooks.pending(), 1)
        self.assertEqual(asyncio.run(hooks.drain_async(1)), [{"ok": True}])


if __name__ == "__main__":
    unittest.main()
