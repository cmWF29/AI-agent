"""Web 面板单测：静态资源定位、越界拒绝、打包产物拼接与注册包装。"""
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))

from ai_new.modules.agent.web.private import _panel, _pure


class ApiError(Exception):
    def __init__(self, message, code="E", status=500):
        super().__init__(message)
        self.code = code
        self.status = status


class FakeApi:
    def __init__(self, files, cfg=None):
        self.files = files
        self.cfg = {"web.paths": {"console": "console/{rel}"}, "web.bundle": []}
        self.cfg.update(cfg or {})
        self.registered = []

    def register(self, name, fn, desc=None, module=None):
        self.registered.append(name)

    def call(self, name, payload=None, caller=None):
        p = payload or {}
        if name == "config.get":
            return {"value": self.cfg.get(p.get("key"))}
        if name == "store.read_text":
            return self.files.get(p.get("path"),
                                  {"exists": False, "value": p.get("fallback", "")})
        raise AssertionError(name)


def make_ctx(root, files, cfg=None):
    api = FakeApi(files, cfg)
    return SimpleNamespace(api=api, ApiError=ApiError,
                           storage=SimpleNamespace(own=lambda f: SimpleNamespace(root=Path(root)))), api


class AssetTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.outside = tempfile.mkdtemp()
        Path(self.outside, "secret.txt").write_text("TOPSECRET")
        Path(self.tmp, "console").mkdir()
        # 数据根内造一个指向根外的符号链接：realpath 后必须被拒
        os.symlink(self.outside, Path(self.tmp, "console", "escape"))

    def test_plain_asset(self):
        ctx, api = make_ctx(self.tmp, {"console/index.html": {"exists": True, "value": "<html>"}})
        got = _panel.WebPanel(ctx).asset(ctx, "index.html")
        self.assertEqual(got, {"content": "<html>",
                               "content_type": "text/html; charset=utf-8"})

    def test_without_console_template(self):
        ctx, api = make_ctx(self.tmp, {"index.html": {"exists": True, "value": "x"}},
                            {"web.paths": {}})
        self.assertEqual(_panel.WebPanel(ctx).asset(ctx, "/index.html")["content"], "x")

    def test_missing_asset(self):
        ctx, api = make_ctx(self.tmp, {})
        with self.assertRaises(ApiError) as cm:
            _panel.WebPanel(ctx).asset(ctx, "nope.html")
        self.assertEqual(cm.exception.code, "no_asset")
        self.assertEqual(cm.exception.status, 404)

    def test_dotdot_rejected(self):
        ctx, api = make_ctx(self.tmp, {})
        with self.assertRaises(ApiError) as cm:
            _panel.WebPanel(ctx).asset(ctx, "../../etc/passwd")
        self.assertEqual(cm.exception.code, "path_escape")

    def test_symlink_escape_rejected(self):
        ctx, api = make_ctx(self.tmp, {"console/escape/secret.txt": {"exists": True, "value": "x"}})
        with self.assertRaises(ApiError) as cm:
            _panel.WebPanel(ctx).asset(ctx, "escape/secret.txt")
        self.assertEqual(cm.exception.code, "path_escape")

    def test_bundle_joins_parts(self):
        cfg = {"web.bundle": [{"out": "app.js", "parts": ["a.js", "b.js"]},
                             {"out": "other.js"}]}
        ctx, api = make_ctx(self.tmp, {"console/a.js": {"exists": True, "value": "A"},
                                       "console/b.js": {"exists": True, "value": "B"}}, cfg)
        got = _panel.WebPanel(ctx).asset(ctx, "app.js")
        self.assertEqual(got, {"content": "A\n;\nB",
                               "content_type": "application/javascript; charset=utf-8",
                               "no_cache": True})

    def test_bundle_match_on_second_entry(self):
        cfg = {"web.bundle": [{"out": "other.js", "parts": ["a.js"]},
                             {"out": "app.js", "parts": ["a.js"]}]}
        ctx, api = make_ctx(self.tmp, {"console/a.js": {"exists": True, "value": "A"}}, cfg)
        self.assertEqual(_panel.WebPanel(ctx).asset(ctx, "app.js")["content"], "A")

    def test_join_and_cfg_paths(self):
        ctx, api = make_ctx(self.tmp, {}, {"web.paths": {"console": "c/{rel}"}})
        self.assertEqual(_panel._join(ctx, "x.js"), "c/x.js")
        ctx2, _ = make_ctx(self.tmp, {}, {"web.paths": None})
        self.assertEqual(_panel._cfg_paths(ctx2), {})


class PureWebTest(unittest.TestCase):
    def test_gate_matrix(self):
        self.assertEqual(_pure.gate({}), {"public": False, "to": "login.html"})
        self.assertEqual(_pure.gate({"path": "/login.html"}), {"public": True, "to": "login.html"})
        self.assertEqual(_pure.gate({"path": "a/b.css"}), {"public": True, "to": ""})
        self.assertEqual(_pure.gate({"path": "conf.json"}), {"public": False, "to": "login.html"})
        self.assertEqual(_pure.gate({"path": "noext"}), {"public": False, "to": "login.html"})

    def test_info_and_console_path(self):
        self.assertEqual(_pure.info({"console": {"a": 1}, "routes": ["r"], "demands": ["d"]}),
                         {"name": "ai_new", "console": {"a": 1}, "routes": ["r"],
                          "demands": ["d"]})
        self.assertEqual(_pure.info({}), {"name": "ai_new", "console": {}, "routes": [],
                                        "demands": []})
        self.assertEqual(_pure.console_path({"paths": {"console": "c/{rel}"}, "path": "/a.html"}),
                         {"path": "c/a.html"})
        self.assertEqual(_pure.console_path({"path": "a.html"}), {"path": "a.html"})

    def test_mime_and_rel(self):
        self.assertEqual(_pure.mime({"path": "a.css"})["type"], "text/css; charset=utf-8")
        self.assertEqual(_pure.mime({"path": "a.bin"})["type"], "application/octet-stream")
        self.assertEqual(_pure.mime({})["type"], "application/octet-stream")
        self.assertEqual(_pure.rel({}), {"path": "manage.html"})


class SetupTest(unittest.TestCase):
    def test_setup_wraps_handlers_with_paths(self):
        tmp = tempfile.mkdtemp()
        ctx, api = make_ctx(tmp, {}, {"web.paths": {"console": "console/{rel}"}})
        captured = {}

        class RecApi(FakeApi):
            def register(self, name, fn, desc=None, module=None):
                captured[name] = fn

        ctx.api = RecApi({}, {"web.paths": {"console": "console/{rel}"}})
        self.assertTrue(_panel.setup(ctx))
        self.assertTrue(hasattr(ctx, "web"))
        self.assertEqual(sorted(captured), ["web.console_path", "web.gate", "web.info",
                                            "web.mime", "web.rel"])
        self.assertEqual(captured["web.rel"](ctx, {"path": "a.html"}), {"path": "a.html"})
        self.assertEqual(captured["web.rel"](ctx, {"path": "a.html", "paths": {}}),
                         {"path": "a.html"})

    def test_package_setup_delegates(self):
        import ai_new.modules.agent.web as web_pkg
        tmp = tempfile.mkdtemp()
        ctx, api = make_ctx(tmp, {})
        self.assertTrue(web_pkg.setup(ctx))
        self.assertTrue(hasattr(ctx, "web"))


if __name__ == "__main__":
    unittest.main()
