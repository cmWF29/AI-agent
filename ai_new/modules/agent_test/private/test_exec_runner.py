"""进程执行：虚拟路径、bwrap 组装、argv/命令探测、超时/打断、Job Object 与错误收口。"""
from __future__ import annotations

import asyncio
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))

from ai_new.modules.agent_common.exec.private import _runner as r  # noqa: E402


class Reader:
    def __init__(self, lines):
        self.lines = list(lines)

    async def readline(self):
        return self.lines.pop(0) if self.lines else b""


class Writer:
    def __init__(self, fail=False):
        self.fail = fail
        self.data = b""
        self.closed = False

    def write(self, data):
        if self.fail:
            raise BrokenPipeError("x")
        self.data += data

    async def drain(self):
        if self.fail:
            raise BrokenPipeError("x")

    def close(self):
        self.closed = True


class Proc:
    def __init__(self, code=0, out=None, err=None, hang=False):
        self.returncode = None if hang else code
        self._code = code
        self.stdout = Reader(out or [])
        self.stderr = Reader(err or [])
        self.stdin = Writer()
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
    def __init__(self, cancelled=False):
        self.parts = []
        self._cancelled = cancelled

    def stream_put(self, key, piece):
        self.parts.append((key, piece))

    def cancelled(self, key, since):
        return self._cancelled


class Api:
    def __init__(self, chars=10):
        self.chars = chars

    def call(self, name, payload=None, caller=None):
        return {"value": self.chars}


class Ctx:
    def __init__(self):
        self.runtime = Runtime()
        self.api = Api()


