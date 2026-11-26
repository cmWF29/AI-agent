"""llm 路由与 auth 闸/登录/节流覆盖。"""
import asyncio
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))
from unittest import mock

from ai_new.modules.agent_common import llm
from ai_new.modules.agent_common.llm.private import _client
from ai_new.modules.agent import auth
from ai_new.modules.agent.auth.private import _pure as apure


class ApiError(Exception):
    def __init__(self, msg, code="bad", status=400):
        super().__init__(msg)
        self.message = msg
        self.code = code
        self.status = status


class Ctx:
    ApiError = ApiError

    def __init__(self):
        self.cfg = {"llm": {"base_url": "http://x", "api_key": "k", "model": "m"},
                    "server": {"auth": {"enabled": False}}}
        self.clock = mock.Mock()
        self.clock.now.return_value = {"ts": 10}
        self.api = mock.Mock()
        self.api.call = self._call
        self.api.acall = self._acall
        self.api.register = mock.Mock()
        self.routes = {}
        self.throttle = {}
        self.cas_seq = []
        self.store_exc = False
        self.runtime = mock.Mock()
        self.runtime.active_keys.return_value = []

    def _call(self, name, payload=None, caller=None):
        p = payload or {}
        fn = self.routes.get(name)
        if fn:
            return fn(p)
        if name == "config.get":
            if p.get("key") == "server.auth":
                return {"value": self.cfg["server"].get("auth") or {}}
            if p.get("key") == "auth.paths":
                return {"value": {"session": "auth/{token}.yaml"}}
            if p.get("key") == "logs.paths":
                return {"value": {"tool": "projects/{project}/logs/{fid}.txt"}}
            if p.get("key") == "sessions.context.tool_output_chars":
                return {"value": 10}
            if p.get("key") == "sessions.react_cap":
                return {"value": 0}
            return {"value": None}
        if name == "codec.digest":
            return {"hex": "d"}
        if name == "llm.encode":
            return llm._route_encode(self, p)
        if name == "clock.now":
            return {"ts": 10}
        if name == "auth.session_valid":
            return {"valid": True, "username": "u"}
        if name == "auth.session_path":
            return {"path": "auth/t.yaml"}
        if name == "auth.login":
            return {}
        if name == "llm.decode_sse":
            return {"ok": True, "content": "", "tool_calls": None}
        if name == "codec.json_encode":
            return {"ok": True, "text": json.dumps(p.get("value"))}
        if name == "codec.json_decode":
            try:
                return {"ok": True, "value": json.loads(p.get("text") or "null")}
            except ValueError:
                return {"ok": False}
        if name == "codec.nonce":
            return {"token": "tok"}
        if name == "store.read":
            if self.store_exc:
                raise RuntimeError("x")
            if p.get("path") == "login-throttle.json":
                return {"value": self.throttle}
            return {"exists": True, "value": {"token": "t", "username": "u",
                                              "issued": 0, "expires": 100}}
        if name == "store.cas":
            if self.cas_seq:
                return self.cas_seq.pop(0)
            return {"ok": True}
        if name in ("auth.build_session", "auth.session_view"):
            return {"token": "t", "username": "u", "ttl": 1}
        if name == "auth.credentials_ok":
            return {"ok": False}
        raise AssertionError(name)

    async def _acall(self, name, payload=None, caller=None):
        p = payload or {}
        if name == "net.request_stream":
            return self.routes.get("net", lambda x: {"ok": True, "items": []})(p)
        if name == "net.request":
            return self.routes.get("net", lambda x: {"ok": True, "text": ""})(p)
        raise AssertionError(name)


