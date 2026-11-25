"""纯函数批测：运维/项目/待办/图/日志/编解码/频道/沙箱/Windows 路径。"""
import io
import json
import os
import tempfile
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))
import wave
from pathlib import Path
from unittest import mock

from ai_new.modules.agent_common.ops.private import _pure as ops
from ai_new.modules.agent.projects.private import _pure as proj
from ai_new.modules.agent.todos.private import _pure as todo
from ai_new.modules.agent_common.graph.private import _pure as graph
from ai_new.modules.agent.logs.private import _pure as logs
from ai_new.modules.agent_common.codec.private import _codec as codec
from ai_new.modules.agent.channel.private import _pure as channel
from ai_new.modules.agent.sandbox.private import _pure as sandbox
from ai_new.modules.agent.sandbox.private import _winpath as winpath
from ai_new.modules.agent_common.archive.private import _backend as archive
from ai_new.modules.agent_common.config.private import _loader as config


class OpsTest(unittest.TestCase):
    def test_assemble(self):
        p = {
            "sessions": {"result": {"items": [{"id": "s", "secret": "x"}]}},
            "tickets": {"result": {"items": [{"id": "t", "title": "T"}]}},
            "knowledge": {"result": {"counts": {"docs": 1}}},
            "artifacts": {"result": {"files": 2, "bytes": 3, "chars": 4}},
            "library": {"result": {"counts": {"roles": 1}}},
            "projects": {"result": {"items": [{"id": "p", "archived": True},
                                              "bad"]}},
            "tools": {"result": {"total": 2, "ready": 1, "x": 0}},
            "docs": {"result": {"counts": {"n": 1}, "items": [{"name": "d"}]}},
            "config": {"server": {"host": "h", "port": 1,
                                  "auth": {"enabled": True}},
                       "llm": {"base_url": "u"}},
        }
        out = ops.assemble(p)
        self.assertEqual(out["projects"]["result"]["archived"], ["p"])
        self.assertEqual(out["tools"]["result"]["total"], 2)
        self.assertEqual(out["docs"]["result"]["counts"], {"n": 1})
        self.assertEqual(ops.assemble(None)["config"]["server"]["auth"]["enabled"], None)
        self.assertEqual(ops._source_result({"result": "x"}), {})
        self.assertEqual(ops._source_result("x"), {})
        self.assertEqual(ops._brief_items(None, ("id",)), [])
        self.assertEqual(ops._brief_items([1], ("id",)), [])
        cfg = ops._config_overview({"server": {"auth": "x"}, "llm": 1})
        self.assertIsNone(cfg["server"]["host"])

    def test_records(self):
        self.assertEqual(ops.record({"data": {"a": 1, "b": {"x": 1}}})["a"], 1)
        self.assertEqual(ops.record({"data": {"b": [1]}})["b"], "[1]")
        self.assertEqual(ops.record({"data": "x"})["level"], "info")
        self.assertEqual(ops.line({})["line"], "")
        self.assertEqual(ops.events({"rows": [{"a": 1}, "x"]})["lines"], 2)
        self.assertEqual(ops.events({})["events"], [])
        spans = ops.spans_events({"rows": ["bad", {"name": "demand:x", "status": "ok",
                                                   "dur_ms": 1.2},
                                            {"name": "y", "status": "err"}]})
        self.assertEqual(spans["events"][0]["event"], "x")
        self.assertEqual(spans["events"][1]["level"], "err")
        self.assertEqual(ops.merge_events({"spans": [1], "legacy": [2, 3]})["events"], [1, 3, 2])
        self.assertEqual(ops.tail({"rows": [1, 2], "lines": 0})["rows"], [2])
        self.assertEqual(ops.export_path({})["path"], "exports/")
        self.assertEqual(ops.log_line({})["text"], "\n")


