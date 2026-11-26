"""API 传输：绑定解析、报文封装、四通道派发与故障分支。"""
from __future__ import annotations

import mmap
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))

from ai_new.modules.agent_common.api.private import _transport as t
from ai_new.modules.agent_common.api.private import _wire


class ApiError(Exception):
    def __init__(self, message, code="error", status=500):
        super().__init__(message)
        self.code = code
        self.status = status


class Md:
    def __init__(self, files):
        self.files = files

    def exists(self, name):
        return name in self.files

    def read_text(self, name):
        return self.files[name]


class Storage:
    def __init__(self, files):
        self.files = files

    def own(self, path):
        return Md(self.files)


class Codec:
    def __init__(self, value=None):
        self.value = value or {}

    def yaml_decode(self, text):
        return {"value": self.value}

    def yaml_encode_flow(self, rec):
        return {"text": "x"}


class Ctx:
    def __init__(self):
        self.storage = Storage({"gen/bindings.yaml": "x"})
        self.codec = Codec()
        self.cfg = {"api": {"transport_timeout": "bad"}}
        self.ApiError = ApiError


class Conn:
    def __init__(self, frames):
        self.frames = frames
        self.closed = False
        self.timeout = None

    def settimeout(self, v):
        self.timeout = v

    def connect(self, addr):
        pass

    def close(self):
        self.closed = True