class LlmTest(unittest.TestCase):
    def ctx(self):
        return Ctx()

    def test_encode(self):
        ctx = self.ctx()
        self.assertTrue(llm.setup(ctx))
        out = llm._route_encode(ctx, {"base_url": "http://x", "stream": True,
                                      "messages": [{"role": "user", "content": "a"}],
                                      "tools": [], "temperature": 0.2})
        self.assertTrue(out["ok"])
        self.assertTrue(out["payload"]["stream"])
        with mock.patch.object(llm._client, "encode", side_effect=ApiError("bad")):
            self.assertEqual(llm._route_encode(ctx, {})["code"], "bad")
        self.assertEqual(llm._route_decode_sse(ctx, {})["tool_calls"], None)
        self.assertEqual(llm.encode(ctx, base_url="http://x")["ok"], True)
        self.assertTrue(llm.decode(ctx, {})["ok"] is False)
        self.assertTrue(llm.decode_sse(ctx, [])["ok"])

    def test_encode_call_fail_wire(self):
        ctx = self.ctx()
        enc = llm._encode_call(ctx, {"base_url": "http://y", "tools": [],
                                     "tool_choice": "auto", "temperature": 1}, False)
        self.assertEqual(enc["url"], "http://y/chat/completions")
        self.assertFalse(enc["payload"]["stream"])
        ctx.cfg["llm"] = {}
        enc = llm._encode_call(ctx, {}, True)
        self.assertEqual(enc["code"], "llm_not_configured")
        self.assertEqual(llm._fail(ctx, {"error": "{\"error\":{\"code\":\"up\"}}",
                                         "code": "n"})["code"], "up")
        self.assertEqual(llm._fail(ctx, {"error": "[1]", "code": "n"})["code"], "n")
        self.assertEqual(llm._fail(ctx, {"error": "x"})["code"], "net_error")
        self.assertEqual(llm._fail(ctx, {})["error"], None)
        wire = llm._wire(ctx, {"url": "u", "headers": {"Authorization": "x"},
                               "payload": {"model": "m"}},
                         {"error": "e"}, {"text": "b"}, True)
        self.assertEqual(wire["headers"]["Authorization"], "***")
        self.assertEqual(wire["response"], "e")

    def test_chat(self):
        ctx = self.ctx()
        ctx.routes["llm.encode"] = lambda p: {"ok": False, "code": "x"}
        self.assertEqual(asyncio.run(llm._route_chat(ctx, {}))["code"], "x")
        ctx.routes["llm.encode"] = lambda p: {"ok": True, "url": "u", "headers": {},
                                               "payload": {}}
        ctx.routes["net"] = lambda p: {"ok": False, "code": "net", "error": "e"}
        out = asyncio.run(llm._route_chat(ctx, {"cancel": {"id": "c"}}))
        self.assertEqual(out["code"], "net")
        self.assertIn("wire", out)
        ctx.routes["net"] = lambda p: {"ok": True, "items": [{"a": 1}]}
        ctx.routes["llm.decode_sse"] = lambda p: {"ok": True}
        out = asyncio.run(llm._route_chat(ctx, {}))
        self.assertTrue(out["ok"])
        self.assertIn("wire", out)
        ctx.routes["llm.decode_sse"] = lambda p: "x"
        self.assertEqual(asyncio.run(llm._route_chat(ctx, {})), "x")

    def test_timeout_from_config_and_payload_wins(self):
        """超时口径：调用方给的最优先，否则读 llm.timeout；都没有才交默认值。"""
        ctx = self.ctx()
        ctx.routes["llm.encode"] = lambda p: {"ok": True, "url": "u", "headers": {},
                                               "payload": {}}
        seen = {}

        def net(p):
            seen["timeout"] = p.get("timeout")
            return {"ok": True, "items": []}
        ctx.routes["net"] = net
        ctx.cfg["llm"]["timeout"] = 7
        asyncio.run(llm._route_chat(ctx, {}))
        self.assertEqual(seen["timeout"], 7)
        asyncio.run(llm._route_chat(ctx, {"timeout": 2}))
        self.assertEqual(seen["timeout"], 2)
        asyncio.run(llm._route_chat(ctx, {"timeout": ""}))
        self.assertEqual(seen["timeout"], 7)
        ctx.cfg["llm"].pop("timeout")
        asyncio.run(llm._route_chat(ctx, {"timeout": ""}))
        self.assertIsNone(seen["timeout"])
        ctx.cfg["llm"]["timeout"] = 5
        ctx.routes["codec.sse_decode"] = lambda p: {"ok": True, "items": []}
        asyncio.run(llm._route_chat_stream(ctx, {}))
        self.assertEqual(seen["timeout"], 5)
        self.assertEqual(llm._limit(ctx, {"timeout": 3}), 3)

    def test_chat_stream(self):
        ctx = self.ctx()
        ctx.routes["llm.encode"] = lambda p: {"ok": False, "code": "enc"}
        self.assertEqual(asyncio.run(llm._route_chat_stream(ctx, {}))["code"], "enc")
        ctx.routes["llm.encode"] = lambda p: {"ok": True, "url": "u", "headers": {},
                                               "payload": {}}
        ctx.routes["net"] = lambda p: {"ok": False, "error": "e"}
        out = asyncio.run(llm._route_chat_stream(ctx, {}))
        self.assertEqual(out["code"], "net_error")
        self.assertEqual(out["wire"]["response"], "e")
        ctx.routes["net"] = lambda p: {"ok": True, "text": "data: {}"}
        ctx.routes["codec.sse_decode"] = lambda p: {"ok": False, "code": "s"}
        self.assertEqual(asyncio.run(llm._route_chat_stream(ctx, {}))["code"], "s")
        ctx.routes["codec.sse_decode"] = lambda p: {"ok": True, "items": []}
        ctx.routes["llm.decode_sse"] = lambda p: "x"
        self.assertEqual(asyncio.run(llm._route_chat_stream(ctx, {})), "x")
        ctx.routes["llm.decode_sse"] = lambda p: {"ok": True}
        self.assertIn("wire", asyncio.run(llm._route_chat_stream(ctx, {})))


