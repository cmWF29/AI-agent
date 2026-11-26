"""跨进程排他锁：路径归一、能力上报、POSIX/NT 分支、重入与超时。"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path
import types
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))

from ai_new.modules.agent_common.plat.private import _lock as l  # noqa: E402


class FakeMsvcrt(types.SimpleNamespace):
    LK_NBLCK = 2
    LK_UNLCK = 0
    calls = []

    def locking(self, fd, mode, n):
        self.calls.append((fd, mode, n))
        if getattr(self, "fail", False):
            raise OSError("locked")


class LockEdgesTest(unittest.TestCase):
    def setUp(self):
        l._held.clear()

    def test_norm_and_capability(self):
        self.assertEqual(l._norm(None), "")
        self.assertEqual(l._norm("a"), os.path.normcase(os.path.abspath("a")))
        with mock.patch.object(l, "PLATFORM", "nt"):
            cap = l.lock_capability()
        self.assertEqual(cap["platform"], "nt")
        self.assertEqual(l.lock_capability()["platform"], l.PLATFORM)

    def test_posix_acquire_release(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "a.lock")
            lock = l.ExclusiveLock.opened(path, timeout=1)
            lock.acquire()
            self.assertTrue(lock._held)
            lock.release()
            self.assertFalse(lock._held)
            fh = open(path, "a+b")
            held = l.ExclusiveLock(fh, path=path, timeout=1)
            held.acquire()
            with self.assertRaises(l.LockError) as cm:
                held.acquire()
            self.assertEqual(cm.exception.code, "lock_reentrant")
            held.release()
            fh.close()
            with l.lock_file(path, timeout=1) as again:
                self.assertTrue(again._held)

    def test_posix_timeout_and_close_errors(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "b.lock")
            with mock.patch("fcntl.flock", side_effect=BlockingIOError):
                with mock.patch.object(l.time, "time", side_effect=[0, 0, 0, 1, 2]):
                    lock = l.ExclusiveLock.opened(path, timeout=1)
                    with self.assertRaises(l.LockError) as cm:
                        lock.acquire()
                    self.assertEqual(cm.exception.code, "lock_timeout")
            handle = mock.Mock()
            handle.fileno.return_value = 1
            handle.close.side_effect = OSError("x")
            lock2 = l.ExclusiveLock(handle, path=path, timeout=1, owns_handle=True)
            with mock.patch("fcntl.flock", side_effect=OSError("boom")):
                with self.assertRaises(OSError):
                    lock2.acquire()
            unowned = l.ExclusiveLock(handle)
            with mock.patch("fcntl.flock", side_effect=OSError("boom")):
                with self.assertRaises(OSError):
                    unowned.acquire()
            fresh = l.ExclusiveLock(handle)
            fresh.release()
            with mock.patch("fcntl.flock", return_value=None):
                lock2.acquire()
                lock2.release()
            self.assertFalse(lock2._held)
            no_path = l.ExclusiveLock(handle)
            no_path.acquire()
            no_path.release()

    def test_nt_branch(self):
        fake = FakeMsvcrt()
        with mock.patch.dict(sys.modules, {"msvcrt": fake}), \
                mock.patch.object(l, "PLATFORM", "nt"), \
                mock.patch.object(l.os, "lseek", return_value=0):
            with tempfile.TemporaryDirectory() as d:
                path = os.path.join(d, "n.lock")
                lock = l.ExclusiveLock.opened(path, timeout=1)
                lock.acquire()
                lock.release()
                fake.fail = True
                with mock.patch.object(l.time, "time", side_effect=[0, 0, 0, 0, 1]):
                    lock2 = l.ExclusiveLock.opened(path, timeout=1)
                    with self.assertRaises(l.LockError):
                        lock2.acquire()
                fake.fail = False
                fake.calls.clear()
                lock3 = l.ExclusiveLock(100, path=None, timeout=None)
                lock3.acquire()
                lock3.release()

    def test_release_close_oserror(self):
        handle = mock.Mock()
        handle.fileno.return_value = 1
        handle.close.side_effect = OSError("x")
        with tempfile.TemporaryDirectory() as d:
            lock = l.ExclusiveLock(handle, path=os.path.join(d, "c.lock"),
                                   owns_handle=True)
            with mock.patch("fcntl.flock", return_value=None):
                lock.acquire()
                lock.release()
            self.assertFalse(lock._held)
            self.assertEqual(l._held, {})


if __name__ == "__main__":
    unittest.main()
