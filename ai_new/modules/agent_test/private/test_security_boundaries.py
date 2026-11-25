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
from ai_new.modules.agent import auth as auth_mod
from ai_new.modules.agent.auth.private import _pure as auth_pure
from ai_new.modules.agent.tickets.private import _pure as ticket_pure
from ai_new.modules.agent.web.private import _pure as web_pure
from ai_new.modules.agent_common.codec.private import _codec
from ai_new.modules.agent_common.llm.private import _client as llm_client
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

    def test_change_password_requires_existing_and_old_digest(self):
        # 空期望摘要 = 账号尚未建立凭据；不能把“没有旧密码”当“旧密码正确”。
        empty = auth_pure.change_password({
            "old_digest": "", "new_digest": "n", "confirm_digest": "n",
            "expect_hash": ""})
        self.assertFalse(empty["ok"])
        self.assertEqual(empty["code"], "bad_old_password")
        no_old = auth_pure.change_password({
            "old_digest": "", "new_digest": "n", "confirm_digest": "n",
            "expect_hash": "h"})
        self.assertFalse(no_old["ok"])
        wrong = auth_pure.change_password({
            "old_digest": "x", "new_digest": "n", "confirm_digest": "n",
            "expect_hash": "h"})
        self.assertEqual(wrong["code"], "bad_old_password")
        mismatch = auth_pure.change_password({
            "old_digest": "h", "new_digest": "n", "confirm_digest": "m",
            "expect_hash": "h"})
        self.assertEqual(mismatch["code"], "confirm_mismatch")
        self.assertTrue(auth_pure.change_password({
            "old_digest": "h", "new_digest": "n", "confirm_digest": "n",
            "expect_hash": "h"})["ok"])

    def test_session_path_requires_template(self):
        # 模板缺失不能把裸令牌当模块内相对路径，否则配置缺失会改写错位置。
        self.assertEqual(auth_pure.session_path({
            "paths": {}, "token": "tok"})["path"], "")
        self.assertEqual(auth_pure.session_path({
            "paths": {"session": "sessions/{token}.yaml"}, "token": "tok"})["path"],
            "sessions/tok.yaml")


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
        self.assertTrue(web_pure.gate({"path": "assets/icon.svg"})["public"])
        self.assertFalse(web_pure.gate({"path": "manage.html"})["public"])
        self.assertFalse(web_pure.gate({"path": "page.HTML"})["public"])
        # json/yaml/md 可能承载配置或正文，不能因为“不是 HTML”就匿名放行。
        for path in ("api.yaml", "data.json", "notes.md"):
            self.assertFalse(web_pure.gate({"path": path})["public"], path)

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


