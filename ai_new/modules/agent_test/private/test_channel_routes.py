"""频道模块路由单测：装配、读写游标、幂等发消息、网页回复闭环。"""
import asyncio
import json
import unittest
from types import SimpleNamespace

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))

from ai_new.modules.agent.channel import (_cfg_paths, _msg_tpl, _read_rows, _route_post,
                                          _route_read_since, _route_read_tail, _route_reply, setup)
from ai_new.modules.agent.channel.private import _pure


class ApiError(Exception):
    def __init__(self, message, code="E", status=500):
        super().__init__(message)
        self.message = message
        self.code = code
        self.status = status


class FakeApi:
    def __init__(self, text="", cfg=None, claim=None):
        self.text = text
        self.cfg = {"logs.paths": {"channel": "channels/{id}.jsonl"},
                    "channel.default_limit": 5, "channel.max_limit": 20}
        self.cfg.update(cfg or {})
        self.claim = claim
        self.registered = []
        self.settled = []
        self.claims = []
        self.encoded = []
        self.effects = [{"kind": "write", "module": "agent/logs"}]

    def register(self, name, fn, desc=None, module=None, stream=False):
        self.registered.append((name, stream))

    async def acall(self, name, payload=None, caller=None):
        if name == "channel.read_tail":
            return {"messages": [{"role": "assistant", "content": "旧答"}]}
        if name == "channel.post":
            return {"ok": True, "posted": payload}
        raise AssertionError(name)

    def call(self, name, payload=None, caller=None):
        p = payload or {}
        if name.startswith("channel."):
            return getattr(_pure, name.split(".", 1)[1])(p)
        if name == "config.get":
            return {"value": self.cfg.get(p.get("key"))}
        if name == "store.read_text":
            return {"value": self.text}
        if name == "store.read":
            return {"value": {"llm_failed": "上游失败：{error}"}}
        if name == "store.id":
            return {"id": p.get("value") or "default"}
        if name == "store.claim":
            self.claims.append(p)
            return self.claim
        if name == "store.settle":
            self.settled.append(p)
            return {"ok": True}
        if name == "clock.now":
            return {"ts": 1000}
        if name == "codec.json_decode":
            try:
                return {"ok": True, "value": json.loads(p.get("text"))}
            except Exception as exc:  # noqa: BLE001
                return {"ok": False, "error": str(exc)}
        if name == "codec.json_encode":
            text = json.dumps(p.get("value"), ensure_ascii=False)
            self.encoded.append(text)
            return {"text": text}
        if name == "logs.record":
            return {"effects": self.effects}
        raise AssertionError("unexpected api.call %s" % name)


class FakeHooks:
    def __init__(self):
        self.points = []
        self.emits = []

    def point(self, name, fields, defer=False):
        self.points.append((name, fields, defer))

    def emit(self, name, payload):
        self.emits.append((name, payload))


def make_ctx(text="", cfg=None, claim=None, hooks=True, demand=None):
    api = FakeApi(text, cfg, claim)
    ctx = SimpleNamespace(api=api, ApiError=ApiError,
                          hooks=FakeHooks() if hooks else None,
                          demand_engine=SimpleNamespace(run_callable=lambda name, inp: (
                              demand if demand is not None else {"result": {"items": [1], "cursor": inp["cursor"]}})),
                          runtime=SimpleNamespace(acall=None))
    return ctx, api


ROWS = [{"seq": 1, "role": "user", "content": "a"},
        {"seq": 2, "role": "assistant", "content": "b"}]
BROKEN = "{不是 JSON"


def dump(rows):
    return "\n".join(json.dumps(r) for r in rows)


class SetupTest(unittest.TestCase):
    def test_setup_registers_and_marks_stream(self):
        ctx, api = make_ctx()
        self.assertTrue(setup(ctx))
        names = [n for n, _ in api.registered]
        self.assertEqual(len(names), 10)
        self.assertEqual(api.registered[-1], ("channel.watch", True))
        self.assertEqual(ctx.hooks.points[0][0], "channel.posted")
        self.assertTrue(ctx.hooks.points[0][2])

    def test_watch_delegates_to_since_with_defaults(self):
        ctx, api = make_ctx()
        setup(ctx)
        watch = dict(api.registered)  # 只取名字集合用不了函数，直接走注册表外的引用
        self.assertIn("channel.watch", list(watch))
        fn = _watch_of(ctx)
        self.assertEqual(fn(ctx, {}), {"items": [1], "cursor": 0})
        self.assertEqual(fn(ctx, {"cursor": 3, "channel": "c"}), {"items": [1], "cursor": 3})

    def test_watch_falls_back_when_no_result(self):
        ctx, api = make_ctx()
        ctx.demand_engine = SimpleNamespace(run_callable=lambda n, i: {})
        self.assertEqual(_watch_of(ctx)(ctx, {"cursor": 2}), {"items": [], "cursor": 2})

    def test_msg_tpl(self):
        ctx, api = make_ctx()
        self.assertEqual(_msg_tpl(ctx), {"llm_failed": "上游失败：{error}"})


