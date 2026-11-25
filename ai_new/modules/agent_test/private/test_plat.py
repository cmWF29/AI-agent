"""plat 平台适配层靶向单测：锁互斥/重入、传输档位与回退、进程信号能力上报。

平台差异只在能力判定内部消化；用例一律打 ``plat`` 公共接口，同一批断言在
Linux 与 Windows 真机都跑，不因 OS 名 skip。
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

from ai_new.modules.agent_common.plat.private import _lock, _net, _proc  # noqa: E402

POSIX = os.name != "nt"
REPO_ROOT = Path(__file__).resolve().parents[4]


def _wait_path(path, timeout=10.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if os.path.exists(path):
            return True
        time.sleep(0.05)
    return False


def _spawn_lock_child(path, ready, hold=30.0, done=""):
    """子进程持锁；所有 OS 都走 plat 公共接口。"""
    child_code = (
        "import sys,time;"
        "from ai_new.modules.agent_common.plat.private import _lock;"
        "l=_lock.lock_file(sys.argv[1]);l.acquire();"
        "open(sys.argv[2],'w').write('ready');"
        "time.sleep(float(sys.argv[3]));"
        "open(sys.argv[4],'w').write('done') if len(sys.argv)>4 and sys.argv[4] else None;"
        "l.release()"
    )
    env = os.environ.copy()
    env["PYTHONPATH"] = str(REPO_ROOT) + os.pathsep + env.get("PYTHONPATH", "")
    return subprocess.Popen(
        [sys.executable, "-c", child_code, path, ready, str(hold), done],
        cwd=str(REPO_ROOT), env=env,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


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
        self.assertEqual(tr["unix_socket"], _net.supports_unix_socket())

    def test_proc_capability_shape(self):
        pr = _proc.proc_capability()
        self.assertTrue(pr["ok"])
        self.assertIn("fork", pr)
        self.assertIn("stop_signals", pr)
        self.assertEqual(pr["fork"]["supported"], _proc.supports_fork())
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

    def test_mutual_exclusion_between_processes(self):
        # 第二把锁在子进程里抢；同一进程会先命中重入守卫，跨进程才验证 OS 原语。
        ready = str(Path(self.tmp) / "child-ready")
        child = _spawn_lock_child(self.path, ready)
        try:
            self.assertTrue(_wait_path(ready), "子进程未拿到锁")
            waiter = _lock.lock_file(self.path, timeout=0.8)
            with self.assertRaises(_lock.LockError) as caught:
                waiter.acquire()
            self.assertEqual(caught.exception.code, "lock_timeout")
            waiter.release()
        finally:
            child.terminate()
            child.wait(timeout=5)

    def test_waiter_acquires_after_other_process_release(self):
        ready = str(Path(self.tmp) / "child-ready-2")
        done = str(Path(self.tmp) / "child-done")
        child = _spawn_lock_child(self.path, ready, hold=1.0, done=done)
        try:
            self.assertTrue(_wait_path(ready))
            waiter = _lock.lock_file(self.path, timeout=5.0)
            waiter.acquire()
            waiter.release()
            self.assertTrue(_wait_path(done))
        finally:
            child.wait(timeout=10)


class NetTransportTest(unittest.TestCase):
    def test_unix_socket_capability_matches_probe(self):
        supported = _net.supports_unix_socket()
        self.assertEqual(_net.default_transport(),
                         "unix_socket" if supported else "tcp_loopback")

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
    def test_install_stop_handler_contract(self):
        out = _proc.install_stop_handler(lambda *a: None)
        self.assertTrue(out["ok"])
        self.assertIn("SIGINT", out["installed"])
        # POSIX 两路信号都可注册；Windows 的 SIGTERM 由 TerminateProcess 直达，
        # 接口层显式归到 unsupported，调用方不再按 OS 名分支。
        if POSIX:
            self.assertEqual(set(out["installed"]), {"SIGINT", "SIGTERM"})
            self.assertEqual(out["unsupported"], [])
        else:
            self.assertIn("SIGTERM", out["unsupported"])


class CrossProcessLockTest(unittest.TestCase):
    """跨进程锁争用：子进程持锁不放，父进程限时等待必须超时释放，异常路径不留句柄。"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="plat-xlock-")
        self.path = str(Path(self.tmp) / "project.lock")
        self.ready = str(Path(self.tmp) / "ready")

    def _spawn_child(self):
        child_code = (
            "import sys,time;"
            "from ai_new.modules.agent_common.plat.private import _lock;"
            "l=_lock.lock_file(sys.argv[1]);l.acquire();"
            "open(sys.argv[2],'w').write('ready');time.sleep(30)"
        )
        env = os.environ.copy()
        env["PYTHONPATH"] = str(REPO_ROOT) + os.pathsep + env.get("PYTHONPATH", "")
        return subprocess.Popen(
            [sys.executable, "-c", child_code, self.path, self.ready],
            cwd=str(REPO_ROOT), env=env,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def _wait_ready(self, proc, timeout=5.0):
        deadline = time.time() + timeout
        while time.time() < deadline:
            if os.path.exists(self.ready):
                return True
            time.sleep(0.05)
        return False

    def test_contended_lock_times_out_then_releases(self):
        proc = self._spawn_child()
        try:
            self.assertTrue(self._wait_ready(proc), "子进程未拿到锁")
            waiter = _lock.lock_file(self.path, timeout=1.5)
            try:
                with self.assertRaises(_lock.LockError) as caught:
                    waiter.acquire()
                self.assertEqual(caught.exception.code, "lock_timeout")
            finally:
                # 异常路径：持锁句柄必须收口，不随进程残留。
                try:
                    waiter.release()
                except OSError:
                    pass
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=5)
        # 子进程退出、锁释放后，父进程可正常拿锁。
        lock = _lock.lock_file(self.path)
        lock.acquire()
        lock.release()

    def test_timeout_does_not_block_forever(self):
        # 未竞争场景：短超时正常拿到，不触发超时分支。
        lock = _lock.lock_file(self.path, timeout=2.0)
        lock.acquire()
        lock.release()


