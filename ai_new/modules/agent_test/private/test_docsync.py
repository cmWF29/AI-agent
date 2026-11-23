"""代码-文档同步门禁自测：哈希 + 符号清单双向闭合，时间戳不能蒙混。

覆盖 5 条规则的实测：
- 新增函数漏文档/漏符号 → 红（stale-symbols）；
- 改函数不更新文档 → 红（stale-hash）；
- 只改时间戳不改哈希/符号 → 不能蒙混（哈希仍以源码现算为准）；
- 补全后 → 绿；
- 源码删/改名后旧文档 → 孤儿文档报红。
"""
from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "scripts" / "lib"))


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


GEN = _load("gen_docs", "scripts/gen_docs.py")
GATE = _load("gate_docsync", "scripts/gate_docsync.py")

SRC = "def alpha():\n    return 1\n"
SRC_PLUS = "def alpha():\n    return 1\n\n\ndef beta():\n    return 2\n"
SRC_MUTATED = "def alpha():\n    return 42\n"


class DocsyncGateTest(unittest.TestCase):
    def _make_root(self, src: str) -> Path:
        td = tempfile.mkdtemp()
        root = Path(td)
        mod = root / "ai_new/modules/demo/private"
        mod.mkdir(parents=True)
        (mod / "_pure.py").write_text(src, encoding="utf-8")
        return root

    def test_green_after_generate(self):
        root = self._make_root(SRC)
        GEN.generate(root=root, write=True)
        result = GATE.scan(root=root)
        self.assertEqual([p["kind"] for p in result["problems"]], [])

    def test_new_function_missing_doc_symbol_red(self):
        root = self._make_root(SRC)
        GEN.generate(root=root, write=True)
        (root / "ai_new/modules/demo/private/_pure.py").write_text(SRC_PLUS, encoding="utf-8")
        result = GATE.scan(root=root)
        self.assertIn("stale-symbols", [p["kind"] for p in result["problems"]])

    def test_changed_body_stale_hash_red(self):
        root = self._make_root(SRC)
        GEN.generate(root=root, write=True)
        (root / "ai_new/modules/demo/private/_pure.py").write_text(SRC_MUTATED, encoding="utf-8")
        result = GATE.scan(root=root)
        self.assertIn("stale-hash", [p["kind"] for p in result["problems"]])

    def test_timestamp_bump_cannot_fake_freshness(self):
        import os
        import time
        root = self._make_root(SRC)
        GEN.generate(root=root, write=True)
        doc = GEN._doc_path(root, "ai_new/modules/demo/private/_pure.py")
        # 把文档 mtime 拨到未来：门禁只认哈希 + 符号，不看 mtime，仍应闭合
        future = time.time() + 3600
        os.utime(doc, (future, future))
        result = GATE.scan(root=root)
        self.assertEqual([p["kind"] for p in result["problems"]], [])

    def test_deleted_source_leaves_orphan_doc(self):
        root = self._make_root(SRC)
        GEN.generate(root=root, write=True)
        (root / "ai_new/modules/demo/private/_pure.py").unlink()
        result = GATE.scan(root=root)
        self.assertIn("orphan-doc", [p["kind"] for p in result["problems"]])


if __name__ == "__main__":
    unittest.main()
