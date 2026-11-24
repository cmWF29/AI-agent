"""边界 fail-closed：鉴权会话、沙箱虚拟路径、ASR 分块、静态资源门槛。

这些用例不 mock 核心逻辑，只替换外部不可控依赖（bwrap 二进制探测）；
每条断言都覆盖具体状态/字段/返回码，防止“返回 200 就算过”的空测试。
"""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))

from ai_new.modules.agent.asr.private import _engine as asr_engine
from ai_new.modules.agent.asr.private import _pure as asr_pure
from ai_new.modules.agent.auth.private import _pure as auth_pure
from ai_new.modules.agent.web.private import _pure as web_pure
from ai_new.modules.agent_common.exec.private import _runner
from ai_new.modules.agent_common.trace.private import _trace


class AuthBoundaryTest(unittest.TestCase):
    def test_valid_token_rejects_path_fragments(self):
        for token in ("abc-123", "A_b-9"):
            self.assertTrue(auth_pure.valid_token({"token": token})["ok"], token)
        for token in ("", "../x", "a/b", "a\\b", "a.b", "x" * 129, "a b"):
            self.assertFalse(auth_pure.valid_token({"token": token})["ok"], token)

    def test_credentials_fail_closed_on_empty_hash(self):
        out = auth_pure.credentials_ok({
            "username": "admin", "expect_username": "admin",
            "digest": "", "expect_hash": ""})
        self.assertFalse(out["ok"])
        self.assertEqual(out["code"], "bad_credentials")
        self.assertTrue(auth_pure.credentials_ok({
            "username": "admin", "expect_username": "admin",
            "digest": "h", "expect_hash": "h"})["ok"])

    def test_session_without_expiry_is_invalid(self):
        rec = {"token": "tok", "username": "admin"}
        out = auth_pure.session_valid({"record": rec, "now": 1000.0})
        self.assertFalse(out["valid"])
        self.assertEqual(out["reason"], "no_expiry")
        bad = auth_pure.session_valid({
            "record": {"token": "tok", "username": "admin", "expires": "soon"},
            "now": 1000.0})
        self.assertFalse(bad["valid"])
        self.assertEqual(bad["reason"], "bad_expiry")

    def test_build_session_without_ttl_does_not_crash(self):
        rec = auth_pure.build_session({"token": "tok", "username": "admin",
                                       "issued": 1000.0})
        self.assertEqual(rec["ttl"], 0)
        self.assertEqual(rec["expires"], 1000.0)
        bad = auth_pure.build_session({"token": "tok", "issued": 1000.0,
                                       "ttl": "not-a-number"})
        self.assertEqual(bad["ttl"], 0)


class SandboxVirtualPathTest(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="sandbox-path-")

    def _sandbox(self, **overrides):
        spec = {"engine": "bwrap", "root": self.root, "mount": "/workspace",
                "cwd": "/workspace/tickets/T-1",
                "binds": [{"src": self.root, "dst": "/workspace"}]}
        spec.update(overrides)
        return spec

    def test_virtual_path_normalizes_and_rejects_escape(self):
        self.assertEqual(_runner._virtual_path("/workspace//a", "cwd")[0],
                         "/workspace/a")
        for raw in ("/workspace/../etc", "/workspace/a/../../etc", "relative",
                    "/", "/workspace/\x00x"):
            path, err = _runner._virtual_path(raw, "cwd")
            self.assertEqual(path, "", raw)
            self.assertTrue(err, raw)

    def test_bwrap_rejects_cwd_and_destination_escape(self):
        with patch.object(_runner.shutil, "which", return_value="/bin/true"):
            _, err = _runner._bwrap_command({"sandbox": self._sandbox(
                cwd="/workspace/../etc")}, "")
            self.assertIn("cwd", err)
            _, err = _runner._bwrap_command({"sandbox": self._sandbox(
                mount="/workspace/../etc")}, "")
            self.assertIn("mount", err)
            _, err = _runner._bwrap_command({"sandbox": self._sandbox(
                binds=[{"src": self.root, "dst": "/workspace/../etc"}])}, "")
            self.assertIn("bind 目的地", err)

    def test_bwrap_rejects_missing_root_and_outside_bind(self):
        with patch.object(_runner.shutil, "which", return_value="/bin/true"):
            args, err = _runner._bwrap_command({"sandbox": {"engine": "bwrap"}}, "")
            self.assertEqual(args, [])
            self.assertIn("sandbox", err)
            outside = tempfile.mkdtemp(prefix="sandbox-outside-")
            _, err = _runner._bwrap_command({"sandbox": self._sandbox(
                binds=[{"src": outside, "dst": "/workspace"}])}, "")
            self.assertIn("bind 源越出项目根", err)

    def test_bwrap_bind_mkdir_failure_is_fail_closed(self):
        denied = Path(self.root) / "denied"
        real_mkdir = Path.mkdir

        def fake_mkdir(self, *args, **kwargs):
            if str(self) == str(denied):
                raise OSError("denied")
            return real_mkdir(self, *args, **kwargs)

        with patch.object(_runner.shutil, "which", return_value="/bin/true"), \
                patch.object(Path, "mkdir", fake_mkdir):
            args, err = _runner._bwrap_command({"sandbox": self._sandbox(
                binds=[{"src": str(denied), "dst": "/workspace"}])}, "")
        self.assertEqual(args, [])
        self.assertIn("bind 源不可用", err)

    def test_bwrap_accepts_valid_paths_and_binds(self):
        with patch.object(_runner.shutil, "which", return_value="/bin/true"):
            args, err = _runner._bwrap_command({"sandbox": self._sandbox()}, "")
        self.assertIsNone(err)
        self.assertIn("--chdir", args)
        self.assertEqual(args[args.index("--chdir") + 1], "/workspace/tickets/T-1")
        self.assertIn("--bind", args)
        self.assertEqual(args[args.index("--bind") + 1], str(Path(self.root).resolve()))
        self.assertEqual(args[args.index("--bind") + 2], "/workspace")