class SidecarTcpTest(unittest.TestCase):
    """loopback TCP：监听/回连/关闭；无 AF_UNIX 平台的侧车文件随 stop 清理。"""

    def test_listen_connect_peer_matches(self):
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

    def test_unix_tcp_fallback_sidecar_cleaned_on_stop(self):
        # 通过能力注入强制走回退分支：任何 OS 都能验证同一接口的 sidecar 生命周期。
        from ai_new.modules.agent_common.api.private import _serve
        from unittest import mock

        with tempfile.TemporaryDirectory() as tmp:
            sock_path = str(Path(tmp) / "api.sock")
            sidecar = _net.addr_file_for(sock_path)
            server = _serve.Server(_minimal_ctx())
            with mock.patch.object(_net, "supports_unix_socket", return_value=False):
                server.start({"unix": {"path": sock_path}}, {"unix"})
            try:
                self.assertTrue(Path(sidecar).is_file(), "侧车端口文件未写出")
                host, port = _net.read_addr_file(sidecar)
                conn = _net.connect_loopback(host, port, timeout=2)
                conn.close()
            finally:
                server.stop()
            self.assertFalse(Path(sidecar).exists(), "stop 后侧车端口文件未清理")


class ShmMmailboxTest(unittest.TestCase):
    """shm 信箱：文件 mmap + 锁的请求/应答往返，读写内容一致。"""

    def test_shm_roundtrip_consistent(self):
        from ai_new.modules.agent_common.api.private import _serve, _transport

        with tempfile.TemporaryDirectory() as tmp:
            directory = str(Path(tmp) / "shm")
            server_ctx = _minimal_ctx()
            server_ctx.api.routes = {"ops.ping": lambda p: {"pong": p.get("n"), "via": "shm"}}
            server = _serve.Server(server_ctx)
            server.start({"shm": {"dir": directory}}, {"shm"})
            try:
                client = _transport.Transport(_minimal_ctx({
                    "default": {"kind": "direct"},
                    "listen": {"shm": {"dir": directory}},
                    "routes": {"ops.*": {"kind": "shm"}}}))
                self.assertEqual(
                    client.send("ops.ping", {"n": 11}, lambda c, p: {"local": 1}),
                    {"pong": 11, "via": "shm"})
            finally:
                server.stop()


def _minimal_ctx(bindings=None):
    """测试最小 ctx：够 _serve/_transport 转调用与编解码。"""
    import yaml
    from ai_new.modules.agent_common.codec.private import _codec

    class _ApiError(Exception):
        def __init__(self, msg, code="", status=400):
            super().__init__(msg)
            self.code = code
            self.status = status

    class _Storage:
        def __init__(self, record):
            self.record = record

        def own(self, anchor):
            return self

        def read_text(self, rel):
            return yaml.safe_dump(self.record or {}, allow_unicode=True,
                                  sort_keys=False)

        def exists(self, rel):
            return self.record is not None

    class _Api:
        def __init__(self):
            self.routes = {}
            self.calls = []

        def call(self, name, payload=None, caller=None, direct=False):
            self.calls.append(name)
            fn = self.routes.get(name)
            if fn is None:
                raise LookupError("路由未注册: %s" % name)
            return fn(payload or {})

    class _Ctx:
        ApiError = _ApiError

        def __init__(self, bindings):
            self.storage = _Storage(bindings)
            self.cfg = {"server": {"token": ""}, "api": {"transport_timeout": 3}}
            self.root = REPO_ROOT
            self.codec = _codec
            self.api = _Api()

    return _Ctx(bindings)


if __name__ == "__main__":
    unittest.main(verbosity=2)
