"""知识文档并发写保护与路径可见性契约。

覆盖：
- 路径穿越 / 绝对路径注入 / 符号链接逃逸一律被拒；
- 公共 / 项目 / 工单三层读写边界：项目互不可见，工单层只读自己工单；
- 原子追加：并发写不丢更新，读不到半截文件；
- 版本元数据纯函数：版本令牌校验、冲突返回双方版本/作者、修订历史；
- 文档锁档位诚实上报：跨进程 OS 锁未落地不冒充已支持。
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))


def _is_relative_to(path: Path, root: Path) -> bool:
    """Py3.8 兼容：Path.is_relative_to 到 3.9 才有，门禁必须能在 3.8 跑。"""
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False

from ai_new.modules.agent_common.store.private import _docpath  # noqa: E402
from ai_new.modules.agent_common.store.private import _doclock  # noqa: E402
from ai_new.modules.agent_common.store.private import _files  # noqa: E402
from ai_new.modules.agent_common.store.private import _panel  # noqa: E402
from ai_new.modules.agent_common.store.private import _revision  # noqa: E402
from ai_new.modules.agent_common.codec.private import _codec  # noqa: E402

MODULE = "agent/knowledge"


class _StubApi:
    def call(self, route, payload, caller=None):
        if route == "clock.now":
            return {"iso": "2026-11-23T10:00:00"}
        raise AssertionError("unexpected route: %s" % route)


def _stub_ctx():
    """最小 ctx：只挂 codec 与 api 桩，供 store 修订闭环直测。"""
    return type("Ctx", (), {"codec": _codec, "api": _StubApi()})()


_ROOT = Path(__file__).resolve().parents[4]

_SUBPROC_SCRIPT = """
import sys, json
from pathlib import Path
ROOT = Path(sys.argv[1]); root = sys.argv[2]; action = sys.argv[3]
sys.path.insert(0, str(ROOT))
from ai_new.modules.agent_common.store.private import _panel
from ai_new.modules.agent_common.codec.private import _codec

class _Api:
    def call(self, route, payload, caller=None):
        if route == "clock.now":
            return {"iso": "2026-11-23T11:00:00"}
        raise AssertionError("unexpected route: %s" % route)

ctx = type("C", (), {"codec": _codec, "api": _Api()})()
md = _panel.ModuleData(Path(root), ctx)
if action == "write":
    token = None if sys.argv[6] == "none" else int(sys.argv[6])
    out = md.revision("note.md", "overwrite", sys.argv[4], sys.argv[5], token)
else:
    out = md.yaml_read(md._meta_rel("note.md"), default={"version": 0, "history": []})