def _watch_of(ctx):
    """从 setup 的注册表里取真实的 watch 实现：注册时闭包被吞，重新装配一次并截获。"""
    captured = {}

    class RecApi(FakeApi):
        def register(self, name, fn, desc=None, module=None, stream=False):
            captured[name] = fn

    ctx.api = RecApi(ctx.api.text, ctx.api.cfg)
    setup(ctx)
    return captured["channel.watch"]


class ReadRowsTest(unittest.TestCase):
    def test_template_path_and_filter_bad_rows(self):
        ctx, api = make_ctx(text=dump(ROWS) + "\n" + BROKEN)
        self.assertEqual(_read_rows(ctx, "c1"), ROWS)
        self.assertEqual(api.cfg["logs.paths"], {"channel": "channels/{id}.jsonl"})

    def test_no_template_uses_channel_id(self):
        ctx, api = make_ctx(text=dump(ROWS), cfg={"logs.paths": None})
        self.assertEqual(_read_rows(ctx, "c1"), ROWS)

    def test_blank_lines_ignored(self):
        ctx, api = make_ctx(text="\n\n" + dump(ROWS[:1]) + "\n\n")
        self.assertEqual(_read_rows(ctx, "c1"), ROWS[:1])

    def test_cfg_paths(self):
        ctx, api = make_ctx()
        self.assertEqual(_cfg_paths(ctx), {"channel": "channels/{id}.jsonl"})


class PureChannelsTest(unittest.TestCase):
    def test_channels_strips_extension(self):
        got = _pure.channels({"rows": [
            {"path": "logs/channels/c1.jsonl", "text": "a\n\nb\n"},
            {"path": "logs/channels/c2", "text": ""},
        ]})
        self.assertEqual(got["channels"], [{"channel": "c1", "count": 2, "last_ts": None},
                                          {"channel": "c2", "count": 0, "last_ts": None}])

    def test_split_and_make_defaults(self):
        self.assertEqual(_pure.split({"text": " a\n \nb\n"})["lines"], [" a", "b"])
        self.assertEqual(_pure.split({})["lines"], [])
        got = _pure.make({})
        self.assertEqual((got["channel"], got["seq"], got["role"], got["ts"]), ("default", 1, "user", 0))
        self.assertEqual(got["id"], "default-000001")
        self.assertEqual(_pure.make({"rows": [1, 2], "channel": "c", "ts": "9"})["ts"], 9)

    def test_tail_and_since(self):
        rows = [{"seq": 1, "role": "u", "content": "a"}, "bad",
               {"seq": 2, "role": "a", "content": "b"}]
        got = _pure.tail({"rows": rows, "limit": None, "default_limit": 1, "max_limit": 5})
        self.assertEqual(got["cursor"], 2)
        self.assertEqual([m["content"] for m in got["messages"]], ["b"])
        self.assertEqual(_pure.tail({"rows": [], "default_limit": 2, "max_limit": 5})["cursor"], 0)
        self.assertEqual(len(_pure.tail({"rows": rows, "limit": "99", "default_limit": 1,
                                        "max_limit": 5})["messages"]), 2)
        since_rows = _pure.since({"rows": rows, "cursor": 1})
        self.assertEqual(since_rows["cursor"], 2)
        self.assertEqual(_pure.since({"rows": rows})["cursor"], 2)
        self.assertEqual(_pure.since({"rows": rows, "cursor": 2}), {"items": [], "cursor": 2})