class LlmPureTest(unittest.TestCase):
    def test_encode_branches(self):
        self.assertEqual(_client.encode()["code"], "llm_not_configured")
        self.assertEqual(_client.encode(base_url="u", messages="x")["code"],
                         "bad_messages")
        self.assertEqual(_client.encode(base_url="u", messages=[1])["code"],
                         "bad_messages")
        out = _client.encode(base_url="u/", api_key="k",
                             messages=[{"role": "assistant", "content": "a"},
                                       {"role": "assistant", "content": "a",
                                        "tool_calls": [1]},
                                       {"role": "tool"},
                                       {"content": "u"}],
                             tools=[{"x": 1}], tool_choice="auto",
                             temperature="1.5")
        self.assertTrue(out["ok"])
        self.assertNotIn("tool_calls", out["payload"]["messages"][0])
        self.assertEqual(out["payload"]["messages"][1]["tool_calls"], [1])
        self.assertEqual(out["payload"]["messages"][3]["content"], "u")
        self.assertEqual(_client.encode(base_url="u", messages=[],
                                        tools="x")["code"], "bad_tools")
        self.assertEqual(_client.encode(base_url="u", messages=[], tools=[],
                                        tool_choice="auto")["payload"].get("tool_choice"),
                         None)
        self.assertEqual(_client.encode(base_url="u", messages=[], tools=[{}]
                                        )["payload"]["tools"], [{}])
        self.assertEqual(_client.encode(base_url="u", messages=[],
                                        temperature="x")["code"], "bad_temperature")
        self.assertEqual(_client.encode(base_url="u", messages=[],
                                        temperature=float("nan") + 1)["code"],
                         "bad_temperature")
        self.assertEqual(_client.encode(base_url="u", messages=[],
                                        temperature=float("inf"))["code"],
                         "bad_temperature")

    def test_decode_branches(self):
        self.assertEqual(_client.decode("x")["code"], "llm_bad_payload")
        self.assertEqual(_client.decode({"error": "e"})["code"], "llm_error")
        self.assertEqual(_client.decode({})["code"], "llm_bad_payload")
        self.assertEqual(_client.decode({"choices": ["x"]})["code"],
                         "llm_bad_payload")
        self.assertEqual(_client.decode({"choices": [{}]})["ok"], True)
        self.assertEqual(_client.decode({"choices": [{"message": 1}]})["code"],
                         "llm_bad_payload")
        self.assertEqual(_client.decode({"choices": [{"message": {"content": 1}}]})["code"],
                         "llm_bad_payload")
        self.assertEqual(_client.decode(
            {"choices": [{"message": {"tool_calls": "x"}}]})["code"],
            "llm_bad_payload")
        out = _client.decode({"choices": [{"message": {"content": None,
                                                       "tool_calls": [1]},
                                           "finish_reason": "stop"}],
                              "usage": {"t": 1}})
        self.assertTrue(out["ok"])
        self.assertEqual(out["content"], "")
        self.assertEqual(out["finish"], "stop")

    def test_decode_sse_branches(self):
        self.assertEqual(_client.decode_sse("x")["code"], "llm_bad_payload")
        self.assertEqual(_client.decode_sse([1])["code"], "llm_bad_payload")
        self.assertEqual(_client.decode_sse([{"choices": "x"}])["code"],
                         "llm_bad_payload")
        self.assertTrue(_client.decode_sse([{"x": 1}])["ok"])
        self.assertTrue(_client.decode_sse([{"choices": [{}]}])["ok"])
        self.assertTrue(_client.decode_sse(
            [{"choices": [{"delta": {"tool_calls": [{"function": None}]}}]}])["ok"])
        self.assertEqual(_client.decode_sse([{"choices": [{"delta": 1}]}])["code"],
                         "llm_bad_payload")
        self.assertEqual(_client.decode_sse(
            [{"choices": [{"delta": {"content": 1}}]}])["code"], "llm_bad_payload")
        self.assertEqual(_client.decode_sse(
            [{"choices": [{"delta": {"tool_calls": 1}}]}])["code"],
            "llm_bad_payload")
        self.assertEqual(_client.decode_sse(
            [{"choices": [{"delta": {"tool_calls": [1]}}]}])["code"],
            "llm_bad_payload")
        self.assertEqual(_client.decode_sse(
            [{"choices": [{"delta": {"tool_calls": [{"index": []}]}}]}])["code"],
            "llm_bad_payload")
        self.assertEqual(_client.decode_sse(
            [{"choices": [{"delta": {"tool_calls": [{"function": 1}]}}]}])["code"],
            "llm_bad_payload")
        self.assertEqual(_client.decode_sse(
            [{"choices": [{"delta": {"tool_calls": [
                {"function": {"arguments": 1}}]}}]}])["code"],
            "llm_bad_payload")
        out = _client.decode_sse([
            {"choices": [{"delta": {"content": "a", "tool_calls": [
                {"index": 0, "id": "i", "function": {"name": "n", "arguments": "{}"}}]},
                "finish_reason": "stop"}]},
            {"choices": [{"delta": {"content": "b", "tool_calls": [
                {"index": 0, "function": {"name": "n2"}},
                {"index": 1, "function": {"arguments": "x"}},
                {"index": 1, "function": {"name": "m"}},
                {"index": 2, "function": {}}]}}]},
        ])
        self.assertTrue(out["ok"])
        self.assertEqual(out["content"], "ab")
        self.assertEqual(out["tool_calls"][0]["function"]["name"], "n2")
        self.assertEqual(out["tool_calls"][1]["id"], "call_1")

    def test_wire(self):
        out = _client.wire({"headers": {"X-Api-Key": "k", "Authorization": "a",
                                        "token": "t", "Other": "o"},
                            "payload": {"model": "m"}, "stream": True})
        self.assertEqual(out["headers"]["Other"], "o")
        self.assertIn("***", out["headers"].values())
        self.assertEqual(out["method"], "POST")
        self.assertEqual(out["response"], "")
        self.assertTrue(out["stream"])


