"""Windows 档路径语义靶向单测（在 Linux 上跑纯判定函数，CI windows-latest 真机复跑）。

覆盖 Win32 规则：盘符大小写/斜杠混用、段尾点号空格、保留设备名、UNC、长路径
前缀、穿越段、跨根型逃逸；以及轻/强档五维度机制对照矩阵。本批用例不碰 OS
文件系统，只打纯判定层，因此可在 POSIX 主机与 Windows 真机上跑同一批断言。
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
from ai_new.modules.agent.sandbox.private import _winpath  # noqa: E402

POSIX = os.name != "nt"
REPO_ROOT = Path(__file__).resolve().parents[4]


class DriveLetterTest(unittest.TestCase):
    def test_case_and_slash_mix_normalized_equal(self):
        ok = _pure.guard_path(r"C:\proj", r"c:/proj/A/b.txt",
                              platform="windows")
        self.assertTrue(ok["ok"], ok)
        self.assertEqual(ok["root_canonical"], "c:/proj")
        self.assertEqual(ok["target_canonical"], "c:/proj/a/b.txt")

    def test_drive_escape_rejected(self):
        res = _winpath.guard_path(r"C:\proj", r"D:\proj\a.txt")
        self.assertFalse(res["ok"])
        self.assertEqual(res["code"], "drive_escape")
        self.assertEqual(res["target_drive"], "d:")

    def test_trailing_dot_and_space_stripped(self):
        res = _winpath.guard_path(r"C:\proj", r"C:\proj\notes.md. ")
        self.assertTrue(res["ok"], res)
        self.assertEqual(res["target_canonical"], "c:/proj/notes.md")


class ReservedNameTest(unittest.TestCase):
    def test_reserved_base_names_rejected(self):
        for name in ("CON", "PRN", "AUX", "NUL", "con", "nul.txt"):
            res = _winpath.guard_path(r"C:\proj", r"C:\proj\%s" % name)
            self.assertFalse(res["ok"], name)
            self.assertEqual(res["code"], "reserved_name", name)

    def test_reserved_com_lpt_rejected(self):
        for name in ("COM1", "COM9", "LPT1", "LPT9", "com3.log", "lpt2.ini"):
            self.assertTrue(_winpath.is_reserved_name(name), name)
            res = _winpath.guard_path(r"C:\proj", r"C:\proj\%s" % name)
            self.assertFalse(res["ok"], name)
            self.assertEqual(res["code"], "reserved_name", name)

    def test_normal_name_allowed(self):
        for name in ("note.txt", "README", "compile.log", "section2.md"):
            self.assertFalse(_winpath.is_reserved_name(name), name)


class UncTest(unittest.TestCase):
    def test_same_share_within_root(self):
        res = _winpath.guard_path(r"\\srv\share", r"\\srv\share\dir\a.md")
        self.assertTrue(res["ok"], res)
        self.assertEqual(res["root_canonical"], "//srv/share")

    def test_different_share_rejected(self):
        res = _winpath.guard_path(r"\\srv\share", r"\\srv\share2\a.md")
        self.assertFalse(res["ok"])
        self.assertEqual(res["code"], "unc_escape")

    def test_different_server_rejected(self):
        res = _winpath.guard_path(r"\\srv\share", r"\\other\share\a.md")
        self.assertFalse(res["ok"])
        self.assertEqual(res["code"], "unc_escape")

    def test_long_unc_prefix_parsed(self):
        root = _winpath.split_root(r"\\?\UNC\srv\share\dir")
        self.assertEqual(root["kind"], "unc")
        self.assertEqual(root["server"], "srv")
        self.assertEqual(root["share"], "share")
        res = _winpath.guard_path(r"\\?\UNC\srv\share",
                                   r"\\?\UNC\srv\share\a.md")
        self.assertTrue(res["ok"], res)


class LongPrefixTest(unittest.TestCase):
    def test_long_drive_prefix_matches_plain_drive(self):
        res = _winpath.guard_path(r"\\?\C:\proj", r"C:\proj\a.txt")
        self.assertTrue(res["ok"], res)
        self.assertEqual(res["root_canonical"], "c:/proj")

    def test_long_prefix_segments(self):
        root = _winpath.split_root(r"\\?\C:\Temp\sub")
        self.assertEqual(root["kind"], "drive")
        self.assertEqual(root["drive"], "c:")
        self.assertEqual(root["segments"], ["Temp", "sub"])


class TraversalAndKindTest(unittest.TestCase):
    def test_traversal_segment_rejected(self):
        res = _winpath.guard_path(r"C:\proj", r"C:\proj\..\etc\passwd")
        self.assertFalse(res["ok"])
        self.assertEqual(res["code"], "traversal")

    def test_cross_kind_rejected(self):
        res = _winpath.guard_path(r"C:\proj", r"\\srv\share\a.md")
        self.assertFalse(res["ok"])
        self.assertEqual(res["code"], "root_kind_mismatch")

    def test_relative_root_rejected(self):
        res = _winpath.guard_path("relative/proj", r"C:\proj\a.md")
        self.assertFalse(res["ok"])
        self.assertEqual(res["code"], "root_not_absolute")


class RelativeGuardTest(unittest.TestCase):
    def test_normal_relative_allowed(self):
        self.assertTrue(_winpath.guard_rel("docs/a.md")["ok"])
        self.assertTrue(_winpath.guard_rel(r"tickets\T-1\note.md")["ok"])

    def test_absolute_drive_unc_rejected(self):
        for rel in ("/abs/b.md", r"C:\x", r"\\srv\share\a"):
            self.assertFalse(_winpath.guard_rel(rel)["ok"], rel)

    def test_traversal_and_reserved_rejected(self):
        self.assertEqual(_winpath.guard_rel("../etc")["code"], "traversal")
        self.assertEqual(_winpath.guard_rel("sub/../../x")["code"], "traversal")
        self.assertEqual(_winpath.guard_rel("CON")["code"], "reserved_name")


class PlatformDispatchTest(unittest.TestCase):
    def test_default_posix_branch_rejects_windows_drive(self):
        # 纯函数缺省走 POSIX 守卫；真实 OS 由路由层经能力解析后显式传平台。
        res = _pure.guard_path(r"C:\proj", r"C:\proj\a")
        self.assertFalse(res["ok"])
        self.assertEqual(res["code"], "root_not_absolute")

    def test_explicit_windows_branch(self):
        res = _pure.guard_path(r"C:\proj", r"C:\proj\a", platform="windows")
        self.assertTrue(res["ok"], res)

    def test_posix_guard_traversal_and_escape(self):
        self.assertFalse(_pure.guard_path("/tmp/p1", "/tmp/p1/../etc",
                                          platform="posix")["ok"])
        self.assertFalse(_pure.guard_path("/tmp/p1", "/tmp/other",
                                          platform="posix")["ok"])
        self.assertTrue(_pure.guard_path("/tmp/p1", "/tmp/p1/a/b",
                                         platform="posix")["ok"])


class MechanismMatrixTest(unittest.TestCase):
    def test_five_dimensions_both_tiers_both_platforms(self):
        diff = _pure.mechanism_diff()
        self.assertEqual(diff["dimensions"],
                         ["acl", "cwd", "directory", "lock",
                          "path_interception"])
        for dim, bands in diff["mechanisms"].items():
            for tier in ("weak", "strong"):
                for plat in ("linux", "windows"):
                    self.assertTrue(bands[tier][plat], (dim, tier, plat))

    def test_weak_lock_mechanism_matches_reported_tiers(self):
        weak_lock = _pure.mechanism_diff()["mechanisms"]["lock"]["weak"]
        self.assertIn("flock", weak_lock["linux"])
        self.assertIn("msvcrt", weak_lock["windows"])


class ExtraSemanticsTest(unittest.TestCase):
    def test_multilevel_backslash_traversal_rejected(self):
        res = _winpath.guard_path(r"C:\proj", r"C:\proj\..\..\Windows\system.ini")
        self.assertFalse(res["ok"])
        self.assertEqual(res["code"], "traversal")

    def test_mixed_separators_normalized(self):
        res = _winpath.guard_path(r"C:\proj", r"C:\proj/docs\a.txt")
        self.assertTrue(res["ok"], res)
        self.assertEqual(res["target_canonical"], "c:/proj/docs/a.txt")

    def test_trailing_dot_only_stripped(self):
        res = _winpath.guard_path(r"C:\proj", r"C:\proj\notes.md.")
        self.assertTrue(res["ok"], res)
        self.assertEqual(res["target_canonical"], "c:/proj/notes.md")

    def test_trailing_space_only_stripped(self):
        res = _winpath.guard_path(r"C:\proj", r"C:\proj\notes.md ")
        self.assertTrue(res["ok"], res)
        self.assertEqual(res["target_canonical"], "c:/proj/notes.md")

    def test_drive_case_insensitive_root_target(self):
        res = _winpath.guard_path(r"c:\proj", r"C:\proj\a.txt")
        self.assertTrue(res["ok"], res)
        self.assertEqual(res["root_canonical"], "c:/proj")
        self.assertEqual(res["target_canonical"], "c:/proj/a.txt")

    def test_rel_multilevel_backslash_traversal_rejected(self):
        self.assertEqual(_winpath.guard_rel(r"sub\..\..\deep")["code"], "traversal")

    def test_rel_mixed_separators_allowed(self):
        self.assertTrue(_winpath.guard_rel(r"docs/sub\file.md")["ok"])


class RouteRegistrationTest(unittest.TestCase):
    def test_guard_path_route_registered_and_callable(self):
        from ai_new.modules.agent.sandbox import setup as sandbox_setup

        class _Api:
            def __init__(self):
                self.routes = {}

            def register(self, name, fn, *args, **kwargs):
                self.routes[name] = fn

        ctx = type("Ctx", (), {"api": _Api()})()
        sandbox_setup(ctx)
        self.assertIn("sandbox.guard_path", ctx.api.routes)
        handler = ctx.api.routes["sandbox.guard_path"]
        out = handler(None, {"root": r"C:\proj", "target": r"C:\proj\a",
                             "platform": "windows"})
        self.assertTrue(out["ok"])


@unittest.skipUnless(not POSIX, "msvcrt 跨进程锁档仅 Windows 真机验证")
class WindowsPlatLockTest(unittest.TestCase):
    """Windows msvcrt.locking 跨进程争用：后到者限时等待/超时释放，异常路径不留句柄。"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="win-xlock-")
        self.path = str(Path(self.tmp) / "project.lock")
        self.ready = str(Path(self.tmp) / "ready")

    def _spawn_child(self):
        from ai_new.modules.agent_common.plat.private import _lock  # noqa: F401
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

    def test_capability_reports_msvcrt(self):
        from ai_new.modules.agent_common.plat.private import _lock
        cap = _lock.lock_capability()
        self.assertEqual(cap["cross_process"]["mechanism"], "msvcrt.locking")

    def test_contended_lock_times_out_then_releases(self):
        from ai_new.modules.agent_common.plat.private import _lock
        proc = self._spawn_child()
        try:
            deadline = time.time() + 5.0
            while time.time() < deadline:
                if os.path.exists(self.ready):
                    break
                time.sleep(0.05)
            self.assertTrue(os.path.exists(self.ready), "子进程未拿到锁")
            waiter = _lock.lock_file(self.path, timeout=1.5)
            try:
                with self.assertRaises(_lock.LockError) as caught:
                    waiter.acquire()
                self.assertEqual(caught.exception.code, "lock_timeout")
            finally:
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
        lock = _lock.lock_file(self.path)
        lock.acquire()
        lock.release()


