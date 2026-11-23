"""增量同步专项：清单三件套、远端幂等跳过、退避上限、断点续传、台账计数。

不连外网；提供方为内存桩，主密钥经环境变量注入。退避等待在策略里置 0 避免拖慢。
"""
import base64
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

from ai_new.modules.agent.cloud.private import _pure, _providers  # noqa: E402

MASTER_KEY = base64.b64encode(b"0" * 32).decode()


def _global_caller():
    return {"scope": "global", "project": "", "ticket": "",
            "session": "admin-s1", "role": "admin"}


class SyncTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        root = Path(cls.tmp.name)
        stage(root)
        write_config(root, {
            "server": {"host": "127.0.0.1", "port": 0, "token": "t"},
            "llm": {"base_url": "http://stub.local/v1", "api_key": "k", "model": "stub"},
            "tickets": {"stall_check": {"enabled": False}},
            "cloud": {"allowed_hosts": []},
        })
        os.environ["AI_NEW_DATA"] = str(root)
        os.environ["AI_NEW_SECRET_KEY"] = MASTER_KEY
        os.environ["AI_NEW_SECRET_KEY_FILE"] = str(root / "secrets.key")
        cls.ctx = Context(root)
        cls.loaded = build(cls.ctx)
        cls.fake = _providers.FakeProvider()
        cls._orig_build = _providers.build
        _providers.build = lambda kind: cls.fake

    @classmethod
    def tearDownClass(cls):
        _providers.build = cls._orig_build
        os.environ.pop("AI_NEW_DATA", None)
        os.environ.pop("AI_NEW_SECRET_KEY", None)
        os.environ.pop("AI_NEW_SECRET_KEY_FILE", None)
        shutil.rmtree(cls.tmp.name, ignore_errors=True)

    def setUp(self):
        self.fake.store = {}
        self.fake.fail_times = 0
        self.fake.fail_keys = {}
        self.fake.attempts = 0
        self.fake.calls = []

    # ---- 夹具 ----

    def _apply(self, res):
        effects = (res or {}).get("effects") or []
        if effects:
            self.ctx.runtime.apply({"effect": effects})

    def _save(self, pid, secret="sync-secret", categories=None):
        payload = {
            "id": pid, "company": "co-sync", "provider": "stub",
            "endpoint": "https://oss.example.com/backup", "root_dir": "team-a",
            "credentials": {"access_key": secret},
            "categories": categories or ["knowledge"],
            "policy": {"max_attempts": 3, "backoff_base_s": 0, "backoff_cap_s": 0},
            "caller": _global_caller(),
        }
        res = self.ctx.api.call("cloud.profile_save", payload)
        self._apply(res)
        return res

    def _stage(self, rel, text):
        self.ctx.api.call("store.write_text",
                          {"module": "agent/knowledge", "path": rel, "text": text})

    def _run(self, pid):
        res = self.ctx.api.call("cloud.sync_run",
                                {"id": pid, "caller": _global_caller()})
        self._apply(res)
        return res

    # ---- 用例 ----

    def test_manifest_records_digest_size_mtime(self):
        self._save("p-manifest")
        self._stage("manifest-probe.md", "清单三件套正文")
        res = self._run("p-manifest")
        self.assertTrue(res["ok"], res["ledger"])

        state = self.ctx.api.call("store.read", {
            "module": "agent/cloud", "path": "state.yaml"})["value"]
        entries = {e["rel"]: e for e in state["manifests"]["p-manifest"]["entries"]}
        entry = next(e for rel, e in entries.items() if rel.endswith("manifest-probe.md"))
        self.assertEqual(len(entry["digest"]), 64)
        self.assertGreater(entry["size"], 0)
        self.assertGreater(entry["mtime"], 0)
        # 摘要与本地内容一致。
        body = self.ctx.api.call("store.read_bytes",
                                 {"module": "agent/knowledge", "path": "manifest-probe.md"})
        dec = self.ctx.api.call("codec.base64_decode_bytes", {"text": body["value"]})
        expected = self.ctx.api.call("codec.digest",
                                     {"text": dec["data"], "algorithm": "sha256"})["hex"]
        self.assertEqual(entry["digest"], expected)

    def test_remote_identical_skipped_without_repush(self):
        self._save("p-identical")
        self._stage("identical-probe.md", "远端已存在相同内容")
        plan = self.ctx.api.call("cloud.sync_plan", {"id": "p-identical"})
        target = next(e for e in plan["plan"]["to_push"] if e["rel"].endswith("identical-probe.md"))
        # 先在远端按相同摘要预置对象：本地清单无记录时应幂等跳过，不再重传。
        body = self.ctx.api.call("store.read_bytes",
                                 {"module": "agent/knowledge", "path": "identical-probe.md"})
        dec = self.ctx.api.call("codec.base64_decode_bytes", {"text": body["value"]})
        digest = self.ctx.api.call("codec.digest",
                                   {"text": dec["data"], "algorithm": "sha256"})["hex"]
        self.fake.store[target["rel"]] = {"data": dec["data"], "digest": digest,
                                          "size": len(dec["data"])}

        res = self._run("p-identical")
        self.assertTrue(res["ok"], res["ledger"])
        # 预置相同摘要的目标条目幂等跳过（远端一致，不重传）；其余本地文件照常上推。
        self.assertGreaterEqual(res["ledger"]["skipped"], 1)
        put_keys = [k for kind, k, *_ in self.fake.calls if kind == "put"]
        self.assertNotIn(target["rel"], put_keys)

    def test_backoff_delays_capped_at_base(self):
        self.assertEqual(_pure.backoff_delay(0, 1, 30), 1)
        self.assertEqual(_pure.backoff_delay(1, 1, 30), 2)
        self.assertEqual(_pure.backoff_delay(2, 1, 30), 4)
        self.assertEqual(_pure.backoff_delay(10, 1, 30), 30)
        # 抖动落在指数值与上限之间。
        jittered = _pure.backoff_jittered(2, 1, 30, ratio=0.5, fraction=1.0)
        self.assertGreaterEqual(jittered, 4)
        self.assertLessEqual(jittered, 30)
        # 退避基数为 0 时不产生等待。
        self.assertEqual(_pure.backoff_jittered(2, 0, 0, fraction=0.5), 0.0)

    def test_failed_entry_resumes_only_pending(self):
        self._save("p-resume")
        self._stage("resume-probe.md", "断点续传正文")
        plan = self.ctx.api.call("cloud.sync_plan", {"id": "p-resume"})
        target = next(e for e in plan["plan"]["to_push"] if e["rel"].endswith("resume-probe.md"))
        # 该条目前 max_attempts 次全部失败；其余条目正常上传。
        self.fake.fail_keys[target["rel"]] = 3

        first = self._run("p-resume")
        self.assertFalse(first["ok"])
        self.assertEqual(len(first["ledger"]["failed"]), 1)
        self.assertEqual(first["ledger"]["failed"][0]["rel"], target["rel"])

        resume = self.ctx.api.call("store.read", {
            "module": "agent/cloud", "path": "resume/p-resume.yaml"})["value"]
        self.assertEqual(resume["pending"], [target["rel"]])
        self.assertIn(target["rel"], resume["entries"])

        # 清除注入失败；第二轮只续传待传条目，已传条目不重传。
        self.fake.fail_keys = {}
        put_before = [k for kind, k, *_ in self.fake.calls if kind == "put"]
        second = self._run("p-resume")
        self.assertTrue(second["ok"], second["ledger"])
        self.assertEqual(second["ledger"]["added"], 1)
        put_after = [k for kind, k, *_ in self.fake.calls if kind == "put"]
        self.assertEqual(put_after.count(target["rel"]), put_before.count(target["rel"]) + 1)

        cleared = self.ctx.api.call("store.read", {
            "module": "agent/cloud", "path": "resume/p-resume.yaml"})
        # 全部成功后检查点应清除（effect 已执行）。
        self.assertFalse(cleared.get("value"))

    def test_ledger_counts_and_legacy_aliases(self):
        self._save("p-count")
        self._stage("count-probe.md", "计数正文")
        res = self._run("p-count")
        self.assertTrue(res["ok"], res["ledger"])
        ledger = res["ledger"]
        # 新旧字段名成对：pushed=added，unchanged=skipped，failures=failed 计数。
        self.assertEqual(ledger["pushed"], ledger["added"])
        self.assertEqual(ledger["unchanged"], ledger["skipped"])
        self.assertEqual(ledger["failures"], len(ledger["failed"]))
        self.assertGreaterEqual(ledger["added"], 1)
        self.assertEqual(ledger["conflicts"], 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