class CodecBoundaryTest(unittest.TestCase):
    def test_json_and_sse_reject_wrong_shapes_without_crashing(self):
        self.assertEqual(_codec.json_decode({"not": "text"})["code"], "decode_failed")
        self.assertEqual(_codec.json_decode("[1,2]")["value"], [1, 2])
        self.assertEqual(_codec.sse_decode(b'data: {"a": 1}\n\ndata: [DONE]\n'),
                         {"ok": True, "items": [{"a": 1}]})
        self.assertEqual(_codec.sse_decode({"bad": "shape"})["code"], "decode_failed")

    def test_digest_only_allows_known_hash_family(self):
        good = _codec.digest("abc", "sha256")
        self.assertTrue(good["ok"])
        self.assertEqual(good["hex"], "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad")
        self.assertTrue(_codec.digest("abc", "MD5")["ok"])
        for algo in ("pbkdf2_hmac", "scrypt", "new", "__class__", ""):
            if algo == "":
                continue
            self.assertFalse(_codec.digest("abc", algo)["ok"], algo)
            self.assertEqual(_codec.digest("abc", algo)["code"], "bad_algorithm")

    def test_nonce_length_is_bounded(self):
        token = _codec.nonce(10 ** 9)["token"]
        self.assertGreaterEqual(len(token), 8)
        self.assertLessEqual(len(token), 5500)
        self.assertFalse(_codec.nonce("bad")["ok"])

    def test_decode_hex_clamps_negative_limit_and_marks_binary(self):
        out = _codec.decode_hex("00ff", max_bytes=-1)
        self.assertEqual(out["text"], "")
        self.assertFalse(out["truncated"])
        binout = _codec.decode_hex("00ff10", max_bytes=2, size=3)
        self.assertEqual(binout["encoding"], "binary")
        self.assertTrue(binout["truncated"])

    def test_wave_decode_rejects_non_bytes_and_bad_wav(self):
        self.assertEqual(_codec.wave_decode("not-bytes")["code"], "bad_audio")
        self.assertEqual(_codec.wave_decode(b"not-wav")["code"], "bad_audio")

    def test_wave_decode_accepts_pcm_wav(self):
        import io
        import wave
        buf = io.BytesIO()
        with wave.open(buf, "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(8000)
            wav.writeframes(b"\x00\x00" * 16)
        out = _codec.wave_decode(buf.getvalue())
        self.assertTrue(out["ok"])
        self.assertEqual(out["rate"], 8000)
        self.assertEqual(out["channels"], 1)
        self.assertEqual(len(out["pcm"]), 32)


class LlmBoundaryTest(unittest.TestCase):
    def test_encode_rejects_bad_messages_tools_and_temperature(self):
        self.assertEqual(llm_client.encode()["code"], "llm_not_configured")
        self.assertEqual(llm_client.encode("http://x", messages={"role": "user"})["code"],
                         "bad_messages")
        self.assertEqual(llm_client.encode("http://x", messages=[{"role": "user"},
                                                                 "bad"])["code"],
                         "bad_messages")
        self.assertEqual(llm_client.encode("http://x", tools={"x": 1})["code"], "bad_tools")
        self.assertEqual(llm_client.encode("http://x", temperature="hot")["code"],
                         "bad_temperature")
        self.assertEqual(llm_client.encode("http://x", temperature=float("nan"))["code"],
                         "bad_temperature")
        good = llm_client.encode("http://x", messages=[{"role": "user", "content": "hi"}],
                                  temperature=0.2)
        self.assertTrue(good["ok"])
        self.assertEqual(good["payload"]["messages"][0]["content"], "hi")
        self.assertEqual(good["payload"]["temperature"], 0.2)

    def test_decode_rejects_non_standard_response_shapes(self):
        for payload in ({"choices": {"0": {}}}, {"choices": [1]},
                        {"choices": [{"message": []}]},
                        {"choices": [{"message": {"content": [1]}}]},
                        {"choices": [{"message": {"tool_calls": {"x": 1}}}]}):
            out = llm_client.decode(payload)
            self.assertFalse(out["ok"], payload)
            self.assertEqual(out["code"], "llm_bad_payload")
        self.assertEqual(llm_client.decode([1])["code"], "llm_bad_payload")
        self.assertEqual(llm_client.decode({"error": {"code": "x"}})["code"], "llm_error")
        ok = llm_client.decode({"choices": [{"message": {"content": "你好"},
                                             "finish_reason": "stop"}], "usage": {"t": 1}})
        self.assertTrue(ok["ok"])
        self.assertEqual(ok["content"], "你好")
        self.assertEqual(ok["finish"], "stop")

    def test_decode_sse_merges_fragments_and_rejects_bad_events(self):
        out = llm_client.decode_sse([
            {"choices": [{"delta": {"content": "你"}}]},
            {"choices": [{"delta": {"content": "好"},
                          "finish_reason": "stop"}]},
            {"choices": [{"delta": {"tool_calls": [
                {"index": 0, "id": "c1", "function": {"name": "read", "arguments": '{"a"'}}]}}]},
            {"choices": [{"delta": {"tool_calls": [
                {"index": 0, "function": {"arguments": ":1}"}}]}}]},
        ])
        self.assertTrue(out["ok"])
        self.assertEqual(out["content"], "你好")
        self.assertEqual(out["tool_calls"][0]["function"]["arguments"], '{"a":1}')
        for items in ([1], [{"choices": {"0": {}}}], [{"choices": [{"delta": []}]}]):
            self.assertEqual(llm_client.decode_sse(items)["code"], "llm_bad_payload")

    def test_wire_masks_secret_headers(self):
        wire = llm_client.wire({"url": "http://x", "headers": {
            "Authorization": "Bearer secret", "X-Api-Key": "k", "Accept": "json"},
            "model": "m", "status": 200})
        self.assertEqual(wire["headers"]["Authorization"], "***")
        self.assertEqual(wire["headers"]["X-Api-Key"], "***")
        self.assertEqual(wire["headers"]["Accept"], "json")
        self.assertEqual(wire["model"], "m")


class LoginThrottleBoundaryTest(unittest.TestCase):
    def test_keys_do_not_lock_account_globally(self):
        self.assertEqual(auth_pure.throttle_keys({"peer": "1.2.3.4", "username": "admin"})["keys"],
                         ["ip:1.2.3.4", "pair:1.2.3.4|admin"])
        self.assertEqual(auth_pure.throttle_keys({"username": "admin"})["keys"],
                         ["user:admin"])
        self.assertEqual(auth_pure.throttle_keys({})["keys"], [])

    def test_guard_cfg_clamps_bad_values_and_mutate_fails_closed(self):
        class FakeApi:
            def __init__(self, cas):
                self.cas_result = cas

            def call(self, name, payload=None, caller=None, direct=False):
                if name == "store.read":
                    return {"value": []}
                if name == "clock.now":
                    return {"ts": 1000.0}
                if name == "store.cas":
                    return self.cas_result
                return {}

        class FakeCtx:
            cfg = {"server": {"auth": {"login_guard": {
                "max_failures": "bad", "window_seconds": 0,
                "lock_seconds": 10 ** 9, "max_entries": -1}}}}
            api = FakeApi({"ok": False, "conflict": True})

        cfg = auth_mod._guard_cfg(FakeCtx())
        self.assertEqual(cfg["max_failures"], 5)
        self.assertEqual(cfg["window_seconds"], 1)
        self.assertEqual(cfg["lock_seconds"], 86400)
        self.assertEqual(cfg["max_entries"], 1)
        self.assertEqual(auth_mod._throttle_read(FakeCtx()), {})
        self.assertEqual(auth_mod._throttle_mutate(FakeCtx(), ["ip:a"], False),
                         {"error": "guard_conflict_exhausted"})
        FakeCtx.api = FakeApi({"ok": False, "code": "write_failed"})
        self.assertEqual(auth_mod._throttle_mutate(FakeCtx(), ["ip:a"], False),
                         {"error": "write_failed"})

    def test_check_and_update_lock_then_success_clears(self):
        now = 1000.0
        cfg = {"max_failures": 2, "window_seconds": 60, "lock_seconds": 120,
               "max_entries": 10}
        out = auth_pure.throttle_update({"entries": {}, "keys": ["ip:a"], "now": now,
                                         "cfg": cfg, "success": False})
        self.assertFalse(out["blocked"])
        out = auth_pure.throttle_update({"entries": out["entries"], "keys": ["ip:a"],
                                         "now": now + 1, "cfg": cfg, "success": False})
        self.assertTrue(out["blocked"])
        self.assertEqual(out["retry_after"], 121)
        out = auth_pure.throttle_update({"entries": out["entries"], "keys": ["ip:a"],
                                         "now": now + 2, "cfg": cfg, "success": True})
        self.assertFalse(out["blocked"])
        self.assertEqual(out["entries"], {})

    def test_window_resets_and_malformed_entries_are_dropped(self):
        now = 1000.0
        cfg = {"max_failures": 3, "window_seconds": 10, "lock_seconds": 0,
               "max_entries": 10}
        entries = {"ip:a": {"failures": 2, "first": 900.0, "last": 900.0,
                            "lock_until": 0},
                   "bad": "not-a-dict",
                   "worse": {"failures": 1, "first": 0, "last": "bad",
                             "lock_until": 0}}
        out = auth_pure.throttle_update({"entries": entries, "keys": ["ip:a"],
                                         "now": now, "cfg": cfg, "success": False})
        self.assertEqual(out["entries"]["ip:a"]["failures"], 1)
        self.assertNotIn("bad", out["entries"])
        self.assertNotIn("worse", out["entries"])

    def test_check_ignores_bad_lock_values(self):
        entries = {"ip:a": {"lock_until": "bad"}, "ip:b": {"lock_until": "2000"}}
        out = auth_pure.throttle_check({"entries": entries,
                                        "keys": ["ip:a", "ip:b"], "now": 1000.0})
        self.assertTrue(out["blocked"])
        self.assertEqual(out["retry_after"], 1001)

    def test_entries_are_pruned_and_capped(self):
        now = 1000.0
        cfg = {"max_failures": 5, "window_seconds": 10, "lock_seconds": 0,
               "max_entries": 2}
        entries = {"old": {"failures": 1, "first": 0, "last": 0, "lock_until": 0},
                   "keep1": {"failures": 1, "first": now, "last": now, "lock_until": 0},
                   "keep2": {"failures": 1, "first": now - 1, "last": now - 1, "lock_until": 0}}
        out = auth_pure.throttle_update({"entries": entries, "keys": ["keep1"],
                                         "now": now, "cfg": cfg, "success": False})
        self.assertNotIn("old", out["entries"])
        self.assertEqual(len(out["entries"]), 2)


class TicketInputBoundaryTest(unittest.TestCase):
    def test_validate_project_and_create_reject_wrong_types(self):
        self.assertEqual(ticket_pure.validate_project({"project": ["p"]})["code"],
                         "bad_project")
        self.assertEqual(ticket_pure.validate_create({"project": {}})["code"], "bad_project")
        self.assertEqual(ticket_pure.validate_create({"project": "p", "title": ["x"]})["code"],
                         "bad_input")
        self.assertEqual(ticket_pure.validate_create({"project": "p", "goal": "x" * 4001})["code"],
                         "bad_input")
        self.assertEqual(ticket_pure.validate_create({"project": "p", "meta": []})["code"],
                         "bad_input")
        self.assertEqual(ticket_pure.validate_create({"project": "p", "pm_max_steps": True})["code"],
                         "bad_input")
        self.assertTrue(ticket_pure.validate_create({"project": "p", "kind": ""})["ok"])
        self.assertEqual(ticket_pure.validate_create({"project": "p", "auto_retrospective": "x"})["code"],
                         "bad_input")
        self.assertTrue(ticket_pure.validate_create({"project": "p", "title": "t"})["ok"])

    def test_validate_split_rejects_non_list_and_bad_limit(self):
        self.assertEqual(ticket_pure.validate_split({"children": "x"})["code"], "bad_input")
        self.assertEqual(ticket_pure.validate_split({"children": ["x"]})["code"], "bad_input")
        self.assertEqual(ticket_pure.validate_split({"children": [{"title": ["x"]}]})["code"],
                         "bad_input")
        self.assertEqual(ticket_pure.validate_split({"children": [], "max_children": "1"})["code"],
                         "bad_input")
        self.assertEqual(ticket_pure.validate_split({"children": [], "force": "true"})["code"],
                         "bad_input")
        self.assertTrue(ticket_pure.validate_split({"children": [{"title": "a", "goal": "b"}],
                                                     "max_children": 1, "force": False})["ok"])

    def test_validate_text_and_rebind_reject_wrong_types(self):
        self.assertEqual(ticket_pure.validate_text({"text": ["x"]})["code"], "bad_input")
        self.assertEqual(ticket_pure.validate_text({"text": "x" * 20001})["code"], "bad_input")
        self.assertEqual(ticket_pure.validate_rebind({"from": [], "to": "b"})["code"],
                         "bad_input")
        self.assertEqual(ticket_pure.validate_rebind({"from": "a", "to": "a"})["code"],
                         "bad_input")
        self.assertEqual(ticket_pure.validate_rebind({"from": "a", "to": ""})["code"],
                         "bad_input")

    def test_slim_thread_survives_non_dict_messages(self):
        out = ticket_pure._slim_thread(["raw", {"role": "system", "content": "drop"},
                                        {"role": "user", "content": "hi"}])
        self.assertEqual(len(out), 2)
        self.assertEqual(out[1]["content"], "hi")

    def test_validate_audio_requires_bytes(self):
        for audio in ("str", {}, [], 0):
            self.assertFalse(asr_pure.validate({"audio": audio})["ok"], audio)
        self.assertTrue(asr_pure.validate({"audio": b"\x00"})["ok"])