print(json.dumps(out, ensure_ascii=False))
"""


def _spawn(root, action, body="", author="", token="none"):
    """起独立子进程跑修订闭环；回传子进程读到/写到的元数据 JSON。"""
    env = dict(os.environ)
    env["AI_NEW_DATA"] = str(root)
    proc = subprocess.run(
        [sys.executable, "-c", _SUBPROC_SCRIPT, str(_ROOT), str(root),
         action, body, author, token],
        capture_output=True, text=True, env=env)
    if proc.returncode != 0:
        raise AssertionError("子进程失败: %s" % proc.stderr)
    return json.loads(proc.stdout)


class PathValidationTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="kpath-")
        os.environ["AI_NEW_DATA"] = self.tmp

    def tearDown(self):
        os.environ.pop("AI_NEW_DATA", None)

    def test_relative_doc_resolves_under_root(self):
        out = _docpath.resolve(MODULE, "public/note.md")
        self.assertTrue(out["ok"])
        self.assertTrue(_is_relative_to(Path(out["real"]), Path(out["root"])))

    def test_traversal_segment_rejected(self):
        for rel in ("../etc/passwd", "public/../../etc", "a/../../../b"):
            out = _docpath.resolve(MODULE, rel)
            self.assertFalse(out["ok"], rel)
            self.assertEqual(out["code"], "traversal", rel)

    def test_absolute_path_rejected(self):
        out = _docpath.resolve(MODULE, "/etc/passwd")
        self.assertFalse(out["ok"])
        self.assertEqual(out["code"], "abs_path")

    def test_symlink_escape_rejected(self):
        root_real = Path(_docpath.resolve(MODULE, "dummy.md")["root"])
        root_real.mkdir(parents=True, exist_ok=True)
        outside = Path(tempfile.mkdtemp(prefix="koutside-"))
        link = root_real / "link.md"
        if os.name == "nt":
            subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(outside)],
                           check=True, capture_output=True)
        else:
            link.symlink_to(outside)
        out = _docpath.resolve(MODULE, "link.md")
        self.assertFalse(out["ok"])
        self.assertEqual(out["code"], "escape")


class LayerIsolationTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="klayer-")
        os.environ["AI_NEW_DATA"] = self.tmp

    def tearDown(self):
        os.environ.pop("AI_NEW_DATA", None)

    def _write(self, rel, text):
        path = Path(_docpath.resolve(MODULE, rel)["real"])
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def _read(self, rel):
        path = Path(_docpath.resolve(MODULE, rel)["real"])
        return path.read_text(encoding="utf-8") if path.is_file() else None

    def test_projects_are_isolated(self):
        self._write("projects/proj-a/note.md", "A 项目私有文档")
        self._write("projects/proj-b/note.md", "B 项目私有文档")
        self.assertEqual(self._read("projects/proj-a/note.md"), "A 项目私有文档")
        self.assertEqual(self._read("projects/proj-b/note.md"), "B 项目私有文档")
        # B 的文档路径不在 A 的项目目录之下。
        a = Path(_docpath.resolve(MODULE, "projects/proj-a/note.md")["real"])
        b = Path(_docpath.resolve(MODULE, "projects/proj-b/note.md")["real"])
        self.assertFalse(_is_relative_to(b, a.parent))

    def test_ticket_layer_isolated_per_ticket(self):
        self._write("tickets/T-1/note.md", "工单 T-1 备注")
        self._write("tickets/T-2/note.md", "工单 T-2 备注")
        self.assertEqual(self._read("tickets/T-1/note.md"), "工单 T-1 备注")
        self.assertEqual(self._read("tickets/T-2/note.md"), "工单 T-2 备注")

    def test_public_is_shared_but_project_not_leaked(self):
        self._write("public/common.md", "公共知识")
        self._write("projects/proj-a/secret.md", "项目私有")
        self.assertEqual(self._read("public/common.md"), "公共知识")
        # 项目层文档不会出现在公共层路径下。
        pub = Path(_docpath.resolve(MODULE, "public/common.md")["real"])
        priv = Path(_docpath.resolve(MODULE, "projects/proj-a/secret.md")["real"])
        self.assertFalse(_is_relative_to(priv, pub.parent))


class AtomicAppendConcurrencyTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="kappend-")

    def test_concurrent_appends_do_not_lose_updates(self):
        md = _panel.ModuleData(Path(self.tmp), _stub_ctx())
        md.append_text_locked("note.md", "首行\n")
        n = 32

        def worker(i):
            md.append_text_locked("note.md", "行-%d\n" % i)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(n)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        text = (Path(self.tmp) / "note.md").read_text(encoding="utf-8")
        for i in range(n):
            self.assertIn("行-%d" % i, text)
        # 完整落盘：以换行收尾，不存在半截行。
        self.assertTrue(text.endswith("\n"))
        self.assertEqual(len([ln for ln in text.splitlines() if ln.strip()]), n + 1)

    def test_append_leaves_no_half_file(self):
        path = Path(self.tmp) / "one.md"
        _files.append_text_atomic(path, "第一段\n")
        _files.append_text_atomic(path, "第二段\n")
        self.assertEqual(path.read_text(encoding="utf-8"), "第一段\n第二段\n")


class VersionMetaTest(unittest.TestCase):
    def test_init_and_check_match(self):
        meta = _revision.init_meta("alice", "2026-11-23T10:00:00", "内容")
        self.assertEqual(meta["version"], 1)
        ok = _revision.check(meta, 1)
        self.assertTrue(ok["ok"])
        self.assertEqual(ok["current_author"], "alice")

    def test_conflict_reports_both_sides(self):
        meta = _revision.init_meta("alice", "2026-11-23T10:00:00", "内容")
        conflict = _revision.check(meta, 5)
        self.assertFalse(conflict["ok"])
        self.assertEqual(conflict["current_version"], 1)
        self.assertEqual(conflict["token"], 5)
        self.assertEqual(conflict["current_author"], "alice")

    def test_bump_appends_history_and_caps(self):
        meta = _revision.init_meta("alice", "t1", "a")
        for i in range(3):
            meta = _revision.bump(meta, "bob", "t%d" % (i + 2), "b")
        self.assertEqual(meta["version"], 4)
        self.assertEqual(len(meta["history"]), 4)
        capped = _revision.bump(meta, "carol", "t6", "c", keep=3)
        self.assertEqual(len(capped["history"]), 3)


class RevisionClosedLoopTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="krev-")
        self.md = _panel.ModuleData(Path(self.tmp), _stub_ctx())

    def _body(self, rel):
        return (Path(self.tmp) / rel).read_text(encoding="utf-8")

    def test_new_doc_writes_body_and_history(self):
        out = self.md.revision("note.md", "overwrite", "v1", "alice", None)
        self.assertTrue(out["ok"])
        self.assertEqual(out["version"], 1)
        self.assertEqual(self._body("note.md"), "v1")
        self.assertEqual(len(out["history"]), 1)
        entry = out["history"][0]
        self.assertEqual(entry["version"], 1)
        self.assertEqual(entry["author"], "alice")
        self.assertEqual(entry["chars"], 2)

    def test_valid_bump_increments_and_records_history(self):
        first = self.md.revision("note.md", "overwrite", "v1", "alice", None)
        second = self.md.revision("note.md", "overwrite", "v2", "bob", first["version"])
        self.assertTrue(second["ok"])
        self.assertEqual(second["version"], 2)
        self.assertEqual(self._body("note.md"), "v2")
        versions = [h["version"] for h in second["history"]]
        self.assertEqual(versions, [1, 2])
        authors = [h["author"] for h in second["history"]]
        self.assertEqual(authors, ["alice", "bob"])

    def test_stale_token_conflicts_and_does_not_overwrite(self):
        first = self.md.revision("note.md", "overwrite", "v1", "alice", None)
        second = self.md.revision("note.md", "overwrite", "v2", "bob", first["version"])
        # 第三方仍拿旧令牌 1 来写：当前已是 2，必须冲突，且正文不被覆盖。
        conflict = self.md.revision("note.md", "overwrite", "v3", "carol", 1)
        self.assertFalse(conflict["ok"])
        self.assertEqual(conflict["code"], "conflict")
        self.assertEqual(conflict["status"], 409)
        self.assertEqual(conflict["current_version"], 2)
        self.assertEqual(conflict["current_author"], "bob")
        self.assertEqual(conflict["token"], 1)
        self.assertEqual(self._body("note.md"), "v2")

    def test_lock_covers_create_and_save_paths(self):
        # create：覆盖写新文档；save：追加写。两条路径都走同一把文档锁。
        self.md.write_text_locked("a.md", "新建\n")
        self.md.append_text_locked("a.md", "追加\n")
        self.assertEqual(self._body("a.md"), "新建\n追加\n")

    def test_concurrent_revision_appends_do_not_lose_updates(self):
        self.md.append_text_locked("note.md", "首行\n")
        n = 32

        def worker(i):
            # 已存在文档的追加：显式 force 跳过令牌比对，仍在同一把锁内原子落盘。
            self.md.revision("note.md", "append", "行-%d\n" % i, "w", None, force=True)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(n)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        text = self._body("note.md")
        for i in range(n):
            self.assertIn("行-%d" % i, text)
        self.assertTrue(text.endswith("\n"))


class DocLockCapabilityTest(unittest.TestCase):
    def test_capability_reports_in_process_and_cross_process(self):
        cap = _doclock.lock_capability()
        self.assertIn(cap["platform"], ("posix", "nt"))
        self.assertTrue(cap["in_process"]["supported"])
        self.assertIn("verified", cap["in_process"])
        self.assertIn("supported", cap["cross_process"])
        self.assertIn("verified", cap["cross_process"])
        # 已落地并验证的档位才允许 verified=True；未验证档位不得冒充。
        if cap["cross_process"]["supported"] and cap["platform"] == "posix":
            self.assertTrue(cap["cross_process"]["verified"])


class ConcurrentRevisionTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="kconcurrent-")
        os.environ["AI_NEW_DATA"] = self.tmp

    def tearDown(self):
        os.environ.pop("AI_NEW_DATA", None)

    def _md(self):
        return _panel.ModuleData(Path(self.tmp), _stub_ctx())

    def test_two_sessions_one_wins_other_conflicts(self):
        """并发两会话写同一文档：仅一方落盘，另一方 409 且拿到双方版本/作者。"""
        md = self._md()
        first = md.revision("note.md", "overwrite", "v1", "alice", None)
        self.assertTrue(first["ok"])

        results = []
        guard = threading.Lock()

        def worker(body, author, token):
            out = md.revision("note.md", "overwrite", body, author, token)
            with guard:
                results.append(out)

        t1 = threading.Thread(target=worker, args=("v2", "bob", 1))
        t2 = threading.Thread(target=worker, args=("v3", "carol", 1))
        t1.start(); t2.start(); t1.join(); t2.join()

        oks = [r for r in results if r["ok"]]
        bads = [r for r in results if not r["ok"]]
        self.assertEqual(len(oks), 1)
        self.assertEqual(len(bads), 1)
        conflict = bads[0]
        self.assertEqual(conflict["code"], "conflict")
        self.assertEqual(conflict["status"], 409)
        self.assertEqual(conflict["current_version"], 2)
        self.assertEqual(conflict["current_author"], oks[0]["author"])
        self.assertEqual(conflict["token"], 1)
        # 正文只保留落盘方的内容，未落盘方的文本不得混入。
        body = (Path(self.tmp) / "note.md").read_text(encoding="utf-8")
        self.assertIn(body, ("v2", "v3"))
        self.assertNotIn("v3" if body == "v2" else "v2", body)

    def test_stale_token_conflicts_and_reports_both_sides(self):
        md = self._md()
        md.revision("note.md", "overwrite", "v1", "alice", None)
        second = md.revision("note.md", "overwrite", "v2", "bob", 1)
        self.assertTrue(second["ok"])
        conflict = md.revision("note.md", "overwrite", "v3", "carol", 1)
        self.assertFalse(conflict["ok"])
        self.assertEqual(conflict["code"], "conflict")
        self.assertEqual(conflict["status"], 409)
        self.assertEqual(conflict["current_version"], 2)
        self.assertEqual(conflict["current_author"], "bob")
        self.assertEqual(conflict["current_updated"], second["updated"])
        self.assertEqual(conflict["token"], 1)
        body = (Path(self.tmp) / "note.md").read_text(encoding="utf-8")
        self.assertEqual(body, "v2")

    def test_force_override_records_revision(self):
        """显式覆盖跳过令牌比对，但覆盖动作仍记入修订历史并标 forced。"""
        md = self._md()
        md.revision("note.md", "overwrite", "v1", "alice", None)
        # 路由层 force 与 version 同时下发；store 锁内跳过比对，不再把 force 折成 None 令牌。
        forced = md.revision("note.md", "overwrite", "v2", "bob", None, force=True)
        self.assertTrue(forced["ok"])
        self.assertEqual(forced["version"], 2)
        self.assertEqual(len(forced["history"]), 2)
        self.assertEqual([h["version"] for h in forced["history"]], [1, 2])
        self.assertEqual([h["author"] for h in forced["history"]], ["alice", "bob"])
        self.assertTrue(forced["history"][-1]["forced"])
        self.assertEqual((Path(self.tmp) / "note.md").read_text(encoding="utf-8"), "v2")

    def test_existing_doc_without_token_requires_token(self):
        """已存在文档覆盖却不带令牌：409 token_required，正文与历史不变。"""
        md = self._md()
        first = md.revision("note.md", "overwrite", "v1", "alice", None)
        conflict = md.revision("note.md", "overwrite", "v2", "bob", None)
        self.assertFalse(conflict["ok"])
        self.assertEqual(conflict["code"], "token_required")
        self.assertEqual(conflict["status"], 409)
        self.assertEqual(conflict["current_version"], first["version"])
        self.assertEqual(conflict["current_author"], "alice")
        self.assertEqual(conflict["token"], None)
        body = (Path(self.tmp) / "note.md").read_text(encoding="utf-8")
        self.assertEqual(body, "v1")

    def test_new_doc_without_token_succeeds(self):
        """新建文档不带令牌：放行并 init_meta，version 从 1 起。"""
        md = self._md()
        out = md.revision("note.md", "overwrite", "v1", "alice", None)
        self.assertTrue(out["ok"])
        self.assertEqual(out["version"], 1)
        self.assertEqual(len(out["history"]), 1)

    def test_new_doc_with_positive_token_conflicts(self):
        """新建文档却带正版本令牌：服务端无该版本，409 且不落盘。"""
        md = self._md()
        conflict = md.revision("note.md", "overwrite", "v1", "alice", 1)
        self.assertFalse(conflict["ok"])
        self.assertEqual(conflict["code"], "conflict")
        self.assertEqual(conflict["status"], 409)
        self.assertEqual(conflict["current_version"], 0)
        self.assertFalse((Path(self.tmp) / "note.md").exists())

    def test_history_grows_with_each_write(self):
        md = self._md()
        r1 = md.revision("note.md", "overwrite", "v1", "alice", None)
        r2 = md.revision("note.md", "overwrite", "v2", "bob", r1["version"])
        r3 = md.revision("note.md", "overwrite", "v3", "carol", r2["version"])
        self.assertEqual([len(r["history"]) for r in (r1, r2, r3)], [1, 2, 3])
        self.assertEqual(r3["version"], 3)


class CrossProcessRevisionTest(unittest.TestCase):
    def test_new_process_reads_consistent_version(self):
        tmp = tempfile.mkdtemp(prefix="kxproc-")
        os.environ["AI_NEW_DATA"] = tmp
        try:
            md = _panel.ModuleData(Path(tmp), _stub_ctx())
            first = md.revision("note.md", "overwrite", "v1", "alice", None)
            self.assertTrue(first["ok"])

            # 子进程基于令牌 1 覆盖为 v2，跨进程锁内完成校验→落盘→记修订。
            written = _spawn(tmp, "write", body="v2", author="bob", token="1")
            self.assertTrue(written["ok"])
            self.assertEqual(written["version"], 2)

            # 父进程以全新实例重读：版本与历史与子进程落盘一致。
            fresh = _panel.ModuleData(Path(tmp), _stub_ctx())
            meta = fresh.yaml_read(fresh._meta_rel("note.md"),
                                   default={"version": 0, "history": []})
            self.assertEqual(meta["version"], 2)
            self.assertEqual(len(meta["history"]), 2)

            # 第二个子进程只读：读到同一版本与同一条历史长度。
            read = _spawn(tmp, "read")
            self.assertEqual(read["version"], 2)
            self.assertEqual(len(read["history"]), 2)
        finally:
            os.environ.pop("AI_NEW_DATA", None)


if __name__ == "__main__":
    unittest.main(verbosity=2)
