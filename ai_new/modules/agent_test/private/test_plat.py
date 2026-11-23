"""plat 平台适配层靶向单测：锁互斥/重入、传输档位与回退、进程信号能力上报。

POSIX 专属行为（flock 跨句柄互斥、fork 能力、SIGTERM 处理器）用 skipUnless /
skipTest 标注；结构形状与降级断言在 POSIX 主机与 Windows 真机上跑同一批。
"""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))

from ai_new.modules.agent_common.plat.private import _lock, _net, _proc  # noqa: E402

POSIX = os.name != "nt"


class CapabilityTest(unittest.TestCase):
    def test_lock_capability_shape(self):
        cap = _lock.lock_capability()
        self.assertTrue(cap["ok"])
        self.assertIn(cap["platform"], ("posix", "nt"))
        cross = cap["cross_process"]
        self.assertIn("supported", cross)
        self.assertIn("verified", cross)
        self.assertIn("mechanism", cross)
        self.assertIn("in_process", cap)
        self.assertTrue(cap["in_process"]["supported"])

    def test_transport_capability_shape(self):
        tr = _net.transport_capability()
        self.assertTrue(tr["ok"])
        self.assertTrue(tr["tcp_loopback"])
        self.assertIn(tr["transport"], ("unix_socket", "tcp_loopback"))
        self.assertIs(tr["unix_socket"], POSIX)

    def test_proc_capability_shape(self):
        pr = _proc.proc_capability()
        self.assertTrue(pr["ok"])
        self.assertIn("fork", pr)
        self.assertIn("stop_signals", pr)
        self.assertEqual(_proc.supports_fork(), POSIX)
        self.assertEqual(pr["fork"]["supported"], POSIX)
        if not POSIX:
            self.assertEqual(pr["fork"]["code"], "unsupported_platform")

    def test_summary_capability_wires_all_facets(self):
        from ai_new.modules.agent_common.plat import capability
        summary = capability()
        self.assertIn(summary["platform"], ("posix", "nt"))
        for facet in ("lock", "transport", "proc"):
            self.assertIn(facet, summary)


class LockFileTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="plat-lock-")
        self.path = str(Path(self.tmp) / "p.lock")

    def test_acquire_release_then_reacquire(self):
        first = _lock.lock_file(self.path)
        first.acquire()
        first.release()
        second = _lock.lock_file(self.path)
        second.acquire()
        second.release()

    def test_reentrant_same_thread_rejected(self):
        first = _lock.lock_file(self.path)
        first.acquire()
        again = _lock.lock_file(self.path)
        try:
            with self.assertRaises(_lock.LockError) as caught:
                again.acquire()
            self.assertEqual(caught.exception.code, "lock_reentrant")
        finally:
            first.release()
            try:
                again._handle.close()
            except OSError:
                pass

    @unittest.skipUnless(POSIX, "flock 跨句柄互斥仅 POSIX 验证")
    def test_mutual_exclusion_between_handles(self):
        import fcntl
        first = _lock.lock_file(self.path)
        first.acquire()
        fh2 = open(self.path, "a+b")  # noqa: SIM115
        try:
            with self.assertRaises(BlockingIOError):
                fcntl.flock(fh2.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        finally:
            first.release()
        fcntl.flock(fh2.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        fcntl.flock(fh2.fileno(), fcntl.LOCK_UN)
        fh2.close()

    @unittest.skipUnless(POSIX, "POSIX 阻塞语义仅本机验证")
    def test_blocking_acquire_waits_other_handle_release(self):
        import fcntl
        import threading
        first = _lock.lock_file(self.path)
        first.acquire()
        acquired = []

        def waiter():
            lock = _lock.lock_file(self.path)
            lock.acquire()
            acquired.append(True)
            lock.release()

        t = threading.Thread(target=waiter)
        t.start()
        self.assertFalse(acquired, "持锁期间等待线程不该拿到锁")
        first.release()
        t.join(timeout=5)
        self.assertTrue(acquired, "释放后等待线程应拿到锁")


class NetTransportTest(unittest.TestCase):
    def test_unix_socket_capability_matches_os(self):
        self.assertEqual(_net.supports_unix_socket(), POSIX)
        if POSIX:
            self.assertEqual(_net.default_transport(), "unix_socket")
        else:
            self.assertEqual(_net.default_transport(), "tcp_loopback")

    def test_loopback_listen_connect_roundtrip(self):
        srv, host, port = _net.loopback_listen()
        try:
            conn = _net.connect_loopback(host, port, timeout=2)
            try:
                peer = conn.getpeername()
                self.assertEqual(peer[0], host)
                self.assertEqual(peer[1], port)
            finally:
                conn.close()
        finally:
            srv.close()

    def test_addr_file_roundtrip(self):
        tmp = tempfile.mkdtemp(prefix="plat-net-")
        addr = Path(tmp) / "srv.sock"
        sidecar = _net.addr_file_for(addr)
        _net.write_addr_file(sidecar, "127.0.0.1", 4321)
        self.assertEqual(_net.read_addr_file(sidecar), ("127.0.0.1", 4321))

    def test_missing_addr_file_returns_none(self):
        self.assertIsNone(_net.read_addr_file("/nonexistent/x.port"))


class ProcSignalTest(unittest.TestCase):
    @unittest.skipUnless(POSIX, "POSIX 注册 SIGINT/SIGTERM")
    def test_install_stop_handler_posix(self):
        def handler(signum, frame):
            pass

        out = _proc.install_stop_handler(handler)
        self.assertTrue(out["ok"])
        self.assertEqual(set(out["installed"]), {"SIGINT", "SIGTERM"})
        self.assertEqual(out["unsupported"], [])

    @unittest.skipUnless(not POSIX, "Windows 只注册 SIGINT")
    def test_install_stop_handler_windows(self):
        out = _proc.install_stop_handler(lambda *a: None)
        self.assertIn("SIGINT", out["installed"])
        self.assertIn("SIGTERM", out["unsupported"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