class ProjectsTest(unittest.TestCase):
    def test_shapes(self):
        self.assertEqual(proj.build({})["id"], "default")
        self.assertEqual(proj.build({"id": "x"})["name"], "x")
        self.assertEqual(proj.view({})["root"], "")
        self.assertEqual(proj.present({"rec": None, "tpl": "missing {id}"})["error"],
                         "missing ")
        self.assertEqual(proj.present({"rec": {"id": "p"}})["id"], "p")
        tree = proj.tree({"projects": [None, {"id": ""}, {"id": "p", "archived": True},
                                       {"id": "q"}],
                          "tickets": [None, {"id": "t0"},
                                      {"id": "t1", "project": "p", "status": "closed"},
                                      {"id": "t2", "project": "q", "status": "open"}]})
        self.assertEqual(tree["orphans"][0]["id"], "t0")
        self.assertEqual(tree["archived"][0]["counts"], {"total": 1, "open": 0, "closed": 1})
        self.assertEqual(tree["items"][0]["counts"], {"total": 1, "open": 1, "closed": 0})
        self.assertEqual(proj.screen({"rows": [None, {"x": 1}, {"id": "p"}]})["items"][0]["id"], "p")

    def test_guards(self):
        self.assertEqual(proj.guard_archive({"rec": {"archived": True}})["code"],
                         "already_archived")
        self.assertEqual(proj.guard_archive({"open_tickets": [1]})["code"], "open_tickets")
        self.assertEqual(proj.guard_archive({"open_tickets": [1], "tpl": {
            "open_tickets": "{n}:{ids}"}})["error"], "1:1")
        self.assertTrue(proj.guard_archive({"open_tickets": [0]})["ok"])
        self.assertEqual(proj.guard_writable({"rec": {"archived": True}})["code"],
                         "project_archived")
        self.assertTrue(proj.guard_writable({})["ok"])
        self.assertTrue(proj.archive({"rec": {"id": "p"}, "now": "n"})["archived"])
        self.assertEqual(proj.renamed({"rec": {"id": "a"}}), {
            "id": "a", "name": "a", "updated": ""})
        self.assertEqual(proj.rooted({"rec": {"id": "a"}, "root": "/r"})["root"], "/r")
        self.assertEqual(proj.missing({"id": "p", "tpl": "no {id}"})["error"], "no p")
        self.assertEqual(proj.conflict({"id": "p"})["code"], "exists")
        self.assertEqual(proj.deleted({})["id"], "")
        self.assertEqual(proj.record_path({"id": "p"}), {"path": "p"})

    def test_overrides(self):
        self.assertEqual(proj.override_parts({})["roles"], [])
        bad = proj.toggle_override({"kind": "x", "tpl": {"bad_kind": "bad {kind}"}})
        self.assertEqual(bad["error"], "bad x")
        self.assertEqual(proj.toggle_override({"kind": "roles", "id": " "})["code"],
                         "missing_id")
        rec = {"overrides": {"roles": ["a", "b"], "tools": []}}
        out = proj.toggle_override({"kind": "roles", "id": "a", "enabled": True,
                                    "rec": rec, "now": "n"})
        self.assertEqual(out["overrides"]["roles"], ["b"])
        out = proj.toggle_override({"kind": "roles", "id": "c", "enabled": False,
                                    "rec": rec})
        self.assertEqual(out["overrides"]["roles"], ["a", "b", "c"])
        out = proj.toggle_override({"kind": "tools", "id": "x", "enabled": False,
                                    "rec": rec, "cascade_roles": ["r1", "a"]})
        self.assertEqual(out["overrides"]["roles"], ["a", "b", "r1"])
        out = proj.toggle_override({"kind": "tools", "id": "y", "enabled": False,
                                    "rec": rec})
        self.assertEqual(out["updated"], "")
        self.assertEqual(proj._clean_list(["a", "a", ""]), ["a"])
        rec2 = {"overrides": {"tools": ["x"]}}
        out = proj.toggle_override({"kind": "tools", "id": "x", "enabled": False,
                                    "rec": rec2, "cascade_roles": []})
        self.assertEqual(out["overrides"]["tools"], ["x"])