class TransportEdgesTest(unittest.TestCase):
    def setUp(self):
        self.ctx = Ctx()
        self.tr = t.Transport(self.ctx)

    def test_bindings_and_kind(self):
        self.ctx.codec = Codec({"routes": {"a.b": {"kind": "unix"}, "c.*": {"kind": "tcp"}},
                                "listen": {"unix": {"path": "/tmp/x"},
                                           "tcp": {"port": 1},
                                           "shm": {"dir": "/tmp/s"}}})
        self.assertEqual(self.tr.kind_for("a.b"), ("unix", "/tmp/x"))
        self.assertEqual(self.tr.kind_for("c.d"), ("tcp", "127.0.0.1:1"))
        self.assertEqual(self.tr.kind_for("x.y"), ("direct", None))
        self.ctx.codec.value = {"routes": {"a.b": {"kind": "shm"}},
                                "listen": {"shm": {"dir": "/tmp/s"}}}
        self.tr.reload()
        self.assertEqual(self.tr.kind_for("a.b"), ("shm", "/tmp/s"))
        self.ctx.codec.value = {"routes": {"a.b": {"kind": "tcp"}}, "listen": {"tcp": {}}}
        self.tr.reload()
        self.assertEqual(self.tr.kind_for("a.b"), ("tcp", None))
        self.ctx.codec.value = {"default": {"kind": "bogus"}}
        self.tr.reload()
        with self.assertRaises(ApiError):
            self.tr.kind_for("a.b")
        self.ctx.codec.value = {}
        self.tr.reload()
        desc = self.tr.describe()
        self.assertEqual(desc["default"], "direct")
        self.assertEqual(desc["source"], "未生成，全直连")
        self.assertEqual(self.tr._timeout(), 10.0)

    def test_pack_unpack_roundtrip(self):
        self.ctx.codec = mock.Mock()
        self.ctx.codec.yaml_encode_flow.return_value = {"text": "x"}
        self.ctx.codec.yaml_decode.return_value = {"value": {"ok": True, "result": 3}}
        self.ctx.cfg["server"] = {"token": "tok"}
        self.assertIsInstance(self.tr._pack("a.b", {"x": 1}), (str, bytes))
        self.assertEqual(self.tr._unpack("a.b", "x"), 3)
        self.ctx.codec.yaml_decode.return_value = {"value": {"ok": False, "error": "e"}}
        with self.assertRaises(ApiError):
            self.tr._unpack("a.b", "x")
        conn = Conn([])
        with mock.patch.object(t._wire, "send_frame") as sf, \
                mock.patch.object(t._wire, "read_frame", return_value=None):
            self.assertIsNone(self.tr._roundtrip(conn, "a.b", b"", False))
            with self.assertRaises(ApiError):
                self.tr._roundtrip(conn, "a.b", b"", True)
            self.ctx.codec.yaml_decode.return_value = {"value": {"ok": True, "result": 1}}
            with mock.patch.object(t._wire, "read_frame", return_value=b"x"):
                self.assertEqual(self.tr._roundtrip(conn, "a.b", b"", True), 1)
            sf.assert_called()

    def test_send_dispatch(self):
        self.tr.kind_for = lambda route: ("direct", None)
        self.assertEqual(self.tr.send("a", {"x": 1}, lambda c, p: p), {"x": 1})
        self.assertEqual(self.tr.notify("a", {"x": 1}, lambda c, p: p)["transport"], "direct")
        for kind in ("unix", "tcp", "shm"):
            self.tr.kind_for = lambda route, k=kind: (k, "addr")
            with mock.patch.object(self.tr, "_" + kind, return_value=7) as m:
                self.assertEqual(self.tr.send("a", {}, None), 7)
                self.assertEqual(self.tr.notify("a", {}, None)["sent"], "a")
                m.assert_called()
        self.tr.kind_for = lambda route: ("bogus", None)
        with self.assertRaises(ApiError):
            self.tr.send("a", {}, None)
        with self.assertRaises(ApiError):
            self.tr.notify("a", {}, None)

    def test_unix(self):
        tr = self.tr
        with self.assertRaises(ApiError):
            tr._unix("", "a", b"x")
        with mock.patch.object(t.plat_net, "supports_unix_socket", return_value=False), \
                mock.patch.object(t.plat_net, "read_addr_file", return_value=None):
            with self.assertRaises(ApiError):
                tr._unix("/tmp/x", "a", b"x")
        with mock.patch.object(t.plat_net, "supports_unix_socket", return_value=False), \
                mock.patch.object(t.plat_net, "read_addr_file", return_value=("h", 1)), \
                mock.patch.object(t.plat_net, "connect_loopback",
                                  side_effect=OSError("x")):
            with self.assertRaises(ApiError):
                tr._unix("/tmp/x", "a", b"x")
        with mock.patch.object(t.plat_net, "supports_unix_socket", return_value=True), \
                mock.patch.object(t.socket, "socket") as sock:
            sock.return_value.connect.side_effect = OSError("x")
            with self.assertRaises(ApiError):
                tr._unix("/tmp/x", "a", b"x")
        with mock.patch.object(t.plat_net, "supports_unix_socket", return_value=True), \
                mock.patch.object(t.socket, "socket") as sock, \
                mock.patch.object(tr, "_roundtrip", return_value=9):
            self.assertEqual(tr._unix("/tmp/x", "a", b"x"), 9)
        with mock.patch.object(t.plat_net, "supports_unix_socket", return_value=False), \
                mock.patch.object(t.plat_net, "read_addr_file", return_value=("h", 1)), \
                mock.patch.object(t.plat_net, "connect_loopback", return_value=Conn([])), \
                mock.patch.object(tr, "_roundtrip", return_value=8):
            self.assertEqual(tr._unix("/tmp/x", "a", b"x"), 8)

    def test_tcp(self):
        with self.assertRaises(ApiError):
            self.tr._tcp("", "a", b"x")
        with mock.patch.object(t.socket, "socket") as sock:
            sock.return_value.connect.side_effect = OSError("x")
            with self.assertRaises(ApiError):
                self.tr._tcp("h:1", "a", b"x")
        with mock.patch.object(t.socket, "socket") as sock, \
                mock.patch.object(self.tr, "_roundtrip", return_value=6):
            sock.return_value.connect.side_effect = OSError("x")
            with self.assertRaises(ApiError):
                self.tr._tcp("h:1", "a", b"x")
        with mock.patch.object(t.socket, "socket") as sock, \
                mock.patch.object(self.tr, "_roundtrip", return_value=6):
            self.assertEqual(self.tr._tcp("h:1", "a", b"x"), 6)

    def test_shm(self):
        tr = self.tr
        with self.assertRaises(ApiError):
            tr._shm("", "a", b"x")
        with tempfile.TemporaryDirectory() as d:
            req = Path(d) / "req.bin"
            req.write_bytes(b"\0" * 16)
            self.assertEqual(tr._shm(d, "a", b"x", expect=False), None)
            resp = Path(d) / "resp.bin"
            resp.write_bytes(b"\0" * 16)
            tr._timeout = lambda: 0
            with self.assertRaises(ApiError):
                tr._shm(d, "a", b"x", expect=True)
            tr._seq = 0
            tr._timeout = lambda: 1
            with open(resp, "r+b") as fh:
                mm = mmap.mmap(fh.fileno(), 0)
                _wire.HDR.pack_into(mm, 0, 3, 1)
                mm[8:11] = b"ok!"
                mm.close()
            self.ctx.codec.yaml_decode = lambda text: {"value": {"ok": True, "result": text}}
            self.assertEqual(tr._shm(d, "a", b"x", expect=True), "ok!")
            with mock.patch.object(t.plat_lock, "ExclusiveLock") as lock:
                lock.return_value.acquire.side_effect = t.plat_lock.LockError("timeout", "x")
                with self.assertRaises(ApiError):
                    tr._shm(d, "a", b"x")
            counter = []

            class Lock:
                def __init__(self, *a, **k):
                    pass

                def acquire(self):
                    counter.append(1)
                    if len(counter) == 2:
                        raise t.plat_lock.LockError("timeout", "x")

                def release(self):
                    pass

            tr._timeout = lambda: 1
            with mock.patch.object(t.plat_lock, "ExclusiveLock", Lock), \
                    mock.patch.object(t.time, "time", side_effect=[0, 0, 0, 0, 0, 9]):
                with self.assertRaises(ApiError):
                    tr._shm(d, "a", b"x", expect=True)
            with mock.patch.object(t.plat_lock, "ExclusiveLock") as lock:
                lock.return_value.acquire.side_effect = t.plat_lock.LockError("timeout", "x")
                tr._timeout = lambda: 0
                with self.assertRaises(ApiError):
                    tr._shm(d, "a", b"x", expect=True)
            Path(d, "resp.bin").unlink()
            Path(d, "resp.bin").mkdir()
            tr._timeout = lambda: 1
            with self.assertRaises(ApiError):
                tr._shm(d, "a", b"x", expect=True)
            with self.assertRaises(ApiError):
                tr._shm(d + "/missing", "a", b"x")

    def test_seq(self):
        self.tr._seq = 0x7FFFFFFE
        self.assertEqual(self.tr._next_seq(), 1)
        self.assertEqual(self.tr._next_seq(), 1)


if __name__ == "__main__":
    unittest.main()