class ExecTest(unittest.TestCase):
    def test_virtual_path(self):
        self.assertEqual(r._virtual_path("/a/../b", "x")[1], "x 含越界片段")
        self.assertEqual(r._virtual_path("/a\x00", "x")[1], "x 含空字节")
        self.assertEqual(r._virtual_path("a", "x")[1], "x 必须是绝对路径")
        self.assertEqual(r._virtual_path("/", "x")[1], "x 归一后不是有效路径")
        self.assertEqual(r._virtual_path("/a/./b", "x")[0], "/a/b")

    @mock.patch.object(r.shutil, "which", return_value="/bwrap")
    def test_bwrap_command(self, _which):
        self.assertEqual(r._bwrap_command({}, ""), ([], None))
        with mock.patch.object(r.shutil, "which", return_value=None):
            self.assertEqual(r._bwrap_command({"sandbox": {"engine": "bwrap"}}, "")[1],
                             "bwrap 不在 PATH，强档隔离不可用")
        base = {"engine": "bwrap", "root": "/tmp/r", "mount": "/w", "cwd": "/w"}
        with mock.patch.object(r.shutil, "which", return_value="/bwrap"):
            with mock.patch.object(r.Path, "mkdir"):
                self.assertIn("root/mount/cwd", r._bwrap_command({"sandbox": dict(base, root="")}, "")[1])
        self.assertIn("非根", r._bwrap_command({"sandbox": dict(base, root="/")}, "")[1])
        self.assertIn("mount", r._bwrap_command({"sandbox": dict(base, mount="rel")}, "")[1])
        self.assertIn("cwd", r._bwrap_command({"sandbox": dict(base, cwd="/x")}, "")[1])
        with tempfile.TemporaryDirectory() as d:
            root = os.path.join(d, "root")
            good = dict(base, root=root)
            with mock.patch.object(r.shutil, "which", return_value="/bwrap"):
                with mock.patch.object(r.Path, "mkdir", side_effect=OSError("x")):
                    self.assertIn("不可创建", r._bwrap_command({"sandbox": good}, "")[1])
                bad = dict(good, binds=[{}])
                self.assertIn("不完整", r._bwrap_command({"sandbox": bad}, "")[1])
                bad = dict(good, binds=[{"src": root, "dst": "/other"}])
                self.assertIn("越出", r._bwrap_command({"sandbox": bad}, "")[1])
                bad = dict(good, binds=[{"src": "/etc", "dst": "/w/etc"}])
                self.assertIn("bind 源越出", r._bwrap_command({"sandbox": bad}, "")[1])
                with mock.patch.object(r.Path, "resolve",
                                       side_effect=[Path(root), OSError("x")]):
                    self.assertIn("源不可用", r._bwrap_command({"sandbox": good}, "")[1])
                bad = dict(good, binds=[{"src": root, "dst": "/w/a/b"}])
                with mock.patch.object(r.Path, "mkdir", side_effect=[None, OSError("x")]):
                    self.assertIn("源不可用", r._bwrap_command({"sandbox": bad}, "")[1])
            args, err = r._bwrap_command({"sandbox": bad}, "")
            self.assertIsNone(err)
            self.assertIn("/w/a", args)
            self.assertIn("TMPDIR=/tmp", args)

    def test_arun_validation(self):
        self.assertEqual(asyncio.run(r._arun(Ctx(), {"argv": []}))["code"], "no_argv")
        with mock.patch.object(r.shutil, "which", return_value=None):
            self.assertEqual(asyncio.run(r._arun(Ctx(), {"argv": ["x"]}))["code"],
                             "command_not_found")
        self.assertEqual(asyncio.run(r._arun(Ctx(), {"argv": ["x"],
            "sandbox": {"engine": "bwrap"}}))["code"], "sandbox_unavailable")

    def test_arun_real_and_stdin(self):
        ctx = Ctx()
        out = asyncio.run(r._arun(ctx, {"argv": [sys.executable, "-c",
                                                 "print('hi')"]}))
        self.assertTrue(out["ok"])
        self.assertEqual(out["out"], "hi\n")
        out = asyncio.run(r._arun(ctx, {"argv": [sys.executable, "-c",
                                                 "import sys; sys.stdout.write(sys.stdin.read())"],
                                        "stdin": "abc"}))
        self.assertEqual(out["out"], "abc")

    def test_arun_timeout_and_cancel(self):
        ctx = Ctx()
        hang = Proc(hang=True)
        hang.wait = mock.AsyncMock(side_effect=asyncio.TimeoutError)
        with mock.patch.object(r.asyncio, "create_subprocess_exec", mock.AsyncMock(return_value=hang)), \
                mock.patch.object(r.time, "time", side_effect=[0, 10, 10]):
            out = asyncio.run(r._arun(ctx, {"argv": ["/bin/echo"], "timeout": 1}))
        self.assertEqual(out["killed"], "timeout")
        ctx.runtime = Runtime(cancelled=True)
        hang2 = Proc(hang=True)
        hang2.wait = mock.AsyncMock(side_effect=asyncio.TimeoutError)
        with mock.patch.object(r.asyncio, "create_subprocess_exec", mock.AsyncMock(return_value=hang2)), \
                mock.patch.object(r.time, "time", side_effect=[0, 0, 0]):
            out = asyncio.run(r._arun(ctx, {"argv": ["/bin/echo"], "cancel": {"key": "k"}}))
        self.assertEqual(out["killed"], "cancelled")

    def test_arun_spawn_and_winjob(self):
        ctx = Ctx()
        with mock.patch.object(r.asyncio, "create_subprocess_exec", mock.AsyncMock(side_effect=OSError("x"))):
            self.assertEqual(asyncio.run(r._arun(ctx, {"argv": ["/bin/echo"]}))["code"], "spawn_failed")
        with mock.patch.object(r._winjob, "ready", return_value=False):
            self.assertEqual(asyncio.run(r._arun(ctx, {"argv": ["/bin/echo"],
                "sandbox": {"engine": "winjob"}}))["code"], "sandbox_unavailable")
        with mock.patch.object(r._winjob, "ready", return_value=True), \
                mock.patch.object(r._winjob, "Job", side_effect=r._winjob.JobError("job", "x")):
            self.assertEqual(asyncio.run(r._arun(ctx, {"argv": ["/bin/echo"],
                "sandbox": {"engine": "winjob"}}))["code"], "sandbox_unavailable")
        job = mock.Mock()
        job.assign.return_value = False
        with mock.patch.object(r._winjob, "ready", return_value=True), \
                mock.patch.object(r._winjob, "Job", return_value=job), \
                mock.patch.object(r.asyncio, "create_subprocess_exec",
                                  mock.AsyncMock(return_value=Proc())):
            out = asyncio.run(r._arun(ctx, {"argv": ["/bin/echo"],
                "sandbox": {"engine": "winjob"}}))
        self.assertEqual(out["code"], "sandbox_assign_failed")

    def test_arun_error_cap_and_stream(self):
        ctx = Ctx()
        with mock.patch.object(r.asyncio, "create_subprocess_exec",
                               mock.AsyncMock(return_value=Proc(code=2, err=[b"boom\n"]))):
            out = asyncio.run(r._arun(ctx, {"argv": ["/bin/echo"]}))
        self.assertEqual(out["error"], "boom")
        self.assertFalse(out["ok"])
        with mock.patch.object(r.asyncio, "create_subprocess_exec",
                               mock.AsyncMock(return_value=Proc(out=[b"a\n"])), ):
            out = asyncio.run(r._arun(ctx, {"argv": ["/bin/echo"], "stream_key": "k"}))
        self.assertEqual(ctx.runtime.parts, [("k", "a\n")])


if __name__ == "__main__":
    unittest.main()