class TodosTest(unittest.TestCase):
    def test_norm(self):
        self.assertIsNone(todo._item({"text": ""}, 1))
        self.assertEqual(todo._item("x", 1)["id"], "t1")
        self.assertEqual(todo._norm([{"id": "t2", "text": "a"},
                                     {"id": "t2", "text": "b"}], 5)[1]["id"], "t2x")
        self.assertEqual(todo._norm([{"text": "a"}, {"text": "b"}], None), [])
        self.assertEqual(todo._norm([{"text": "a"}], "bad"), [])
        self.assertEqual(todo._next_id([None, {"id": "t9"}, {"id": "x"}]), "t10")
        self.assertEqual(todo.counts([None, {"status": "x"}]), {
            "total": 2, "pending": 1, "doing": 0, "done": 0})

    def test_apply(self):
        base = [{"id": "t1", "text": "a", "status": "pending", "note": ""}]
        self.assertEqual(todo.apply_ops({"todos": base})["action"], "list")
        self.assertEqual(todo.apply_ops({"todos": base, "limit": 5, "limit": 5,
                                         "args": {"action": "clear"}})["changed"], True)
        self.assertEqual(todo.apply_ops({"args": {"action": "clear"}})["changed"], False)
        self.assertFalse(todo.apply_ops({"args": {"action": "replace",
                                                  "items": base}})["changed"])
        self.assertEqual(todo.apply_ops({"args": {"action": "add"}})["code"], "bad_request")
        out = todo.apply_ops({"todos": base, "limit": 5, "args": {
            "action": "add", "text": "b", "id": "t1", "status": "doing"}})
        self.assertEqual(out["todos"][-1]["id"], "t2")
        out = todo.apply_ops({"todos": [], "limit": 5, "args": {"action": "add", "text": "b"}})
        self.assertEqual(out["todos"][0]["id"], "t1")
        self.assertEqual(todo.apply_ops({"args": {"action": "update", "id": "x"}})["code"],
                         "not_found")
        out = todo.apply_ops({"todos": base, "limit": 5, "args": {"action": "update", "id": "t1",
                                                       "text": "z", "status": "done",
                                                       "note": None}})
        self.assertEqual(out["todos"][0]["note"], "")
        self.assertTrue(out["changed"])
        self.assertFalse(todo.apply_ops({"todos": base, "limit": 5, "args": {
            "action": "update", "id": "t1"}})["changed"])
        todo.apply_ops({"todos": base, "limit": 5,
                        "args": {"action": "update", "id": "t1", "note": "n"}})
        self.assertEqual(todo.apply_ops({"args": {"action": "remove", "id": "x"}})["code"],
                         "not_found")
        self.assertEqual(todo.apply_ops({"todos": base, "limit": 5, "args": {
            "action": "remove", "id": "t1"}})["todos"], [])
        self.assertEqual(todo.apply_ops({"args": {"action": "nope"}})["code"], "bad_request")
        self.assertEqual(todo._norm([{"text": ""}], 5), [])
        self.assertEqual(todo._item(1, 1)["id"], "t1")
        out = todo.apply_ops({"todos": base + [{"id": "t9", "text": "z", "status": "done"}],
                              "limit": 5, "args": {"action": "update", "id": "t1"}})
        self.assertEqual(len(out["todos"]), 2)

    def test_brief_context(self):
        self.assertEqual(todo.brief({"todos": []})["current"], "")
        self.assertEqual(todo.brief({"todos": [{"id": "t", "text": "a", "status": "doing"}]})
                         ["current"], "a")
        self.assertEqual(todo.context({}), {"message": None})
        self.assertEqual(todo.context({"todos": [{"id": "t", "text": "a"}], "limit": 5,
                                       "tpl": {}})["message"]["content"], "t [pending] a")
        msg = todo.context({"todos": [{"id": "t", "text": "a"}], "limit": 5,
                            "tpl": {"heading": "H", "row": "{id}/{status}/{text}",
                                    "hint": "tip"}})["message"]["content"]
        self.assertEqual(msg.splitlines(), ["H", "t/pending/a", "tip"])


