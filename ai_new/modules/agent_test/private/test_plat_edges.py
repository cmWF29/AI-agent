"""平台适配层边角：能力汇总挂载、UNIX 探测收尾、loopback 重试、连接文件、信号安装。"""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))

from ai_new.modules.agent_common import plat as plat_pkg
from ai_new.modules.agent_common.plat.private import _net as n
from ai_new.modules.agent_common.plat.private import _proc


class FakeSock:
    """最小 socket 替身：按构造序号控制哪一步失败。"""

    made = []

    def __init__(self, tag="ok", fail_close=False):
        self.tag = tag
        self.fail_close = fail_close
        self.closed = False
        FakeSock.made.append(self)

    def bind(self, addr):
        pass

    def listen(self, n):
        pass

    def settimeout(self, t):
        pass

    def setsockopt(self, *a):
        pass

    def getsockname(self):
        return ("127.0.0.1", 0)

    def connect(self, addr):
        pass

    def accept(self):
        return FakeSock("conn"), None

    def close(self):
        self.closed = True
        if self.fail_close:
            raise OSError("close failed")


class PlatPackageTest(unittest.TestCase):
    def test_setup_mounts_ctx_plat_and_registers(self):
        registered = {}

        class Api:
            def register(self, name, fn, desc=None, module=None):
                registered[name] = fn

        ctx = SimpleNamespace(api=Api())
        self.assertTrue(plat_pkg.setup(ctx))
        self.assertTrue(hasattr(ctx, "plat"))
        self.assertIs(ctx.plat.lock, __import__(
            "ai_new.modules.agent_common.plat.private._lock", fromlist=["x"]))
        cap = registered["plat.capability"](ctx, {})
        self.assertEqual(sorted(cap), ["lock", "platform", "proc", "transport"])
        self.assertEqual(cap["platform"], _proc.PLATFORM)
        self.assertEqual(ctx.plat.capability(), cap)


class ProbeUnixTest(unittest.TestCase):
    def setUp(self):
        FakeSock.made = []

    def test_probe_true_and_cleanup_errors_swallowed(self):
        socks = {"i": 0}

        def factory(*a, **kw):
            socks["i"] += 1
            # 第 2 个是 cli：关闭时报错，走到 finally 的捕获分支
            return FakeSock("s%d" % socks["i"], fail_close=socks["i"] == 2)

        with mock.patch.object(n.socket, "socket", side_effect=factory), \
                mock.patch.object(n.os, "unlink", mock.Mock(side_effect=OSError("x"))), \
                mock.patch.object(n.os, "rmdir", mock.Mock(side_effect=OSError("x"))):
            self.assertTrue(n._probe_unix_socket())
        self.assertEqual(socks["i"], 2)  # srv + cli；accept 回来的 conn 走替身自身

    def test_probe_false_when_connect_fails(self):
        def factory(*a, **kw):
            sock = FakeSock()
            if len(FakeSock.made) == 2:
                sock.connect = mock.Mock(side_effect=OSError("no"))
            return sock

        with mock.patch.object(n.socket, "socket", side_effect=factory):
            self.assertFalse(n._probe_unix_socket())


class LoopbackTest(unittest.TestCase):
    def test_retry_exhausted_raises_with_detail(self):
        closed = []

        def factory(*a, **kw):
            sock = FakeSock()
            sock.bind = mock.Mock(side_effect=OSError("in use"))
            sock.close = mock.Mock(side_effect=lambda: closed.append(1))
            return sock

        with mock.patch.object(n.socket, "socket", side_effect=factory), \
                mock.patch.object(n.time, "sleep", mock.Mock()):
            with self.assertRaises(OSError) as cm:
                n.loopback_listen()
        self.assertIn("重试 5 次仍失败", str(cm.exception))
        self.assertEqual(len(closed), n.LISTEN_RETRIES)

    def test_addr_file_roundtrip_and_bad_content(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "x.port")
            n.write_addr_file(path, "127.0.0.1", 1234)
            self.assertEqual(n.read_addr_file(path), ("127.0.0.1", 1234))
            self.assertEqual(n.addr_file_for("/tmp/x.sock"), "/tmp/x.sock.port")
            Path(path).write_text("")
            self.assertIsNone(n.read_addr_file(path))
            self.assertIsNone(n.read_addr_file(os.path.join(d, "missing")))

    def test_connect_loopback_sets_timeout(self):
        sock = FakeSock()
        with mock.patch.object(n.socket, "socket", return_value=sock), \
                mock.patch.object(n.socket, "socket") as patched:
            patched.return_value = sock
            got = n.connect_loopback("127.0.0.1", "9", timeout=0.5)
        self.assertIs(got, sock)
        with mock.patch.object(n.socket, "socket", return_value=FakeSock()):
            self.assertIsNotNone(n.connect_loopback("127.0.0.1", "9"))  # 不给 timeout 仍可连


class ProcSignalTest(unittest.TestCase):
    def test_posix_signal_install_and_restore(self):
        import signal
        before = {s: signal.getsignal(s) for s in (signal.SIGINT, signal.SIGTERM)}
        try:
            got = _proc.install_stop_handler(lambda s, f: None)
            self.assertTrue(got["ok"])
            self.assertEqual(sorted(got["installed"]), ["SIGINT", "SIGTERM"])
        finally:
            for s, h in before.items():
                signal.signal(s, h)

    def test_posix_install_failure_collected(self):
        with mock.patch.object(_proc, "PLATFORM", "posix"), \
                mock.patch("signal.signal", side_effect=ValueError("no")):
            got = _proc.install_stop_handler(lambda s, f: None)
        self.assertFalse(got["ok"])
        self.assertEqual(got["unsupported"], ["SIGINT", "SIGTERM"])

    def test_windows_branch_installs_sigint_only(self):
        import signal
        before = signal.getsignal(signal.SIGINT)
        try:
            with mock.patch.object(_proc, "PLATFORM", "nt"):
                got = _proc.install_stop_handler(lambda s, f: None)
            self.assertEqual(got["installed"], ["SIGINT"])
            self.assertEqual(got["unsupported"], ["SIGTERM"])
        finally:
            signal.signal(signal.SIGINT, before)

    def test_windows_branch_sigint_failure(self):
        with mock.patch.object(_proc, "PLATFORM", "nt"), \
                mock.patch("signal.signal", side_effect=OSError("no")):
            got = _proc.install_stop_handler(lambda s, f: None)
        self.assertFalse(got["ok"])
        self.assertEqual(got["unsupported"], ["SIGINT", "SIGTERM"])

    def test_supports_fork(self):
        with mock.patch.object(_proc, "PLATFORM", "nt"):
            self.assertFalse(_proc.supports_fork())
        with mock.patch.object(_proc, "PLATFORM", "posix"):
            self.assertTrue(_proc.supports_fork())


if __name__ == "__main__":
    unittest.main()
