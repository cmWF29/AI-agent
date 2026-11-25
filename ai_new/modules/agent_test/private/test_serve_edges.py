"""API 服务端：报文鉴权/解码、监听失败、accept 轮询、shm 锁失败与通道集合。"""
from __future__ import annotations

import mmap
import os
import socket as socket_mod
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))

from ai_new.modules.agent_common.api.private import _serve as s  # noqa: E402
from ai_new.modules.agent_common.api.private import _wire  # noqa: E402


class ApiError(Exception):
    def __init__(self, message, code=""):
        super().__init__(message)
        self.code = code


class Codec:
    def __init__(self, fail=False, value=None):
        self.fail = fail
        self.value = value

    def yaml_decode(self, text):
        if self.fail:
            raise ValueError("bad")
        return {"value": self.value}

    def yaml_encode_flow(self, value):
        return {"text": "encoded"}


class Api:
    def __init__(self):
        self.calls = []

    def call(self, name, payload, caller=None, direct=False):
        self.calls.append(name)
        if name == "trace.attach":
            raise ValueError("trace")
        if name == "boom":
            raise ApiError("x", "code")
        return {"ok": True}


class Ctx:
    def __init__(self):
        self.codec = Codec()
        self.cfg = {"server": {"token": "t"}}
        self.api = Api()