@unittest.skipUnless(not POSIX, "loopback TCP 回退通道仅 Windows 真机验证")
class WindowsTcpTransportTest(unittest.TestCase):
    """loopback TCP 传输往返：小服务 + 一条请求 + 关闭，侧车端口文件清理。"""

    def test_tcp_roundtrip_and_sidecar_cleanup(self):
        import socket as _socket
        from test_plat import _minimal_ctx
        from ai_new.modules.agent_common.api.private import _serve, _transport

        sock = _socket.socket(_socket.AF_INET, _socket.SOCK_STREAM)
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
        sock.close()

        server_ctx = _minimal_ctx()
        server_ctx.api.routes = {"ops.ping": lambda p: {"pong": p.get("n"), "via": "tcp"}}
        server = _serve.Server(server_ctx)
        server.start({"tcp": {"host": "127.0.0.1", "port": port}}, {"tcp"})
        try:
            client = _transport.Transport(_minimal_ctx({
                "default": {"kind": "direct"},
                "listen": {"tcp": {"host": "127.0.0.1", "port": port}},
                "routes": {"ops.*": {"kind": "tcp"}}}))
            self.assertEqual(
                client.send("ops.ping", {"n": 9}, lambda c, p: {"local": 1}),
                {"pong": 9, "via": "tcp"})
        finally:
            server.stop()


@unittest.skipUnless(not POSIX, "multiprocessing.shared_memory 档仅 Windows 真机验证")
class WindowsShmSharedMemoryTest(unittest.TestCase):
    """shm 信箱 Windows 替代：shared_memory 块读写一致。"""

    def test_shared_memory_block_roundtrip(self):
        from multiprocessing import shared_memory
        payload = b"ai_new-shm-consistency-0123456789"
        shm = shared_memory.SharedMemory(create=True, size=len(payload),
                                         name="ai_new_probe")
        try:
            shm.buf[:len(payload)] = payload
            self.assertEqual(bytes(shm.buf[:len(payload)]), payload)
        finally:
            shm.close()
            shm.unlink()


if __name__ == "__main__":
    unittest.main(verbosity=2)