class GraphTest(unittest.TestCase):
    def test_merge(self):
        out = graph.merge_branch_updates({
            "state": {"a": 1, "l": [1]},
            "updates": ["x", {"a": 2, "l": [1, 2]}, {"u": 1}],
            "policies": {"u": "union"}})
        self.assertEqual(out["state"]["a"], 2)
        self.assertEqual(out["state"]["l"], [1, 2])
        self.assertEqual(out["state"]["u"], [1])
        self.assertEqual(out["merged_keys"], ["a", "l", "u"])
        out = graph.merge_branch_updates({"state": {"c": 1}, "updates": [{"c": 2}],
                                          "policies": {"c": "conflict"}})
        self.assertEqual(out["conflicts"][0]["left"], 1)
        out = graph.merge_branch_updates({"updates": [{"c": 2}, {"c": 2}],
                                          "policies": {"c": "conflict"}})
        self.assertEqual(out["state"]["c"], 2)
        with self.assertRaises(ValueError):
            graph.merge_branch_updates({"updates": [{"a": 1}], "policies": {"a": "bad"}})
        self.assertEqual(graph._as_list(None), [])
        self.assertEqual(graph._as_list(1), [1])
        self.assertEqual(graph._default_policy([], 1), graph.APPEND)
        self.assertEqual(graph._gate_item_text("x"), "")

    def test_limit_gate(self):
        self.assertEqual(graph.step_limit({"steps": 3, "cap": 3})["outcome"],
                         graph.EXHAUSTED_CLOSE)
        self.assertEqual(graph.step_limit({})["remaining"], None)
        contract = {"s": {"id": "s", "gate": {"must": [{"id": "m", "text": "M"}],
                                              "forbid": [{"id": "f"}]}},
                    "bad": 1}
        self.assertEqual(graph._resolve_gate(contract, {"id": "f", "text": "F"})["id"], "f")
        self.assertEqual(graph._resolve_gate(contract, "m")["state"], "s")
        self.assertEqual(graph._resolve_gate(contract, "z")["state"], "")
        reasons = graph.gate_reasons({"contract": contract, "violations": ["f"],
                                      "missing": ["m", "z"]})["reasons"]
        self.assertEqual([r["kind"] for r in reasons], ["forbid", "must", "must"])
        self.assertEqual(reasons[0]["text"], "")

    def test_subprocess(self):
        out = graph.subprocess_checklist({"parent": {}, "refs": {}})
        self.assertEqual(out["ref"], "")
        out = graph.subprocess_checklist({"parent": {"ref": "r"}, "refs": {"x": []}})
        self.assertEqual(out["children"], [])
        out = graph.subprocess_checklist({
            "parent": {"ref": "r"},
            "refs": {"r": ["bad", {"id": "s", "gate": {"must": ["m", "m"],
                                                       "forbid": ["f"]}}]}})
        self.assertEqual(out["rollup_must"], ["m"])
        self.assertEqual(out["children"][0]["forbid"], ["f"])