class ServeTest(unittest.TestCase):
    def setUp(self):
        self.ctx = Ctx()
        self.srv = s.Server(self.ctx)

    def test_stop_and_kinds(self):
        self.srv._closed = [lambda: (_ for _ in ()).throw(OSError("x"))]
        self.srv._unlink = ["/tmp/no-such-lock-file"]
        self.srv._threads = [threading.Thread(target=lambda: None)]
        self.srv._threads[0].start()
        self.srv._threads[0].join()
        self.srv.stop()
        self.assertTrue(self.srv._stop.is_set())

        self.assertEqual(s.kinds_in({"routes": {"a": {"kind": "unix"},
                                                "b": {"kind": "direct"}},
                                     "default": {"kind": "tcp"}}), {"unix", "tcp"})
        self.assertEqual(s.kinds_in({"routes": {"a": {}}, "default": {}}), set())

    def test_start_all_channels(self):
        listen = {"unix": {"path": "/tmp/u"}, "tcp": {"port": "1", "host": "h"},
                  "shm": {"dir": "/tmp/s"}}
        with mock.patch.object(self.srv, "_start_unix") as u, \
                mock.patch.object(self.srv, "_start_tcp") as t, \
                mock.patch.object(self.srv, "_start_shm") as m:
            out = self.srv.start(listen, {"unix", "tcp", "shm"})
        self.assertEqual([o["kind"] for o in out], ["unix", "tcp", "shm"])
        u.assert_called_once()
        t.assert_called_once()
        m.assert_called_once()
        self.assertEqual(self.srv.start({}, set()), [])

    def test_handle(self):
        self.assertEqual(self.srv.handle("x"), "encoded")
        self.ctx.codec.fail = True
        self.assertEqual(self.srv.handle("x"), "encoded")
        self.ctx.codec.fail = False
        self.ctx.codec.value = {"token": "bad", "route": "a"}
        self.assertEqual(self.srv.handle("x"), "encoded")
        self.ctx.codec.value = {"token": "t", "trace": "1", "payload": {"x": 1}}
        self.assertEqual(self.srv.handle("x"), "encoded")
        self.ctx.codec.value = {"token": "t"}
        self.assertEqual(self.srv.handle("x"), "encoded")
        self.ctx.codec.value = {"token": "t", "route": "boom"}
        self.assertEqual(self.srv.handle("x"), "encoded")
        self.ctx.codec.value = {"token": "t", "route": "ok"}
        self.assertEqual(self.srv.handle("x"), "encoded")

    def test_start_and_bind_failures(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "a.sock")
            with mock.patch.object(s.plat_net, "supports_unix_socket", return_value=True), \
                    mock.patch.object(s.os, "chmod"), \
                    mock.patch.object(s.socket, "socket") as sock:
                self.srv._start_unix(path)
                self.assertEqual(len(self.srv._threads), 1)
                self.srv.stop()
                sock.return_value.close.assert_called()
            with mock.patch.object(s.plat_net, "supports_unix_socket", return_value=False), \
                    mock.patch.object(s.plat_net, "loopback_listen",
                                      return_value=(mock.Mock(), "h", 1)), \
                    mock.patch.object(s.plat_net, "write_addr_file"):
                self.srv._start_unix(path)
                self.assertEqual(len(self.srv._threads), 2)
                self.srv.stop()

        with mock.patch.object(s.socket, "socket") as sock:
            sock.return_value.bind.side_effect = OSError("bind")
            with self.assertRaises(OSError):
                self.srv._start_tcp("127.0.0.1", 1)
            sock.return_value.close.assert_called()
        with mock.patch.object(s.socket, "socket") as sock, \
                mock.patch.object(s.threading, "Thread") as th:
            self.srv._start_tcp("127.0.0.1", 1)
            th.return_value.start.assert_called()

    def test_serve_one(self):
        class Conn:
            def __init__(self, body):
                self.body = body

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def settimeout(self, v):
                pass

        with mock.patch.object(s._wire, "read_frame", return_value=None):
            self.srv._serve_one(Conn(None))
        with mock.patch.object(s._wire, "read_frame", return_value=b"x"), \
                mock.patch.object(s._wire, "send_frame") as send:
            self.srv._serve_one(Conn(b"x"))
            send.assert_called()
        with mock.patch.object(s._wire, "read_frame", side_effect=OSError("x")):
            self.srv._serve_one(Conn(None))

    def test_start_shm(self):
        with tempfile.TemporaryDirectory() as d:
            with mock.patch.object(self.srv, "_shm_loop"):
                self.srv._start_shm(d)
            self.assertEqual(len(self.srv._threads), 1)
            self.assertTrue((Path(d) / "req.bin").exists())
            sizes = (Path(d) / "req.bin").stat().st_size
            with mock.patch.object(self.srv, "_shm_loop"):
                self.srv._start_shm(d)
            self.assertEqual((Path(d) / "req.bin").stat().st_size, sizes)

    def test_shm_resp_success(self):
        with tempfile.TemporaryDirectory() as d:
            req = Path(d) / "req.bin"
            resp = Path(d) / "resp.bin"
            req.write_bytes(b"\0" * s.SHM_SIZE)
            resp.write_bytes(b"\0" * s.SHM_SIZE)
            body = b"x"
            with open(req, "r+b") as fh:
                mm = mmap.mmap(fh.fileno(), s.SHM_SIZE)
                _wire.HDR.pack_into(mm, 0, len(body), 1)
                mm[s.HDR.size:s.HDR.size + len(body)] = body
                mm.close()

            def mark(_):
                self.srv._stop.set()

            with mock.patch.object(s.time, "sleep", side_effect=mark):
                self.srv._shm_loop(req, resp)
            self.assertTrue(self.srv._stop.is_set())

    def test_accept_timeout_and_stop(self):
        self.srv._stop.set()
        self.srv._accept(mock.Mock(accept=mock.Mock(side_effect=socket_mod.timeout)))
        self.srv._stop.clear()

        calls = []

        class Sock:
            def accept(self):
                calls.append(1)
                if len(calls) == 1:
                    raise socket_mod.timeout
                self.srv._stop.set()
                return mock.Mock(), None

        class Conn:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def settimeout(self, v):
                pass

        Sock.accept = lambda self: (Conn(), None) if self.srv._stop.set() is None else (Conn(), None)
        Sock.srv = self.srv
        Sock.accept = lambda self: (self.srv._stop.set(), (Conn(), None))[1]
        self.srv._accept(Sock())
        self.assertTrue(self.srv._stop.is_set())

    def test_accept_timeout_then_stop(self):
        self.srv._stop.clear()
        count = []

        class Sock:
            def accept(self):
                count.append(1)
                if len(count) == 1:
                    raise socket_mod.timeout
                self.srv._stop.set()
                con = mock.Mock()

                class CM:
                    def __enter__(self):
                        return self

                    def __exit__(self, *a):
                        return False

                    def settimeout(self, v):
                        pass

                return CM(), None

        Sock.srv = self.srv
        self.srv._accept(Sock())
        self.assertEqual(len(count), 2)
        self.srv._stop.clear()

        class Bad:
            def accept(self):
                raise OSError("x")

        self.srv._accept(Bad())

    def test_shm_lock_failures(self):
        with tempfile.TemporaryDirectory() as d:
            req = Path(d) / "req.bin"
            resp = Path(d) / "resp.bin"
            req.write_bytes(b"\0" * s.SHM_SIZE)
            resp.write_bytes(b"\0" * s.SHM_SIZE)

            class Lock:
                def acquire(self):
                    raise s.plat_lock.LockError("timeout", "x")

                def release(self):
                    pass

            def stop_sleep(_):
                self.srv._stop.set()

            with mock.patch.object(s.plat_lock, "ExclusiveLock", side_effect=lambda *a, **k: Lock()), \
                    mock.patch.object(s.time, "sleep", side_effect=stop_sleep):
                self.srv._shm_loop(req, resp)

            counter = []

            class RespLock:
                def acquire(self):
                    counter.append(1)
                    if len(counter) == 2:
                        raise s.plat_lock.LockError("timeout", "x")

                def release(self):
                    pass

            self.srv._stop.clear()
            body = "x".encode()
            with open(req, "r+b") as fh:
                mm = mmap.mmap(fh.fileno(), s.SHM_SIZE)
                _wire.HDR.pack_into(mm, 0, len(body), 1)
                mm[s.HDR.size:s.HDR.size + len(body)] = body
                mm.close()

            def mark(_):
                self.srv._stop.set()

            with mock.patch.object(s.plat_lock, "ExclusiveLock", side_effect=lambda *a, **k: RespLock()), \
                    mock.patch.object(s.time, "sleep", side_effect=mark):
                self.srv._shm_loop(req, resp)


if __name__ == "__main__":
    unittest.main()