class AsrBoundaryTest(unittest.TestCase):
    def test_chunk_size_rejects_zero_and_bad_values(self):
        self.assertEqual(asr_engine.chunk_size(4000), (4000, None))
        for raw in (0, -1, None, "bad", ""):
            step, err = asr_engine.chunk_size(raw)
            self.assertEqual(step, 0)
            self.assertEqual(err["code"], "bad_chunk_config")
            self.assertEqual(err["status"], 503)

    def test_transcribe_bad_chunk_config_returns_503_without_loop(self):
        class FakeApi:
            def call(self, method, payload, caller=None):
                if method == "codec.wave_decode":
                    return {"ok": True, "pcm": b"\x01\x02" * 8, "rate": 8000}
                if method == "config.get":
                    return {"value": 0}
                if method == "store.read":
                    return {"value": {"bad_chunk_config": "bad chunk"}}
                return {}

        class FakeCtx:
            api = FakeApi()

        with patch.object(asr_engine, "_load_model", return_value=(object(), None)):
            out = asr_engine.transcribe(FakeCtx(), b"wav")
        self.assertEqual(out["code"], "bad_chunk_config")
        self.assertEqual(out["status"], 503)
        self.assertEqual(out["error"], "bad chunk")

    def test_validate_and_present(self):
        self.assertFalse(asr_pure.validate({"audio": b""})["ok"])
        self.assertEqual(asr_pure.validate({"audio": b"\x00"})["ok"], True)
        self.assertFalse(asr_pure.present({"text": "  "})["ok"])
        out = asr_pure.present({"text": " 你好 "})
        self.assertEqual(out["text"], "你好")
        self.assertEqual(out["chars"], 2)


class TraceBoundaryTest(unittest.TestCase):
    def tearDown(self):
        _trace._S["st"] = None

    def test_routes_accept_none_payload_and_clamp_limits(self):
        _trace._S["st"] = None
        self.assertEqual(_trace._route_get(None, None)["count"], 0)
        self.assertEqual(_trace._route_list(None, None)["total"], 0)
        self.assertEqual(_trace._route_slow(None, None)["spans"], 0)
        self.assertEqual(_trace._route_recent(None, None)["total"], 0)
        self.assertEqual(_trace._route_attach(None, None), {"trace": ""})
        self.assertEqual(_trace._route_list(None, {"limit": -1})["items"], [])
        self.assertEqual(_trace._route_slow(None, {"limit": -1})["items"], [])
        self.assertEqual(_trace._route_recent(None, {"limit": -1})["items"], [])


class WebBoundaryTest(unittest.TestCase):
    def test_gate_public_only_login_and_assets(self):
        self.assertTrue(web_pure.gate({"path": "login.html"})["public"])
        self.assertTrue(web_pure.gate({"path": "assets/app.css"})["public"])
        self.assertFalse(web_pure.gate({"path": "manage.html"})["public"])
        self.assertFalse(web_pure.gate({"path": "page.HTML"})["public"])

    def test_rel_mime_and_console_path(self):
        self.assertEqual(web_pure.rel({"path": "/manage.html"})["path"], "manage.html")
        self.assertEqual(web_pure.mime({"path": "x.unknown"})["type"],
                         "application/octet-stream")
        self.assertEqual(web_pure.mime({"path": "x.CSS"})["type"],
                         "text/css; charset=utf-8")
        self.assertEqual(web_pure.console_path({
            "paths": {"console": "console/{rel}"}, "path": "/a.js"})["path"],
            "console/a.js")


if __name__ == "__main__":
    unittest.main(verbosity=2)