class LogsTest(unittest.TestCase):
    def test_entries(self):
        self.assertEqual(logs.entry({})["category"], "log")
        rows = logs.index_upsert({"entries": ["bad", {"path": "a", "created": 1}],
                                  "entry": {"path": "a", "updated": 2, "name": "n"}})
        self.assertEqual(rows["entries"][0]["name"], "n")
        self.assertEqual(logs.index_upsert({"entries": ["bad"], "entry": {}})["entries"], [])
        self.assertEqual(logs.index_upsert({"entries": [{"path": "z"}],
                                            "entry": {"path": "a"}})["entries"][1]["path"], "a")
        self.assertEqual(logs.index_upsert({"entries": [], "entry": {"path": "n"}})
                         ["entries"][0]["path"], "n")
        self.assertEqual(logs._bad("c", "e")["code"], "c")
        self.assertEqual(logs.index_purge({"entries": ["bad", {"path": "a/x"},
                                                       {"path": "b"}], "prefix": "a/"})
                         ["entries"], [{"path": "b"}])
        self.assertEqual(logs.index_purge({"entries": [{"path": "a"}], "paths": ["a"]})
                         ["entries"], [])
        self.assertEqual(logs.index_purge({"entries": [{"path": "a"}], "prefix": "a"})
                         ["entries"], [])

    def test_group(self):
        out = logs.group({"entries": ["bad", {"path": "p", "layer": "public"},
                                      {"path": "t", "layer": "ticket", "ticket": "T1"},
                                      {"path": "o", "layer": "ticket", "ticket": "T2"},
                                      {"path": "x", "layer": "project", "project": "P"}],
                          "tickets": [None, {}, {"project": "P"},
                                      {"id": "T1", "project": "P", "title": "Title"}],
                          "tpl": {}})
        self.assertEqual(out["counts"], {"public": 1, "project": 1, "ticket": 2})
        self.assertEqual(out["items"][-1]["source"], "system")
        child = out["tree"][1]["children"][-1]
        self.assertEqual(child["label"], "Title")


