"""进程执行边角：bwrap 虚拟路径拒绝、ensure_cwd、Job 收口、stdin 断管与泵异常。"""
import asyncio
import os
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))

from ai_new.modules.agent_common.exec import _route_run, setup
from ai_new.modules.agent_common.exec.private import _runner as r


class Reader:
    def __init__(self, lines=None, exc=None):
        self.lines = list(lines or [])
        self.exc = exc

    async def readline(self):
        if self.lines:
            return self.lines.pop(0)
        if self.exc:
            raise self.exc
        return b""


class Writer:
    def __init__(self, fail=False):
        self.fail = fail

    def write(self, data):
        if self.fail:
            raise BrokenPipeError("x")

    async def drain(self):
        if self.fail:
            raise BrokenPipeError("x")

    def close(self):
        pass


class Proc:
    def __init__(self, code=0, out=None, err=None, hang=False, stdin_fail=False, read_exc=None):
        self.returncode = None if hang else code
        self._code = code
        self.stdout = Reader(out or [], read_exc)
        self.stderr = Reader(err or [])
        self.stdin = Writer(stdin_fail)
        self.pid = 1
        self.killed = False

    async def wait(self):
        if self.returncode is None:
            self.returncode = self._code
        return self.returncode

    def kill(self):
        self.killed = True
        self.returncode = -9


class Runtime:
    def __init__(self, cancel=False, boom=False):
        self.parts = []
        self._cancel = cancel
        self._boom = boom

    def stream_put(self, key, piece):
        if self._boom:
            raise RuntimeError("stream gone")
        self.parts.append((key, piece))

    def cancelled(self, key, since):
        return self._cancel


class Api:
    def call(self, name, payload=None, caller=None):
        return {"value": 10}


class Ctx:
    def __init__(self, runtime=None):
        self.runtime = runtime if runtime is not None else Runtime()
        self.api = Api()


class BwrapEdgeTest(unittest.TestCase):
    def setUp(self):
        self._which = mock.patch.object(r.shutil, "which", return_value="/bwrap")
        self._which.start()

    def tearDown(self):
        self._which.stop()

    def test_virtual_cwd_and_bind_dst_rejected(self):
        base = {"engine": "bwrap", "root": "/tmp/r", "mount": "/w", "cwd": "/w"}
        self.assertIn("cwd", r._bwrap_command({"sandbox": dict(base, cwd="rel")}, "")[1])
        with mock.patch.object(Path, "mkdir"):
            bad = {"engine": "bwrap", "root": "/tmp/r", "mount": "/w", "cwd": "/w",
                   "binds": [{"src": "/tmp/r", "dst": "rel"}]}
            self.assertIn("bind 目的地", r._bwrap_command({"sandbox": bad}, "")[1])

    def test_bwrap_builds_parent_dirs_and_binds(self):
        with tempfile.TemporaryDirectory() as d:
            root = os.path.join(d, "root")
            sandbox = {"engine": "bwrap", "root": root, "mount": "/w", "cwd": "/w/deep/x",
                       "binds": [{"src": root, "dst": "/w/a/b"}]}
            args, err = r._bwrap_command({"sandbox": sandbox}, "")
            self.assertIsNone(err)
            self.assertEqual(args[:2], ["/bwrap", "--unshare-all"])
            self.assertIn("--chdir", args)
            self.assertEqual(args[args.index("--chdir") + 1], "/w/deep/x")
            self.assertIn("/w/a", args)


class BwrapOptionalBitsTest(unittest.TestCase):
    def test_missing_system_dirs_and_blank_env(self):
        with tempfile.TemporaryDirectory() as d, \
                mock.patch.object(r.shutil, "which", return_value="/bwrap"), \
                mock.patch.object(Path, "exists", return_value=False), \
                mock.patch.dict(os.environ, {"LANG": "", "LC_ALL": "", "TZ": ""}):
            root = os.path.join(d, "root")
            args, err = r._bwrap_command({"sandbox": {"engine": "bwrap", "root": root,
                                                     "mount": "/w", "cwd": "/w"}}, "")
        self.assertIsNone(err)
        self.assertNotIn("--ro-bind", args)
        self.assertEqual([a for a in args if a.startswith("LANG=")], [])


