"""store 面板与数据路由：路径推导、文本/字节读写、CAS、修订、遍历与删除。"""
from __future__ import annotations

import base64
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))

from ai_new.modules.agent_common.store import _panel  # noqa: E402


class ApiError(Exception):
    def __init__(self, message, code="bad", status=400):
        super().__init__(message)
        self.code = code
        self.status = status


class Codec:
    fail_encode = False

    def json_decode(self, text):
        try:
            return {"ok": True, "value": json.loads(text)}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def json_encode(self, obj):
        if self.fail_encode:
            return {"ok": False, "error": "encode"}
        return {"ok": True, "text": json.dumps(obj)}

    yaml_decode = json_decode

    def yaml_encode(self, obj):
        return self.json_encode(obj)


class Ctx:
    ApiError = ApiError

    def __init__(self, root):
        self.root = Path(root)
        self.cfg = {}
        self.codec = Codec()
        self.clock = self
        self.api = self
        self.registered = []
        self.archive = {}
        self.seq = 0

    def register(self, name, fn, desc=None, module=None):
        self.registered.append((name, fn))

    def call(self, name, payload=None, caller=None):
        payload = payload or {}
        if name == "clock.now":
            return {"ts": 1000, "iso": "T"}
        if name == "archive.resolve_abs":
            out = self.archive.get(payload["abs"])
            return {"exists": out is not None, "raw": out or b""}
        raise AssertionError(name)

    def now(self):
        return {"ts": 1000, "iso": "T"}


class PanelTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.old = os.environ.get("AI_NEW_DATA")
        os.environ["AI_NEW_DATA"] = str(self.root / "data")
        self.ctx = Ctx(self.root)
        _panel.setup(self.ctx)
        self.md = self.ctx.storage.own(__file__)

    def tearDown(self):
        if self.old is None:
            os.environ.pop("AI_NEW_DATA", None)
        else:
            os.environ["AI_NEW_DATA"] = self.old
        self.tmp.cleanup()

    def test_setup_and_helpers(self):
        self.assertTrue(any(n == "store.cas" for n, _ in self.ctx.registered))
        other = Ctx(self.root / "preset")
        other.data_root = self.root / "preset" / "dri"
        _panel.setup(other)
        self.assertEqual(other.data_root, self.root / "preset" / "dri")
        self.assertEqual(self.ctx.storage.safe_id("a b"), "a-b")
        self.assertEqual(self.ctx.storage.now_iso(), "T")
        self.assertEqual(self.ctx.storage.next_seq("b", 3), 4)
        self.assertEqual(self.ctx.storage.next_seq("b", 0), 5)
        self.assertEqual(self.ctx.storage.path("k", "rel/x"), Path(self.ctx.root) / "rel/x")
        self.assertEqual(self.ctx.storage.path("k", "/abs/x"), Path("/abs/x"))
        self.assertEqual(_panel._dir_of("agent/knowledge"), self.root / "data" / "agent" / "knowledge")
        self.assertEqual(_panel.ModuleData._meta_rel("a"), "a.meta.yaml")
        with self.assertRaises(ValueError):
            _panel.modules_root("/tmp/no-modules")
        old = os.environ.pop("AI_NEW_DATA")
        try:
            self.assertEqual(_panel._dir_of("agent/knowledge").name, "data")
            self.assertTrue(str(_panel.module_data(__file__)).endswith("data"))
        finally:
            os.environ["AI_NEW_DATA"] = old
        self.assertEqual(_panel._route_id({"value": "a b"}), {"id": "a-b"})
        self.assertEqual(_panel._route_next_seq(self.ctx, {"bucket": "b", "baseline": 5})["seq"], 6)
        self.assertTrue(_panel._route_doc_lock_capability(self.ctx, {})["in_process"]["supported"])

    def test_module_data_basics(self):
        self.assertEqual(self.md.dir(), self.md.root)
        self.assertEqual(self.md.dir("sub"), self.md.root / "sub")
        self.assertEqual(self.md.path("a/b.txt"), self.md.root / "a" / "b.txt")
        self.assertEqual(self.md.json_read("none", default={"x": 1}), {"x": 1})
        self.md.json_write("a.json", {"x": 1})
        self.assertEqual(self.md.json_read("a.json"), {"x": 1})
        self.assertEqual(self.md.yaml_read("none", default={"y": 1}), {"y": 1})
        self.md.yaml_write("a.yaml", {"y": 1})
        self.assertEqual(self.md.yaml_read("a.yaml"), {"y": 1})
        self.assertEqual(self.md.read_text("none"), None)
        self.md.write_text("direct.txt", "d")
        self.assertEqual(self.md.read_text("direct.txt"), "d")
        listing = self.md.list_dir()
        self.assertIn("a.json", listing)
        self.assertIn("a.yaml", listing)
        self.assertEqual(self.md.list_dir("nope"), [])
        self.assertTrue(self.md.exists("a.json"))
        self.assertFalse(self.md.is_dir("a.json"))
        self.assertEqual(self.md.stat_size("none"), 0)
        self.assertEqual(self.md.stat_mtime("none"), 0.0)
        self.assertEqual(self.md.glob("*.json"), ["a.json"])
        self.assertEqual(self.md.walk(pattern="*.json"), ["a.json"])
        self.assertEqual(self.md.walk("nope"), [])
        self.assertTrue(self.md.stat_mtime("a.json") > 0)
        (self.md.root / "sys").mkdir()
        self.assertIn("sys", self.md.dirs())
        self.assertEqual(self.md.dirs("nope"), [])
        self.assertEqual(self.md.remove("none"), False)
        self.assertTrue(self.md.remove("a.json"))
        with self.assertRaises(ValueError):
            self.md.remove("sys")
        self.assertTrue(self.md.remove("sys", recursive=True))

    def test_module_data_codec_failures_and_bytes(self):
        self.ctx.codec.fail_encode = True
        with self.assertRaises(ValueError):
            self.md.json_write("x.json", {})
        with self.assertRaises(ValueError):
            self.md.yaml_write("x.yaml", {})
        self.ctx.codec.fail_encode = False
        self.md.write_bytes("b.bin", b"xy")
        self.assertEqual(self.md.read_bytes("b.bin"), b"xy")
        (self.md.root / "bad.yaml").write_text("{bad")
        self.assertEqual(self.md.yaml_read("bad.yaml", default="d"), "d")

    def test_route_read_write_cas_and_remove(self):
        with self.assertRaises(ApiError) as e:
            _panel._route_read(self.ctx, {"module": "m", "path": "../x"})
        self.assertEqual(e.exception.code, "traversal")
        self.assertEqual(_panel._route_exists(self.ctx, {"module": "m", "path": "a.yaml"}),
                         {"exists": False})
        self.assertEqual(_panel._route_read(self.ctx, {"module": "m", "path": "a.yaml",
                                                       "fallback": "F"}),
                         {"value": "F", "exists": False})
        _panel._route_write(self.ctx, {"module": "m", "path": "a.yaml", "value": {"a": 1}})
        self.assertEqual(_panel._route_read(self.ctx, {"module": "m", "path": "a.yaml"})["value"],
                         {"a": 1})
        (self.root / "data/m/bad.yaml").write_text("{bad")
        self.assertTrue(_panel._route_read(self.ctx, {"module": "m", "path": "bad.yaml"})["bad"])
        self.ctx.codec.fail_encode = True
        with self.assertRaises(ValueError):
            _panel._route_write(self.ctx, {"module": "m", "path": "b.yaml", "value": 1})
        with self.assertRaises(ValueError):
            _panel._route_cas(self.ctx, {"module": "m", "path": "b2.yaml", "value": 1})
        self.ctx.codec.fail_encode = False
        self.assertEqual(_panel._route_cas(self.ctx, {"module": "m", "path": "c.yaml",
                                                      "expected": None, "value": {"x": 1}})["ok"],
                         True)
        self.assertEqual(_panel._route_cas(self.ctx, {"module": "m", "path": "c.yaml",
                                                      "expected": None, "value": {"x": 2}})["code"],
                         "conflict")
        self.assertEqual(_panel._route_cas(self.ctx, {"module": "m", "path": "c.yaml",
                                                      "value": {"x": 3}})["ok"], True)
        (self.root / "data/m/d.yaml").write_text("{bad")
        self.assertEqual(_panel._route_cas(self.ctx, {"module": "m", "path": "d.yaml",
                                                      "value": 1})["code"], "decode_error")
        self.assertEqual(_panel._route_cas(self.ctx, {"module": "m", "path": "e.yaml",
                                                      "expected": None, "create": True,
                                                      "value": 1})["ok"], True)
        self.assertEqual(_panel._route_remove(self.ctx, {"module": "m", "path": "a.yaml"}),
                         {"removed": True})
        self.assertEqual(_panel._route_remove(self.ctx, {"module": "m", "path": "a.yaml"}),
                         {"removed": False})

    def test_routes_glob_walk_text_bytes(self):
        (self.root / "data/m/tree/sub").mkdir(parents=True)
        (self.root / "data/m/tree/a.yaml").write_text('{"id": "a"}')
        (self.root / "data/m/tree/b.yaml").write_text("{bad")
        (self.root / "data/m/tree/sub/c.yaml").write_text('{"id": "c"}')
        (self.root / "data/m/tree/note.md").write_text("hello")
        self.assertEqual(_panel._route_glob(self.ctx, {"module": "m", "root": "none"})["items"],
                         [])
        self.assertEqual(_panel._route_glob(self.ctx, {"module": "m", "root": "tree",
                                                       "pattern": "**"})["items"],
                         ["a.yaml", "b.yaml", "note.md", "sub/c.yaml"])
        self.assertEqual(_panel._route_glob(self.ctx, {"module": "m", "root": "tree",
                                                       "pattern": "*.yaml"})["items"],
                         ["a.yaml", "b.yaml"])
        self.assertEqual(_panel._route_walk(self.ctx, {"module": "m", "root": "none"})["rows"], [])
        _panel._route_walk(self.ctx, {"module": "m", "root": "tree", "pattern": "*"})
        rows = _panel._route_walk(self.ctx, {"module": "m", "root": "tree",
                                             "pattern": "**/*.yaml"})["rows"]
        self.assertEqual(rows, [{"id": "a"}, {"id": "c"}])
        text = _panel._route_walk_text(self.ctx, {"module": "m", "root": "tree"})["rows"]
        self.assertEqual(text, [{"path": "note.md", "text": "hello"}])
        self.assertEqual(_panel._route_walk_text(self.ctx, {"module": "m", "root": "none"})["rows"],
                         [])
        _panel._route_walk_text(self.ctx, {"module": "m", "root": "tree", "pattern": "*"})
        self.assertEqual(_panel._route_read_text(self.ctx, {"module": "m", "path": "none",
                                                            "fallback": "F"}),
                         {"value": "F", "exists": False})
        self.assertEqual(_panel._route_read_text(self.ctx, {"module": "m", "path": "tree/note.md"}),
                         {"value": "hello", "exists": True})
        self.assertEqual(_panel._route_read_bytes(self.ctx, {"module": "m", "path": "none"})["size"],
                         0)
        out = _panel._route_write_bytes(self.ctx, {"module": "m", "path": "x.bin",
                                                   "hex": "7879"})
        self.assertEqual(out["bytes"], 2)
        self.assertEqual(Path(out["path"]).read_bytes(), b"xy")
        out2 = _panel._route_write_bytes(self.ctx, {"module": "m", "path": "y.bin",
                                                    "value": base64.b64encode(b"z").decode()})
        self.assertEqual(Path(out2["path"]).read_bytes(), b"z")
        self.assertEqual(_panel._route_read_bytes(self.ctx, {"module": "m", "path": "y.bin"})["value"],
                         base64.b64encode(b"z").decode())

    def test_text_locks_revision_remove_dir_archive(self):
        self.assertEqual(_panel._route_write_text(self.ctx, {"module": "m", "path": "doc.txt",
                                                             "text": "a"})["written"], True)
        self.assertEqual(_panel._route_append_text(self.ctx, {"module": "m", "path": "doc.txt",
                                                              "text": "b"})["appended"], True)
        self.assertEqual((self.root / "data/m/doc.txt").read_text(), "ab")
        bad_new = _panel._route_doc_revision(self.ctx, {"module": "m", "path": "new.md",
                                                        "text": "x", "author": "u",
                                                        "version": 1})
        self.assertEqual(bad_new["code"], "conflict")
        new = _panel._route_doc_revision(self.ctx, {"module": "m", "path": "doc.md", "text": "x",
                                                    "author": "u"})
        self.assertTrue(new["ok"])
        need = _panel._route_doc_revision(self.ctx, {"module": "m", "path": "doc.md",
                                                     "text": "y", "author": "u"})
        self.assertEqual(need["code"], "token_required")
        conflict = _panel._route_doc_revision(self.ctx, {"module": "m", "path": "doc.md",
                                                         "text": "y", "author": "u",
                                                         "version": 99})
        self.assertEqual(conflict["code"], "conflict")
        forced = _panel._route_doc_revision(self.ctx, {"module": "m", "path": "doc.md",
                                                       "text": "z", "author": "u", "force": True})
        self.assertTrue(forced["ok"])
        appended = _panel._route_doc_revision(self.ctx, {"module": "m", "path": "doc.md",
                                                        "text": "w", "author": "u",
                                                        "version": forced["version"],
                                                        "mode": "append"})
        self.assertTrue(appended["ok"])
        (self.root / "data/m/deldir").mkdir()
        self.assertEqual(_panel._route_remove_dir(self.ctx, {"module": "m", "path": "deldir"}),
                         {"removed": True})
        self.assertEqual(_panel._route_remove_dir(self.ctx, {"module": "m", "path": "deldir"}),
                         {"removed": False})
        arch = _panel._route_archive(self.ctx, {"module": "m", "name": "out.zip"})
        self.assertTrue(Path(arch["archive"]).is_file())
        self.assertGreaterEqual(arch["files"], 1)

    def test_repo_text_pack_workspace_resolve(self):
        self.assertEqual(self.ctx.storage.repo_text(""), "")
        self.assertEqual(self.ctx.storage.repo_text("/etc/passwd"), "")
        self.assertEqual(self.ctx.storage.repo_text("../x"), "")
        self.assertTrue(self.ctx.storage.repo_text("docs/testing-layers.md"))
        self.assertEqual(self.ctx.storage.repo_text("no-such-file"), "")
        base = self.root / "escape"
        (base / "modules").mkdir(parents=True)
        outside = Path(tempfile.mkdtemp())
        (outside / "outside.txt").write_text("x")
        (self.root / "link").symlink_to(outside, target_is_directory=True)
        real = _panel._files.modules_root
        _panel._files.modules_root = lambda: base / "modules"
        try:
            self.assertEqual(self.ctx.storage.repo_text("link/outside.txt"), "")
        finally:
            _panel._files.modules_root = real
            import shutil
            shutil.rmtree(outside)
        self.assertEqual(_panel._route_workspace(self.ctx, {})["code"], "missing_project")
        self.assertEqual(_panel._route_workspace(self.ctx, {"project": "p"})["project"], "p")
        self.assertEqual(_panel._route_workspace(self.ctx, {"project": "p", "root": "rel"})["code"],
                         "root_not_absolute")
        out = _panel._route_resolve_doc(self.ctx, {"module": "m", "path": "doc.txt"})
        self.assertTrue(out["ok"])
        self.assertEqual(_panel._route_resolve_doc(self.ctx, {"module": "m", "path": "../x"})["code"],
                         "traversal")


if __name__ == "__main__":
    unittest.main()