class CodecTest(unittest.TestCase):
    def test_json_yaml(self):
        self.assertFalse(codec.json_encode({1})["ok"])
        self.assertFalse(codec.json_decode("{")["ok"])
        with mock.patch.object(codec.yaml, "dump", side_effect=TypeError("x")):
            self.assertFalse(codec.yaml_encode({})["ok"])
            self.assertFalse(codec.yaml_encode_flow({})["ok"])
        self.assertTrue(codec.yaml_encode({"a": 1})["ok"])
        self.assertTrue(codec.yaml_encode_flow({"a": 1})["ok"])
        self.assertFalse(codec.yaml_decode("{")["ok"])
        self.assertEqual(codec.json_decode(None)["value"], None)

    def test_sse_base64_digest(self):
        self.assertFalse(codec.sse_decode(1)["ok"])
        self.assertEqual(codec.sse_decode(b'data: {"a":1}\n')["items"], [{"a": 1}])
        self.assertEqual(codec.sse_decode("data: [DONE]\ndata: bad\nx")["items"], [])
        with mock.patch.object(codec.base64, "b64decode", side_effect=ValueError("x")):
            self.assertFalse(codec.base64_decode_bytes("x")["ok"])
            self.assertFalse(codec.hex_from_base64("x")["ok"])
        self.assertEqual(codec.base64_encode(b"a")["text"], "YQ==")
        with mock.patch.object(codec.base64, "b64encode", side_effect=ValueError("x")):
            self.assertFalse(codec.base64_encode("x")["ok"])
        self.assertFalse(codec.digest("x", "md5x")["ok"])
        class Bad:
            def __str__(self):
                raise TypeError("bad")
        self.assertFalse(codec.digest(Bad(), "md5")["ok"])
        self.assertTrue(codec.digest("x", "md5")["ok"])
        self.assertEqual(codec.nonce(1)["ok"], True)
        self.assertFalse(codec.nonce("x")["ok"])

    def test_hex_wave(self):
        out = codec.decode_hex("6869", max_bytes=1, size=2)
        self.assertEqual(out["text"], "h")
        self.assertTrue(out["truncated"])
        self.assertEqual(codec.decode_hex("ff")["encoding"], "binary")
        self.assertFalse(codec.decode_hex("zz")["ok"])
        self.assertFalse(codec.wave_decode("x")["ok"])
        self.assertFalse(codec.wave_decode(b"bad")["ok"])
        buf = io.BytesIO()
        with wave.open(buf, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(8000)
            w.writeframes(b"\x00\x00")
        self.assertEqual(codec.wave_decode(buf.getvalue())["rate"], 8000)
        fake = mock.Mock()
        fake.__enter__ = lambda s: s
        fake.__exit__ = lambda *a: None
        fake.getcomptype.return_value = "ULAW"
        with mock.patch.object(codec.wave, "Wave_read", return_value=fake):
            self.assertEqual(codec.wave_decode(b"x")["code"], "compressed_wav")


class ChannelSandboxTest(unittest.TestCase):
    def test_channel(self):
        self.assertEqual(channel.split({"text": "a\n \nb"})["lines"], ["a", "b"])
        self.assertEqual(channel.make({})["id"], "default-000001")
        self.assertEqual(channel.tail({"rows": ["x", {"seq": 1, "role": "u"}],
                                       "default_limit": "2", "max_limit": "5"})["cursor"], 1)
        self.assertEqual(channel.tail({"rows": [], "default_limit": "2",
                                       "max_limit": "5"})["cursor"], 0)
        self.assertEqual(channel.since({"cursor": 1, "rows": ["x", {"seq": 2}]})["cursor"], 2)
        rows = channel.channels({"rows": [{"path": "a/b.jsonl", "text": "1\n2"},
                                          {"path": "c", "text": ""}]})["channels"]
        self.assertEqual(rows[0], {"channel": "b", "count": 2, "last_ts": None})

    def test_sandbox(self):
        self.assertEqual(sandbox.describe()["weak"]["tier"], "weak")
        self.assertEqual(sandbox.validate_root("")["code"], "empty_root")
        self.assertEqual(sandbox.validate_root("x")["code"], "root_not_absolute")
        self.assertEqual(sandbox.validate_root("/a/../b")["code"], "traversal")
        self.assertEqual(sandbox.validate_root("/a/./b")["root"], "/a/b")
        self.assertEqual(sandbox.pick_tier({"tier": "strong"})["reason"], "policy_requested")
        self.assertEqual(sandbox.pick_tier({"untrusted_code": True})["tier"], "strong")
        self.assertEqual(sandbox.pick_tier({})["tier"], "weak")
        self.assertEqual(sandbox.plan("p", "weak", {})["code"], "empty_root")
        out = sandbox.plan("p", "strong", {"root": "/r"})
        self.assertEqual(out["cwd"], "/r")
        self.assertEqual(out["lock_path"], "/r/.locks/p.lock")
        self.assertIsNotNone(out["strong_wrap"])
        self.assertEqual(sandbox.guard_path("", "")["code"], "empty_root")
        self.assertEqual(sandbox.guard_path("/r", "")["code"], "empty_target")
        self.assertEqual(sandbox.guard_path("r", "/r")["code"], "root_not_absolute")
        self.assertEqual(sandbox.guard_path("/r", "r")["code"], "root_not_absolute")
        self.assertEqual(sandbox.guard_path("/r/../x", "/r")["code"], "traversal")
        self.assertEqual(sandbox.guard_path("/r", "/x")["code"], "escape")
        self.assertEqual(sandbox.guard_path("/r", "/r/a")["code"], "ok")
        self.assertEqual(sandbox.guard_path("C:\\r", "C:\\r", platform="nt")["code"], "ok")
        self.assertEqual(sandbox._posix_norm("/a/../b"), "/b")
        self.assertEqual(sandbox._posix_norm("/../x"), "/x")
        self.assertEqual(sandbox.plan("p", None, {"root": "/r"})["tier"], "weak")
        self.assertEqual(len(sandbox.mechanism_diff()["dimensions"]), 5)


class WinPathTest(unittest.TestCase):
    def test_prefix_segments(self):
        self.assertEqual(winpath.strip_long_prefix("\\\\?\\UNC\\s\\d")[0], "unc")
        self.assertEqual(winpath.strip_long_prefix("\\\\?\\C:\\x")[0], "drive")
        self.assertEqual(winpath.strip_long_prefix("C:\\x")[0], None)
        self.assertFalse(winpath.is_reserved_name(""))
        self.assertTrue(winpath.is_reserved_name("CON.txt"))
        self.assertTrue(winpath.is_reserved_name("com1"))
        self.assertFalse(winpath.is_reserved_name("COM10"))
        self.assertEqual(winpath.normalize_segment("A. "), "a")
        self.assertEqual(winpath.split_root("\\\\s\\d\\x")["canonical_root"], "//s/d")
        self.assertEqual(winpath.split_root("\\\\s")["kind"], "unc")
        self.assertEqual(winpath.split_root("C:/x/./y")["canonical_root"], "c:")
        self.assertEqual(winpath.split_root("\\\\?\\C:\\x")["drive"], "c:")
        self.assertEqual(winpath.split_root("\\\\?\\Q")["kind"], "relative")
        self.assertEqual(winpath.split_root("\\\\?\\C:\\x")["drive"], "c:")
        self.assertEqual(winpath.canonical("C:\\") , "c:")
        self.assertEqual(winpath.canonical("x/./y"), "x/y")

    def test_guards(self):
        self.assertEqual(winpath.guard_rel("")["code"], "empty_target")
        self.assertEqual(winpath.guard_rel("/x")["code"], "abs_path")
        self.assertEqual(winpath.guard_rel("C:\\x")["code"], "abs_or_drive_or_unc")
        self.assertEqual(winpath.guard_rel("\\\\s\\d")["code"], "abs_or_drive_or_unc")
        self.assertEqual(winpath.guard_rel("a/../b")["code"], "traversal")
        self.assertEqual(winpath.guard_rel("CON")["code"], "reserved_name")
        self.assertEqual(winpath.guard_rel("a/b")["code"], "ok")
        self.assertEqual(winpath.guard_path("", "x")["code"], "empty_root")
        self.assertEqual(winpath.guard_path("r", "")["code"], "empty_target")
        self.assertEqual(winpath.guard_path("r", "C:\\x")["code"], "root_not_absolute")
        self.assertEqual(winpath.guard_path("C:\\r", "r")["code"], "root_not_absolute")
        self.assertEqual(winpath.guard_path("C:\\r", "\\\\s\\d")["code"], "root_kind_mismatch")
        self.assertEqual(winpath.guard_path("C:\\r", "D:\\x")["code"], "drive_escape")
        self.assertEqual(winpath.guard_path("\\\\s\\d", "\\\\s\\e")["code"], "unc_escape")
        self.assertEqual(winpath.guard_path("C:\\r", "C:\\x\\..\\r")["code"], "traversal")
        self.assertEqual(winpath.guard_path("C:\\r", "C:\\r")["code"], "ok")
        self.assertEqual(winpath.guard_path("C:\\r", "C:\\r\\a")["code"], "ok")
        self.assertEqual(winpath.guard_path("C:\\r", "C:\\x")["code"], "escape")


class ConfigArchiveTest(unittest.TestCase):
    def test_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            old = os.environ.get("AI_NEW_DATA")
            os.environ["AI_NEW_DATA"] = tmp
            try:
                self.assertTrue(str(config._data_dir()).startswith(tmp))
                saved = os.environ.pop("AI_NEW_DATA")
                try:
                    self.assertTrue(str(config._data_dir()).endswith("data"))
                finally:
                    os.environ["AI_NEW_DATA"] = saved
                ctx = type("C", (), {})()
                ctx.api = mock.Mock()
                ctx.cfg = {}
                config.setup(ctx)
                self.assertEqual(ctx.cfg["server"], {})
                config._write(ctx, "config.default.yaml", {"server": {"host": "h"}})
                config.setup(ctx)
                self.assertEqual(ctx.cfg["server"]["host"], "h")
                with mock.patch.dict(os.environ, {"AI_NEW_PORT": "1",
                                                  "AI_NEW_LLM_BASE_URL": "u"}):
                    config._apply_env(ctx.cfg)
                self.assertEqual(ctx.cfg["server"]["port"], 1)
                self.assertEqual(config.get(ctx, "server.port"), 1)
                self.assertEqual(config.get(ctx, "none", 2), 2)
                self.assertEqual(config.set_value(ctx, "a.b", 1), 1)
                self.assertEqual(config._route_get(ctx, {"key": "a.b"})["value"], 1)
                self.assertEqual(config._route_get(ctx, {"key": "server"})["value"],
                                 ctx.cfg["server"])
                self.assertEqual(config.redacted(ctx)["a"], {"b": 1})
                self.assertEqual(config._route_set_value(ctx, {})["code"], "missing_key")
                self.assertEqual(config._route_set_value(ctx, {"key": "x.y",
                                                               "value": 1})["value"], 1)
                spec = {"params": [{"group": "g", "key": "a.b"}, "bad",
                                   {"group": "g", "key": "z"}]}
                config._write(ctx, "params.yaml", spec)
                ex = config._route_explain(ctx, {})
                self.assertEqual(ex["groups"], ["g"])
                self.assertEqual(ex["count"], 2)
                ctx.cfg["token"] = "x"
                ctx.cfg["nested"] = {"api_key": "y"}
                self.assertEqual(config.redacted(ctx)["nested"]["api_key"], "<redacted>")
                self.assertEqual(config._deep_merge({"a": {"b": 1}}, {"a": {"c": 2}}),
                                 {"a": {"b": 1, "c": 2}})
                self.assertIsNone(config._nested_get({}, "a"))
                self.assertEqual(config._route_get(ctx, {})["server"]["port"], 1)
                Path(tmp, "agent_common", "config", "bad.yaml").write_text("{")
                self.assertEqual(config._read(ctx, "bad.yaml"), {})
            finally:
                if old is None:
                    os.environ.pop("AI_NEW_DATA", None)
                else:
                    os.environ["AI_NEW_DATA"] = old

    def test_archive(self):
        self.assertEqual(archive.backend_info()["default"], "gzip")
        c = archive.compress_bytes(b"x", 1)
        self.assertEqual(archive.decompress_bytes(c["data"]), b"x")
        with self.assertRaises(ValueError):
            archive.compress_bytes(b"x", algorithm="zstd")
        with self.assertRaises(ValueError):
            archive.decompress_bytes(b"x", algorithm="zstd")
        with self.assertRaises(ValueError):
            archive.compress_bytes(b"x", algorithm="bad")
        self.assertEqual(archive.suffix_for("zstd"), ".zst")
        self.assertEqual(archive.suffix_for("bad"), ".gz")
        with self.assertRaises(ValueError):
            archive.decompress_bytes(b"x", algorithm="bad")
        import sys, types
        fake = types.ModuleType("zstandard")
        fake.ZstdCompressor = lambda level=6: types.SimpleNamespace(
            compress=lambda data: b"z")
        fake.ZstdDecompressor = lambda: types.SimpleNamespace(
            decompress=lambda data: b"x")
        with mock.patch.dict(sys.modules, {"zstandard": fake}):
            self.assertEqual(archive._zstd_compress(b"x", 1), b"z")
            self.assertEqual(archive._zstd_decompress(b"z"), b"x")
        with mock.patch.object(archive, "_ZSTD_INSTALLED", True):
            with mock.patch.object(archive, "_zstd_compress", return_value=b"z"):
                self.assertEqual(archive.compress_bytes(b"x", algorithm="zstd")["algorithm"],
                                 "zstd")
            with mock.patch.object(archive, "_zstd_decompress", return_value=b"x"):
                self.assertEqual(archive.decompress_bytes(b"z", "zstd"), b"x")
            self.assertEqual(archive.backend_info()["zstd"]["note"], "zstandard 已可导入。")
            self.assertIn("zstd", archive.available_algorithms())


if __name__ == "__main__":
    unittest.main()