class ArunEdgeTest(unittest.TestCase):
    def test_ensure_cwd_failure(self):
        ctx = Ctx()
        with mock.patch.object(Path, "mkdir", side_effect=OSError("x")):
            got = asyncio.run(r._arun(ctx, {"argv": ["/bin/echo"], "cwd": "/tmp/x",
                                            "ensure_cwd": True}))
        self.assertEqual(got["code"], "cwd_unavailable")

    def test_ensure_cwd_ok(self):
        ctx = Ctx()
        with tempfile.TemporaryDirectory() as d:
            target = os.path.join(d, "sub")
            got = asyncio.run(r._arun(ctx, {"argv": ["/bin/pwd"], "cwd": target,
                                            "ensure_cwd": True}))
            self.assertTrue(os.path.isdir(target))
        self.assertTrue(got["ok"])

    def test_job_closed_on_spawn_failure(self):
        job = mock.Mock()
        with mock.patch.object(r._winjob, "ready", return_value=True), \
                mock.patch.object(r._winjob, "Job", return_value=job), \
                mock.patch.object(r.asyncio, "create_subprocess_exec",
                                  mock.AsyncMock(side_effect=OSError("x"))):
            got = asyncio.run(r._arun(Ctx(), {"argv": ["/bin/echo"],
                                             "sandbox": {"engine": "winjob"}}))
        self.assertEqual(got["code"], "spawn_failed")
        job.close.assert_called_once()

    def test_job_closed_on_success(self):
        job = mock.Mock()
        job.assign.return_value = True
        with mock.patch.object(r._winjob, "ready", return_value=True), \
                mock.patch.object(r._winjob, "Job", return_value=job), \
                mock.patch.object(r.asyncio, "create_subprocess_exec",
                                  mock.AsyncMock(return_value=Proc())):
            got = asyncio.run(r._arun(Ctx(), {"argv": ["/bin/echo"],
                                             "sandbox": {"engine": "winjob",
                                                         "limits": {"memory_mb": 512}}}))
        self.assertTrue(got["ok"])
        job.close.assert_called_once()

    def test_stdin_broken_pipe_swallowed(self):
        with mock.patch.object(r.asyncio, "create_subprocess_exec",
                               mock.AsyncMock(return_value=Proc(stdin_fail=True))):
            got = asyncio.run(r._arun(Ctx(), {"argv": ["/bin/echo"], "stdin": "abc"}))
        self.assertTrue(got["ok"])

    def test_stream_put_failure_does_not_break_run(self):
        ctx = Ctx(Runtime(boom=True))
        with mock.patch.object(r.asyncio, "create_subprocess_exec",
                               mock.AsyncMock(return_value=Proc(out=[b"a\n", b"b\n"]))):
            got = asyncio.run(r._arun(ctx, {"argv": ["/bin/echo"], "stream_key": "k"}))
        self.assertTrue(got["ok"])
        self.assertEqual(got["out"], "a\nb\n")

    def test_wait_timeout_then_timeout_kill(self):
        hang = Proc(hang=True)
        hang.wait = mock.AsyncMock(side_effect=asyncio.TimeoutError)
        with mock.patch.object(r.asyncio, "create_subprocess_exec",
                               mock.AsyncMock(return_value=hang)), \
                mock.patch.object(r.time, "time", side_effect=[0, 0, 10, 10]):
            got = asyncio.run(r._arun(Ctx(), {"argv": ["/bin/echo"], "timeout": 1}))
        self.assertEqual(got["killed"], "timeout")

    def test_pump_read_error_swallowed(self):
        with mock.patch.object(r.asyncio, "create_subprocess_exec",
                               mock.AsyncMock(return_value=Proc(out=[b"a\n"],
                                                                read_exc=OSError("read")))):
            got = asyncio.run(r._arun(Ctx(), {"argv": ["/bin/echo"]}))
        self.assertEqual(got["out"], "a\n")
        self.assertTrue(got["ok"])

    def test_error_cap_truncates(self):
        ctx = Ctx()
        with mock.patch.object(r.asyncio, "create_subprocess_exec",
                               mock.AsyncMock(return_value=Proc(code=3))):
            got = asyncio.run(r._arun(ctx, {"argv": ["/bin/echo"]}))
        self.assertEqual(got["error"], "进程退出码 3")
        self.assertFalse(got["ok"])

    def test_cancel_flag_present_but_not_cancelled(self):
        hang = Proc(hang=True)
        with mock.patch.object(r.asyncio, "create_subprocess_exec",
                               mock.AsyncMock(return_value=hang)), \
                mock.patch.object(r.time, "time", return_value=0):
            got = asyncio.run(r._arun(Ctx(Runtime(cancel=False)),
                                      {"argv": ["/bin/echo"], "cancel": {"key": "k"}}))
        self.assertTrue(got["ok"])
        self.assertNotIn("killed", got)

    def test_cancel_with_id_and_start_stamp(self):
        hang = Proc(hang=True)
        hang.wait = mock.AsyncMock(side_effect=asyncio.TimeoutError)
        ctx = Ctx(Runtime(cancel=True))
        with mock.patch.object(r.asyncio, "create_subprocess_exec",
                               mock.AsyncMock(return_value=hang)), \
                mock.patch.object(r.time, "time", return_value=0):
            got = asyncio.run(r._arun(ctx, {"argv": ["/bin/echo"],
                                            "cancel": {"id": "g", "since": "t"}}))
        self.assertEqual(got["killed"], "cancelled")


class RouteTest(unittest.TestCase):
    def test_setup_and_route_run(self):
        captured = {}

        class RegApi(Api):
            def register(self, name, fn, desc=None, module=None, internal=False):
                captured["name"] = name
                captured["fn"] = fn

        ctx = Ctx()
        ctx.api = RegApi()
        self.assertTrue(setup(ctx))
        self.assertEqual(captured["name"], "exec.run")
        got = asyncio.run(_route_run(ctx, {"argv": ["/bin/echo", "ok"]}))
        self.assertTrue(got["ok"])

    def test_sync_shell_bridges_to_loop(self):
        loop = asyncio.new_event_loop()
        thread = threading.Thread(target=loop.run_forever, daemon=True)
        thread.start()
        try:
            ctx = Ctx()
            ctx.api = type("A", (), {"call": lambda self, n, p=None, caller=None: {"value": 10},
                                     "_ensure_loop": lambda self: loop})()
            got = r.run(ctx, {"argv": ["/bin/echo", "sync"]})
        finally:
            loop.call_soon_threadsafe(loop.stop)
            thread.join(timeout=5)
            loop.close()
        self.assertTrue(got["ok"])
        self.assertEqual(got["out"], "sync\n")


if __name__ == "__main__":
    unittest.main()
