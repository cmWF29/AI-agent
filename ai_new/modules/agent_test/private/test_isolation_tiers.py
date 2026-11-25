"""隔离两档靶向单测：档位策略、切换条件、执行计划、跨进程锁互斥。

策略纯函数直接打；跨进程锁只打 store 能力层 _xlock 的公共接口，底层 flock /
msvcrt 由平台层选择，用例不做 OS 分支、不 skip。
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))

from ai_new.modules.agent.sandbox.private import _pure  # noqa: E402
from ai_new.modules.agent_common.store.private import _xlock  # noqa: E402


class TierPolicyTest(unittest.TestCase):
    def test_describe_both_tiers_with_overhead(self):
        desc = _pure.describe()
        for tier in ("weak", "strong"):
            self.assertIn("mechanisms", desc[tier])
            self.assertIn("overhead", desc[tier])
            self.assertIn("linux", desc[tier]["mechanisms"])
            self.assertIn("windows", desc[tier]["mechanisms"])
        self.assertTrue(desc["upgrade_conditions"])
        self.assertTrue(desc["keep_weak_conditions"])

    def test_pick_tier_explicit_wins(self):
        self.assertEqual(_pure.pick_tier({"tier": "strong"})["tier"], "strong")
        self.assertEqual(_pure.pick_tier({"tier": "weak"})["tier"], "weak")

    def test_pick_tier_flag_upgrades_to_strong(self):
        for flag in ("untrusted_code", "multi_tenant", "network_restrict",
                     "audit_isolation"):
            out = _pure.pick_tier({flag: True})
            self.assertEqual(out["tier"], "strong", flag)
            self.assertIn(flag, out["flags"])

    def test_pick_tier_default_weak(self):
        out = _pure.pick_tier({})
        self.assertEqual(out["tier"], "weak")
        self.assertEqual(out["reason"], "default")

    def test_plan_weak_constrains_cwd_and_lock(self):
        out = _pure.plan("p1", "weak", {"root": "/tmp/ai_new/p1"})
        self.assertTrue(out["ok"])
        self.assertEqual(out["cwd"], "/tmp/ai_new/p1")
        self.assertTrue(out["lock_path"].endswith("p1.lock"))
        self.assertEqual(out["env"]["AI_NEW_PROJECT"], "p1")
        self.assertIsNone(out["strong_wrap"])

    def test_plan_strong_carries_wrap_descriptor(self):
        out = _pure.plan("p1", "strong", {"root": "/tmp/ai_new/p1"})
        self.assertTrue(out["ok"])
        self.assertIsNotNone(out["strong_wrap"])
        self.assertIn("unshare", out["strong_wrap"]["linux"][0])

    def test_plan_rejects_relative_and_traversal_root(self):
        self.assertFalse(_pure.plan("p1", "weak", {"root": "../rel"})["ok"])
        self.assertFalse(_pure.plan("p1", "weak", {"root": "/tmp/../etc"})["ok"])
        self.assertFalse(_pure.plan("p1", "weak", {"root": ""})["ok"])


class XlockTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="xlock-")
        self.path = str(Path(self.tmp) / "project.lock")

    def test_capability_reports_cross_process_lock(self):
        cap = _xlock.capability()
        self.assertTrue(cap["cross_process"]["supported"])
        self.assertTrue(cap["cross_process"]["verified"])
        if os.name == "nt":
            self.assertEqual(cap["cross_process"]["mechanism"], "msvcrt.locking")
        else:
            self.assertEqual(cap["cross_process"]["mechanism"], "fcntl.flock")

    def test_cross_process_exclusion(self):
        # 子进程持锁不放；父进程限时抢锁必须 timeout；子进程退出后父进程可拿到。
        child_code = (
            "import sys,time;"
            "from ai_new.modules.agent_common.store.private import _xlock;"
            "l=_xlock.lock_file(sys.argv[1]);l.acquire();"
            "open(sys.argv[2],'w').write('ready');time.sleep(30)"
        )
        ready = str(Path(self.tmp) / "ready")
        repo_root = str(Path(__file__).resolve().parents[4])
        env = os.environ.copy()
        env["PYTHONPATH"] = repo_root + os.pathsep + env.get("PYTHONPATH", "")
        proc = subprocess.Popen(
            [sys.executable, "-c", child_code, self.path, ready],
            cwd=repo_root, env=env,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            for _ in range(100):
                if os.path.exists(ready):
                    break
                time.sleep(0.05)
            self.assertTrue(os.path.exists(ready), "子进程未拿到锁")
            waiter = _xlock.lock_file(self.path, timeout=0.8)
            with self.assertRaises(Exception) as caught:
                waiter.acquire()
            self.assertEqual(getattr(caught.exception, "code", ""), "lock_timeout")
            waiter.release()
        finally:
            proc.terminate()
            proc.wait(timeout=5)
        lock = _xlock.lock_file(self.path)
        lock.acquire()
        lock.release()


if __name__ == "__main__":
    unittest.main()