class AuthTest(unittest.TestCase):
    def ctx(self, **cfg):
        c = Ctx()
        c.cfg["server"] = cfg.get("server") or cfg or {"auth": {"enabled": False}}
        return c

    def handlers(self, ctx):
        auth.setup(ctx)
        return {call.args[0]: call.args[1] for call in ctx.api.register.call_args_list}

    def test_setup_status_verify(self):
        ctx = self.ctx(server={"auth": {"enabled": False}, "token": ""})
        with mock.patch.object(auth, "_default_warning", side_effect=RuntimeError("x")):
            self.handlers(ctx)
        hs = self.handlers(ctx)
        self.assertTrue(hs["auth.verify"](ctx, {}).get("allow"))
        self.assertEqual(hs["auth.status"](ctx, {})["warning"], "")
        ctx.cfg["server"] = {"token": "legacy"}
        self.assertEqual(hs["auth.verify"](ctx, {"token": "legacy"})["mode"], "legacy")
        self.assertEqual(hs["auth.verify"](ctx, {"token": "x"})["reason"], "unauthorized")
        ctx.cfg["server"] = {"auth": {"enabled": True}}
        self.assertEqual(hs["auth.verify"](ctx, {"token": "../x"})["reason"], "unauthorized")
        ctx.cfg["auth_paths"] = {"session": ""}
        ctx.routes["config.get"] = lambda p: ({"value": ""} if p.get("key") == "auth.paths"
                                               else {"value": ctx.cfg["server"].get("auth")})
        self.assertEqual(hs["auth.verify"](ctx, {"token": "ok"})["reason"], "unauthorized")
        ctx.routes["config.get"] = lambda p: ({"value": {"session": "auth/{token}.yaml"}}
                                               if p.get("key") == "auth.paths"
                                               else {"value": ctx.cfg["server"].get("auth")})
        ctx.store_exc = True
        self.assertEqual(hs["auth.verify"](ctx, {"token": "ok"})["reason"], "unauthorized")
        ctx.store_exc = False
        hs2 = self.handlers(ctx)
        self.assertEqual(hs2["auth.verify"](ctx, {"token": "ok"})["allow"], True)
        ctx.routes["store.read"] = lambda p: {"exists": True, "value": {"token": "t"}}
        hs3 = self.handlers(ctx)
        self.assertEqual(hs3["auth.verify"](ctx, {"token": "ok"})["allow"], False)
        ctx.routes["auth.build_session"] = lambda p: {"token": "t"}
        ctx.routes["auth.session_view"] = lambda p: {"token": "t"}
        hs4 = self.handlers(ctx)
        ctx.cfg["server"] = {"auth": {"enabled": True, "username": "u"}}
        self.assertTrue(hs4["auth.status"](ctx, {})["enabled"])
        ctx.cfg["server"] = {"auth": {"enabled": True}}
        with mock.patch.object(auth, "_default_warning", side_effect=RuntimeError("x")):
            self.assertFalse(hs4["auth.status"](ctx, {})["default_password"])
        with mock.patch.object(auth, "_default_warning",
                               return_value={"default": True, "reason": "empty"}):
            self.assertTrue(hs4["auth.status"](ctx, {})["default_password"])
        self.assertEqual(hs4["auth.session_path"](ctx, {"token": "t"})["path"],
                         "auth/t.yaml")
        self.assertEqual(hs4["auth.session_path"](
            ctx, {"token": "t", "paths": {"session": "x/{token}.yaml"}})["path"],
            "x/t.yaml")
        ctx.routes["store.read"] = lambda p: {"exists": False, "value": None}
        self.assertEqual(hs4["auth.verify"](ctx, {"token": "ok"})["reason"], "unauthorized")

    def test_guard_cfg_check(self):
        ctx = self.ctx(server={"auth": {"login_guard": {"max_failures": "x",
                                                         "window_seconds": 0,
                                                         "max_entries": 99999,
                                                         "enabled": False}}})
        cfg = auth._guard_cfg(ctx)
        self.assertFalse(cfg["enabled"])
        self.assertEqual(cfg["max_failures"], 5)
        self.assertEqual(cfg["window_seconds"], 1)
        self.assertEqual(cfg["max_entries"], 10000)
        ctx.cfg["server"] = {"auth": {"login_guard": "x"}}
        self.assertTrue(auth._guard_cfg(ctx)["enabled"])
        ctx.cfg["server"] = {"auth": {"login_guard": {"enabled": True}}}
        out = auth._guard_check(ctx, {"username": "u", "peer": "p"})
        self.assertFalse(out["blocked"])
        self.assertEqual(out["keys"], apure.throttle_keys({"username": "u",
                                                            "peer": "p"})["keys"])
        with mock.patch.object(auth._pure, "throttle_check",
                               return_value={"blocked": True, "retry_after": 3}):
            self.assertTrue(auth._guard_check(ctx, {"peer": "p"})["blocked"])

    def test_throttle(self):
        ctx = self.ctx(server={"auth": {"login_guard": {"enabled": True}}})
        ctx.throttle = {"a": {"failures": 0, "last": 0}}
        self.assertEqual(auth._throttle_mutate(ctx, [], True)["entries"], ctx.throttle)
        out = auth._throttle_mutate(ctx, ["k"], False)
        self.assertTrue(out["entries"])
        ctx.throttle = {"k": {"failures": 5, "last": 10}}
        ctx.cas_seq = [{"ok": False, "conflict": True}, {"ok": True}]
        self.assertNotIn("error", auth._throttle_mutate(ctx, ["k"], False))
        ctx.cas_seq = [{"ok": False, "code": "bad"}]
        self.assertEqual(auth._throttle_mutate(ctx, ["k"], False)["error"], "bad")
        ctx.cas_seq = [{"ok": False, "conflict": True}] * 8
        self.assertEqual(auth._throttle_mutate(ctx, ["k"], False)["error"],
                         "guard_conflict_exhausted")
        ctx.throttle = []
        self.assertEqual(auth._throttle_read(ctx), {})
        self.assertFalse(auth._guard_cfg(ctx)["enabled"] is False)

    def test_login_change(self):
        ctx = self.ctx(server={"auth": {"enabled": True,
                                             "login_guard": {"enabled": False},
                                             "salt": "s", "username": "u",
                                             "password_hash": "h", "ttl": "x"}})
        hs = self.handlers(ctx)
        ctx.cfg["server"]["auth"]["login_guard"] = {"enabled": True}
        with mock.patch.object(auth._pure, "throttle_check",
                               return_value={"blocked": True, "retry_after": 1}):
            self.assertEqual(auth._route_login(ctx, {})["code"], "too_many_attempts")
        ctx.cfg["server"]["auth"]["login_guard"] = {"enabled": False}
        ctx.routes["auth.credentials_ok"] = lambda p: {"ok": False}
        self.assertEqual(auth._route_login(ctx, {})["code"], "bad_credentials")
        ctx.cfg["server"]["auth"]["login_guard"] = {"enabled": True}
        with mock.patch.object(auth, "_throttle_mutate",
                               return_value={"error": "e"}):
            self.assertEqual(auth._route_login(ctx, {})["code"], "login_guard_unavailable")
        with mock.patch.object(auth, "_throttle_mutate",
                               return_value={"blocked": True, "retry_after": 2}):
            self.assertEqual(auth._route_login(ctx, {})["retry_after"], 2)
        ctx.cfg["server"]["auth"]["login_guard"] = {"enabled": False}
        ctx.routes["auth.credentials_ok"] = lambda p: {"ok": True}
        out = auth._route_login(ctx, {})
        self.assertEqual(out["token"], "t")
        ctx.cfg["server"]["auth"]["ttl"] = 100
        self.assertEqual(auth._route_login(ctx, {})["token"], "t")
        ctx.cfg["server"]["auth"]["ttl"] = "x"
        self.assertEqual(out["effects"][0]["path"], "auth/t.yaml")
        ctx.cfg["server"]["auth"]["login_guard"] = {"enabled": True}
        with mock.patch.object(auth, "_throttle_mutate", return_value={"error": "e"}):
            self.assertEqual(auth._route_login(ctx, {})["code"],
                             "login_guard_unavailable")
        ctx.cfg["server"]["auth"]["login_guard"] = {"enabled": False}
        ctx.routes["config.set_value"] = lambda p: {"value": 1}
        ctx.routes["auth.password_check"] = lambda p: {"ok": False, "code": "c",
                                                        "error": "e"}
        self.assertEqual(auth._route_change_password(ctx, {})["code"], "c")
        ctx.routes["auth.password_check"] = lambda p: {"ok": True}
        self.assertEqual(auth._route_change_password(ctx, {})["username"], "u")
        self.assertEqual(auth._too_many(1)["message"], "登录失败次数过多，请 1 分钟后再试")


