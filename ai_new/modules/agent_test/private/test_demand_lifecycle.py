"""需求生命周期门禁自测：入口写需求没有收口、异步交接没有消费者都必须报红。"""
from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]


def _gate():
    spec = importlib.util.spec_from_file_location(
        "gate_demand_lifecycle", ROOT / "scripts" / "gate_demand_lifecycle.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class DemandLifecycleGateTest(unittest.TestCase):
    def _root(self):
        tmp = tempfile.TemporaryDirectory()
        root = Path(tmp.name)
        (root / "ai_new/modules/demo").mkdir(parents=True)
        (root / "ai_new/modules/demo/__init__.py").write_text(
            "ctx.hooks.point('demo.queued', defer=True)\n"
            "ctx.hooks.emit('demo.queued', {})\n", encoding="utf-8")
        demands = root / "ai_new/modules/agent_common/demand_engine/data/demands"
        demands.mkdir(parents=True)
        (demands / "view-demo.yaml").write_text(
            "id: view-demo\nview:\n  key: demo\n  sections:\n  - kind: composer\n"
            "    submit: {demand: demo.intake}\n", encoding="utf-8")
        return tmp, root, demands

    def test_unfinished_entry_is_rejected(self):
        gate = _gate()
        tmp, root, demands = self._root()
        try:
            (demands / "demo.intake.yaml").write_text(
                "id: demo.intake\ntags: [write]\nenabled: true\ncallable: true\n"
                "'on': []\ndo: []\n", encoding="utf-8")
            bad = gate.scan(root)
            self.assertTrue(any("缺少 completion" in x for x in bad))
        finally:
            tmp.cleanup()

    def test_event_without_consumer_is_rejected(self):
        gate = _gate()
        tmp, root, demands = self._root()
        try:
            (demands / "demo.intake.yaml").write_text(
                "id: demo.intake\ntags: [write]\nenabled: true\ncallable: true\n"
                "'on': []\ncompletion: {event: demo.queued, consumer: demo.nope}\n"
                "do: []\n", encoding="utf-8")
            bad = gate.scan(root)
            self.assertTrue(any("消费者不存在" in x for x in bad))
        finally:
            tmp.cleanup()

    def test_queue_semantics_cannot_be_declared_inline(self):
        gate = _gate()
        tmp, root, demands = self._root()
        try:
            (demands / "demo.intake.yaml").write_text(
                "id: demo.intake\ntitle: 消息入队\ntags: [write]\nenabled: true\n"
                "callable: true\ncompletion: inline\n'on': []\ndo: []\n", encoding="utf-8")
            bad = gate.scan(root)
            self.assertTrue(any("队列/异步语义" in x for x in bad))
        finally:
            tmp.cleanup()

    def test_declared_event_and_consumer_pass(self):
        gate = _gate()
        tmp, root, demands = self._root()
        try:
            (demands / "demo.intake.yaml").write_text(
                "id: demo.intake\ntags: [write]\nenabled: true\ncallable: true\n"
                "'on': []\ncompletion: {event: demo.queued, consumer: demo.consume}\n"
                "do: []\n", encoding="utf-8")
            (demands / "demo.consume.yaml").write_text(
                "id: demo.consume\ntags: [write]\nenabled: true\ncallable: false\n"
                "'on': [demo.queued]\ndo:\n- call: demo.flush\n", encoding="utf-8")
            self.assertEqual(gate.scan(root), [])
        finally:
            tmp.cleanup()


if __name__ == "__main__":
    unittest.main()