class PostTest(unittest.TestCase):
    def test_plain_post_appends_and_emits(self):
        ctx, api = make_ctx(text=dump(ROWS) + "\n" + BROKEN)
        got = _route_post(ctx, {"channel": "c1", "role": "user", "content": "hi"})
        self.assertEqual(got["channel"], "c1")
        self.assertEqual(got["seq"], 3)
        self.assertEqual(got["id"], "c1-000003")
        self.assertEqual(got["effects"][0]["kind"], "append_text")
        self.assertEqual(got["effects"][0]["text"].strip(), api.encoded[-1])
        self.assertEqual(ctx.hooks.emits[0][0], "channel.posted")
        self.assertEqual(ctx.hooks.emits[0][1]["seq"], 3)

    def test_no_hooks_still_posts(self):
        ctx, api = make_ctx(text=dump(ROWS), hooks=False)
        got = _route_post(ctx, {"channel": "c1"})
        self.assertEqual(got["role"], "user")

    def test_no_channel_template_falls_back_to_id(self):
        ctx, api = make_ctx(cfg={"logs.paths": {}})
        got = _route_post(ctx, {"channel": "c1"})
        self.assertEqual(got["effects"][0]["path"], "c1")

    def test_idem_claim_then_settle(self):
        ctx, api = make_ctx(text=dump(ROWS), claim={"claimed": True})
        got = _route_post(ctx, {"channel": "c1", "idem_key": "k1"})
        self.assertEqual(api.claims[0]["key"], "k1")
        self.assertEqual(api.claims[0]["scope"], "c1")
        self.assertEqual(api.settled[0]["key"], "k1")
        self.assertEqual(api.settled[0]["result_digest"], "c1|3")
        self.assertEqual(got["seq"], 3)

    def test_idem_done_reuses_result(self):
        ctx, api = make_ctx(claim={"claimed": False, "status": "done", "result_digest": "d"})
        got = _route_post(ctx, {"channel": "c1", "idem_key": "k1"})
        self.assertEqual(got, {"channel": "c1", "reused": True, "digest": "d"})

    def test_idem_inflight_conflicts(self):
        ctx, api = make_ctx(claim={"claimed": False, "status": "running"})
        with self.assertRaises(ApiError) as cm:
            _route_post(ctx, {"channel": "c1", "idem_key": "k1"})
        self.assertEqual(cm.exception.code, "idem_running")
        self.assertEqual(cm.exception.status, 409)


class ReadRoutesTest(unittest.TestCase):
    def test_read_since(self):
        ctx, api = make_ctx(text=dump(ROWS) + "\n" + BROKEN)
        got = _route_read_since(ctx, {"channel": "c1", "cursor": 1})
        self.assertEqual([x["seq"] for x in got["items"]], [2])
        self.assertEqual(got["cursor"], 2)

    def test_read_since_empty_cursor_zero(self):
        ctx, api = make_ctx(text="")
        self.assertEqual(_route_read_since(ctx, {"channel": "c1"}), {"items": [], "cursor": 0})

    def test_read_tail_defaults_from_config(self):
        ctx, api = make_ctx(text=dump(ROWS) + "\n" + BROKEN)
        got = _route_read_tail(ctx, {"channel": "c1", "limit": 9})
        self.assertEqual([m["content"] for m in got["messages"]], ["a", "b"])

    def test_read_tail_honours_explicit_limits(self):
        ctx, api = make_ctx(text=dump(ROWS) + "\n" + BROKEN)
        got = _route_read_tail(ctx, {"channel": "c1", "limit": None,
                                     "default_limit": 1, "max_limit": 1})
        self.assertEqual([m["content"] for m in got["messages"]], ["b"])


class ReplyTest(unittest.TestCase):
    def test_non_user_role_skipped(self):
        ctx, api = make_ctx()
        self.assertEqual(asyncio.run(_route_reply(ctx, {"role": "assistant"})),
                         {"ok": True, "skipped": True})

    def test_assistant_reply_posted(self):
        ctx, api = make_ctx()
        ctx.runtime = SimpleNamespace(acall=_answer({"ok": True, "content": "好"}))
        got = asyncio.run(_route_reply(ctx, {"role": "user", "channel": "c1", "content": "问"}))
        self.assertEqual(got["posted"]["role"], "assistant")
        self.assertEqual(got["posted"]["content"], "好")

    def test_llm_failure_becomes_system_message(self):
        ctx, api = make_ctx()
        ctx.runtime = SimpleNamespace(acall=_answer({"ok": False, "error": "超时"}))
        got = asyncio.run(_route_reply(ctx, {"role": "user", "channel": "c1"}))
        self.assertEqual(got["posted"]["role"], "system")
        self.assertEqual(got["posted"]["content"], "上游失败：超时")

    def test_llm_failure_without_template(self):
        ctx, api = make_ctx()
        api.call = _no_tpl_call(api)
        ctx.runtime = SimpleNamespace(acall=_answer(None))
        got = asyncio.run(_route_reply(ctx, {"role": "user"}))
        self.assertEqual(got["posted"]["content"], "")


def _answer(value):
    async def acall(demand, payload=None):
        return value
    return acall


def _no_tpl_call(api):
    orig = api.call

    def call(name, payload=None, caller=None):
        if name == "store.read":
            return {"value": {}}
        return orig(name, payload, caller)
    return call


if __name__ == "__main__":
    unittest.main()