class AuthPureTest(unittest.TestCase):
    def test_token_default_password(self):
        self.assertTrue(apure.valid_token({"token": "a_b-1"})["ok"])
        self.assertFalse(apure.valid_token({"token": "../x"})["ok"])
        self.assertFalse(apure.default_password_state({"auth": {}})["default"])
        self.assertEqual(apure.default_password_state(
            {"auth": {"enabled": True}})["reason"], "password_hash_empty")
        self.assertEqual(apure.default_password_state(
            {"auth": {"enabled": True, "username": "admin", "password_hash": "h"},
             "weak_digest": "h"})["reason"], "default_credentials")
        self.assertFalse(apure.default_password_state(
            {"auth": {"enabled": True, "username": "u", "password_hash": "h"},
             "weak_digest": "h"})["default"])

    def test_credentials(self):
        for p in ({}, {"username": "u"}, {"username": "u", "expect_username": "u"},
                  {"username": "u", "expect_username": "u", "digest": "d"}):
            self.assertFalse(apure.credentials_ok(p)["ok"])
        self.assertFalse(apure.credentials_ok({"username": "u", "expect_username": "x",
                                               "digest": "d", "expect_hash": "h"})["ok"])
        self.assertFalse(apure.credentials_ok({"username": "u", "expect_username": "u",
                                               "digest": "x", "expect_hash": "h"})["ok"])
        self.assertTrue(apure.credentials_ok({"username": "u", "expect_username": "u",
                                              "digest": "h", "expect_hash": "h"})["ok"])

    def test_change_password(self):
        self.assertEqual(apure.change_password({})["code"], "bad_old_password")
        self.assertEqual(apure.change_password(
            {"expect_hash": "h", "old_digest": "x"})["code"], "bad_old_password")
        self.assertEqual(apure.change_password(
            {"expect_hash": "h", "old_digest": "h"})["code"], "weak_password")
        self.assertEqual(apure.change_password(
            {"expect_hash": "h", "old_digest": "h", "new_digest": "a"})["code"],
            "confirm_mismatch")
        self.assertTrue(apure.change_password(
            {"expect_hash": "h", "old_digest": "h", "new_digest": "a",
             "confirm_digest": "a"})["ok"])

    def test_session(self):
        self.assertEqual(apure.build_session({"issued": 1, "ttl": "x"})["expires"], 1)
        self.assertEqual(apure.build_session({"issued": 1, "ttl": 2})["expires"], 3)
        self.assertEqual(apure.session_valid({})["reason"], "no_record")
        self.assertEqual(apure.session_valid({"record": {"token": "t"}})["reason"],
                         "no_expiry")
        self.assertEqual(apure.session_valid(
            {"record": {"token": "t", "expires": True}})["reason"], "no_expiry")
        self.assertEqual(apure.session_valid(
            {"record": {"token": "t", "expires": "x"}})["reason"], "bad_expiry")
        self.assertTrue(apure.session_valid(
            {"record": {"token": "t", "expires": 10}, "now": 1})["valid"])
        self.assertTrue(apure.session_valid(
            {"record": {"token": "t", "expires": 1}, "now": 1})["expired"])
        self.assertEqual(apure.session_view({"record": {"token": "t"}})["token"], "t")
        self.assertEqual(apure.session_path({"paths": {}, "token": "t"})["path"], "")
        self.assertEqual(apure.session_path(
            {"paths": {"session": "a/{token}.yaml"}, "token": "t"})["path"], "a/t.yaml")

    def test_throttle(self):
        self.assertEqual(apure.throttle_keys({"peer": "p", "username": "u"})["keys"],
                         ["ip:p", "pair:p|u"])
        self.assertEqual(apure.throttle_keys({"username": "u"})["keys"], ["user:u"])
        self.assertEqual(apure.throttle_keys({})["keys"], [])
        entries = {"ip:p": {"lock_until": 10}, "bad": "x", "badnum": {"lock_until": "x"}}
        out = apure.throttle_check({"entries": entries, "keys": ["bad", "badnum", "ip:p"],
                                    "now": 5})
        self.assertTrue(out["blocked"])
        self.assertFalse(apure.throttle_check({"entries": [], "keys": [], "now": 5})["blocked"])
        cfg = {"max_failures": 2, "window_seconds": 10, "lock_seconds": 20,
               "max_entries": 2}
        self.assertFalse(apure.throttle_update(
            {"entries": {"a": {"failures": 1}}, "keys": ["a"], "now": 3,
             "cfg": cfg, "success": True})["blocked"])
        self.assertFalse(apure.throttle_update(
            {"entries": {"a": {"failures": "x"}}, "keys": ["a"], "now": 3,
             "cfg": cfg})["blocked"])
        out = apure.throttle_update(
            {"entries": {"a": {"failures": 1, "first": "x", "last": 0}}, "keys": ["a"],
             "now": 100, "cfg": cfg})
        self.assertTrue(out["blocked"])
        out = apure.throttle_update(
            {"entries": {"a": {"failures": 1, "first": 1, "last": 1}}, "keys": ["a"],
             "now": 100, "cfg": cfg})
        self.assertEqual(out["entries"]["a"]["failures"], 1)
        out = apure.throttle_update({"entries": {"a": {"failures": 1}}, "keys": ["a"],
                                     "now": 3, "cfg": cfg})
        self.assertTrue(out["blocked"])
        self.assertEqual(apure.throttle_update(
            {"entries": {"a": "x", "b": {"last": "x"}, "c": {"last": 0, "lock_until": 0}},
             "keys": [], "now": 1000, "cfg": {"max_entries": 1}})["entries"], {})
        out = apure.throttle_update(
            {"entries": {"a": {"last": 999}, "b": {"last": 998}, "c": {"last": 997}},
             "keys": [], "now": 1000, "cfg": {"max_entries": 2}})
        self.assertEqual(len(out["entries"]), 2)


if __name__ == "__main__":
    unittest.main()
