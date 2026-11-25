"""平台分支在 Linux 上也要被执行：Windows Job/盘符/探针失败路径用受控桩覆盖。"""
from __future__ import annotations

import asyncio
import ctypes
import os
import subprocess
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))

from ai_new.modules.agent.cloud.private import _rsync  # noqa: E402
from ai_new.modules.agent_common.exec.private import _runner  # noqa: E402
from ai_new.modules.agent_common.plat.private import _net, _winjob  # noqa: E402
from ai_new.modules.agent_common.store.private import _files, _isolate  # noqa: E402


class _Proc:
    returncode = 0

    def __init__(self, rc=0, stdout="", stderr=""):
        self.returncode = rc
        self.stdout = stdout
        self.stderr = stderr


class RsyncAdapterBranchesTest(unittest.TestCase):
    def test_posix_without_rsync_is_unsupported(self):
        with mock.patch.object(_rsync, "detect", return_value=None), \
                mock.patch.object(_rsync, "PLATFORM", "posix"):
            self.assertEqual(_rsync.probe()["code"], "unsupported_platform")
            self.assertEqual(_rsync.sync("a", "b")["code"], "unsupported_platform")

    def test_subprocess_success_partial_timeout_error_and_missing(self):
        base = {"detect": "/bin/rsync", "PLATFORM": "posix"}
        with mock.patch.object(_rsync, "detect", return_value="/bin/rsync"), \
                mock.patch.object(_rsync.subprocess, "run", return_value=_Proc(0, "ok")):
            self.assertTrue(_rsync.sync("a", "b")["ok"])
        with mock.patch.object(_rsync, "detect", return_value="/bin/rsync"), \
                mock.patch.object(_rsync.subprocess, "run", return_value=_Proc(0)) as run:
            _rsync.sync("a", "b", delete=True, partial_dir="p", ssh_args="k",
                        extra_args=["-v"])
            argv = run.call_args[0][0]
            for token in ("--delete", "--partial-dir", "p", "-e", "ssh k", "-v"):
                self.assertIn(token, argv)
        with mock.patch.object(_rsync, "detect", return_value="/bin/rsync"), \
                mock.patch.object(_rsync.subprocess, "run", return_value=_Proc(23)):
            out = _rsync.sync("a", "b")
            self.assertEqual(out["code"], "partial_transfer")
            self.assertTrue(out["resumable"])
        with mock.patch.object(_rsync, "detect", return_value="/bin/rsync"), \
                mock.patch.object(_rsync.subprocess, "run", return_value=_Proc(12)):
            self.assertEqual(_rsync.sync("a", "b")["code"], "timeout")
        with mock.patch.object(_rsync, "detect", return_value="/bin/rsync"), \
                mock.patch.object(_rsync.subprocess, "run", return_value=_Proc(1, stderr="bad")):
            out = _rsync.sync("a", "b")
            self.assertEqual(out["code"], "rsync_error")
            self.assertEqual(out["stderr"], "bad")
        with mock.patch.object(_rsync, "detect", return_value="/bin/rsync"), \
                mock.patch.object(_rsync.subprocess, "run", side_effect=FileNotFoundError()):
            self.assertEqual(_rsync.sync("a", "b")["code"], "unsupported_platform")
        with mock.patch.object(_rsync, "detect", return_value="/bin/rsync"), \
                mock.patch.object(_rsync.subprocess, "run",
                                  side_effect=subprocess.TimeoutExpired("rsync", 1)):
            out = _rsync.sync("a", "b", timeout=1)
            self.assertEqual(out["code"], "timeout")
            self.assertTrue(out["resumable"])
        with mock.patch.object(_rsync, "detect", return_value="/bin/rsync"), \
                mock.patch.object(_rsync.subprocess, "run", side_effect=OSError("nope")):
            self.assertEqual(_rsync.sync("a", "b")["code"], "rsync_error")

    def test_shutil_tree_remote_missing_and_single_file(self):
        root = Path(tempfile.mkdtemp(prefix="rsync-branch-"))
        self.addCleanup(lambda: __import__("shutil").rmtree(root, ignore_errors=True))
        src = root / "src"
        src.mkdir()
        (src / "a.txt").write_text("a", encoding="utf-8")
        out = _rsync._sync_tree("user@host:/x", str(root / "dst"))
        self.assertEqual(out["code"], "unsupported_platform")
        out = _rsync._sync_tree(str(root / "missing"), str(root / "dst"))
        self.assertEqual(out["code"], "rsync_error")
        one = root / "one.txt"
        one.write_text("one", encoding="utf-8")
        self.assertTrue(_rsync._sync_tree(str(one), str(root / "d2"))["ok"])
        self.assertTrue((root / "d2" / "one.txt").exists())
        self.assertFalse(_rsync._is_remote("C:\\work\\a"))
        self.assertFalse(_rsync._is_remote("C:/work/a"))
        self.assertTrue(_rsync._is_remote("user@host:/a"))


class NetProbeBranchesTest(unittest.TestCase):
    def test_missing_af_unix_attribute(self):
        fake = types.SimpleNamespace(socket=lambda *a, **k: None)
        with mock.patch.object(_net, "socket", fake):
            self.assertFalse(_net._probe_unix_socket())

    def test_bind_failure_and_cleanup_errors(self):
        with mock.patch.object(_net.tempfile, "mkdtemp", return_value="/tmp/x"), \
                mock.patch.object(_net.os.path, "join", return_value="/tmp/" + "x" * 300), \
                mock.patch.object(_net.os, "unlink", side_effect=OSError), \
                mock.patch.object(_net.os, "rmdir", side_effect=OSError):
            self.assertFalse(_net._probe_unix_socket())


class _Job:
    def __init__(self, assign=True, fail=None):
        self.assign_result = assign
        self.fail = fail
        self.closed = False
        self.assigned = None

    def __enter__(self):
        if self.fail:
            raise self.fail
        return self

    def __exit__(self, *_exc):
        self.close()
        return False

    def assign(self, pid):
        self.assigned = pid
        return self.assign_result

    def close(self):
        self.closed = True


class JobObjectBranchesTest(unittest.TestCase):
    def setUp(self):
        _winjob._STATE = None
        self._old_state = None

    def tearDown(self):
        _winjob._STATE = None

    def _fake_k32(self, create=1, config=1, open_proc=2, assign=1):
        class K:
            CreateJobObjectW = staticmethod(lambda *a: create)
            SetInformationJobObject = staticmethod(lambda *a: config)
            AssignProcessToJobObject = staticmethod(lambda *a: assign)
            OpenProcess = staticmethod(lambda *a: open_proc)
            CloseHandle = staticmethod(lambda *a: 1)
        return K()

    def test_posix_job_is_noop(self):
        with mock.patch.object(_winjob, "PLATFORM", "posix"):
            self.assertEqual(_winjob.probe()["code"], "unsupported_platform")
            self.assertEqual(_winjob.probe()["code"], "unsupported_platform")
            with self.assertRaises(_winjob.JobError):
                _winjob._kernel32()
            job = _winjob.Job()
            self.assertFalse(job.supported)
            self.assertFalse(job.assign(1))
            job.close()

    def test_windows_job_lifecycle_and_failures(self):
        with mock.patch.object(_winjob, "PLATFORM", "nt"), \
                mock.patch.object(ctypes, "WinDLL", create=True, return_value=self._fake_k32()):
            job = _winjob.Job(memory_mb=32, active_processes=2)
            self.assertTrue(job.supported)
            self.assertTrue(job.assign(123))
            job.close()
            self.assertFalse(job.supported)
            with _winjob.Job() as ctx_job:
                self.assertIs(ctx_job.__enter__(), ctx_job)
                self.assertFalse(ctx_job.__exit__(None, None, None))
        with mock.patch.object(_winjob, "PLATFORM", "nt"), \
                mock.patch.object(ctypes, "WinDLL", create=True, return_value=self._fake_k32(create=0)):
            with self.assertRaises(_winjob.JobError) as caught:
                _winjob.Job()
            self.assertEqual(caught.exception.code, "job_create_failed")
        with mock.patch.object(_winjob, "PLATFORM", "nt"), \
                mock.patch.object(ctypes, "WinDLL", create=True, return_value=self._fake_k32(config=0)):
            with self.assertRaises(_winjob.JobError) as caught:
                _winjob.Job()
            self.assertEqual(caught.exception.code, "job_config_failed")
        with mock.patch.object(_winjob, "PLATFORM", "nt"), \
                mock.patch.object(ctypes, "WinDLL", create=True, return_value=self._fake_k32()):
            job = _winjob.Job()
            self._fake_open = self._fake_k32(open_proc=0)
            job._k32 = self._fake_open
            self.assertFalse(job.assign(1))
            job._k32 = self._fake_k32(assign=0)
            self.assertFalse(job.assign(1))

    def test_probe_windows_true_false_and_exception(self):
        proc = types.SimpleNamespace(pid=99, wait=lambda timeout: 0)
        with mock.patch.object(_winjob, "PLATFORM", "nt"), \
                mock.patch.object(_winjob.subprocess, "Popen", return_value=proc), \
                mock.patch.object(_winjob, "Job", return_value=_Job(assign=True)):
            out = _winjob.probe()
            self.assertTrue(out["verified"])
            self.assertEqual(out["code"], "")
        _winjob._STATE = None
        with mock.patch.object(_winjob, "PLATFORM", "nt"), \
                mock.patch.object(_winjob.subprocess, "Popen", return_value=proc), \
                mock.patch.object(_winjob, "Job", return_value=_Job(assign=False)):
            out = _winjob.probe()
            self.assertEqual(out["code"], "assign_failed")
        _winjob._STATE = None
        with mock.patch.object(_winjob, "PLATFORM", "nt"), \
                mock.patch.object(_winjob, "Job", side_effect=_winjob.JobError("x", "boom")):
            out = _winjob.probe()
            self.assertEqual(out["code"], "probe_failed")
            self.assertFalse(_winjob.ready())
        _winjob._STATE = {"supported": True, "verified": True}
        self.assertTrue(_winjob.ready())


class RunnerJobBranchesTest(unittest.TestCase):
    def _run(self, payload):
        return asyncio.run(_runner._arun(types.SimpleNamespace(runtime=None), payload))

    def _payload(self, **limits):
        return {"argv": [sys.executable, "-c", "pass"],
                "sandbox": {"engine": "winjob", "limits": limits}, "timeout": 5}

    def test_ready_false_and_job_error(self):
        with mock.patch.object(_runner._winjob, "ready", return_value=False):
            self.assertEqual(self._run(self._payload())["code"], "sandbox_unavailable")
        with mock.patch.object(_runner._winjob, "ready", return_value=True), \
                mock.patch.object(_runner._winjob, "Job",
                                  side_effect=_runner._winjob.JobError("x", "boom")):
            self.assertEqual(self._run(self._payload())["code"], "sandbox_unavailable")

    def test_spawn_oserror_closes_job(self):
        job = _Job()
        with mock.patch.object(_runner._winjob, "ready", return_value=True), \
                mock.patch.object(_runner._winjob, "Job", return_value=job), \
                mock.patch.object(_runner.asyncio, "create_subprocess_exec",
                                  side_effect=OSError("no")):
            self.assertEqual(self._run(self._payload())["code"], "spawn_failed")
            self.assertTrue(job.closed)

    def test_assign_false_kills_proc(self):
        job = _Job(assign=False)
        proc = types.SimpleNamespace(pid=7, kill=mock.Mock(),
                                     wait=mock.AsyncMock(return_value=0))
        with mock.patch.object(_runner._winjob, "ready", return_value=True), \
                mock.patch.object(_runner._winjob, "Job", return_value=job), \
                mock.patch.object(_runner.asyncio, "create_subprocess_exec",
                                  return_value=proc):
            out = self._run(self._payload())
            self.assertEqual(out["code"], "sandbox_assign_failed")
            proc.kill.assert_called_once()
            self.assertTrue(job.closed)

    def test_success_path_assigns_and_runs(self):
        job = _Job(assign=True)
        with mock.patch.object(_runner._winjob, "ready", return_value=True), \
                mock.patch.object(_runner._winjob, "Job", return_value=job):
            out = self._run(self._payload())
            self.assertTrue(out["ok"], out)
            self.assertIsInstance(job.assigned, int)


class IsolateWindowsBranchesTest(unittest.TestCase):
    def test_cap_nt_and_sandbox_info(self):
        with mock.patch.object(_isolate._winjob, "probe",
                               return_value={"supported": True, "verified": True}):
            self.assertEqual(_isolate._cap_nt()["os"], "nt")
        root = Path("/tmp/root")
        with mock.patch.object(_isolate.os, "name", "nt"), \
                mock.patch.object(_isolate._winjob, "ready", return_value=True):
            out = _isolate._sandbox_info(root, [], "t1", root)
            self.assertEqual(out["engine"], "winjob")
            self.assertEqual(out["limits"]["active_processes"], 64)
        with mock.patch.object(_isolate.os, "name", "nt"), \
                mock.patch.object(_isolate._winjob, "ready", return_value=False):
            self.assertEqual(_isolate._sandbox_info(root, [], "t1", root)["engine"], "path")


if __name__ == "__main__":
    unittest.main()


class StoreFileRetryTest(unittest.TestCase):
    """Windows 原子改名/读取遇到短暂占用必须退避重试，不能把并发放大成失败。"""

    def test_replace_retries_permission_error_on_windows(self):
        calls = []

        def flaky(src, dst):
            calls.append(dst)
            if len(calls) < 3:
                raise PermissionError(dst)

        with mock.patch.object(_files.os, "replace", side_effect=flaky), \
                mock.patch.object(_files.os, "name", "nt"):
            _files.replace_file("a.tmp", "target")
        self.assertEqual(len(calls), 3)

    def test_replace_does_not_retry_on_posix(self):
        with mock.patch.object(_files.os, "replace",
                               side_effect=PermissionError("denied")), \
                mock.patch.object(_files.os, "name", "posix"):
            with self.assertRaises(PermissionError):
                _files.replace_file("a.tmp", "target")

    def test_read_retries_permission_error_on_windows(self):
        with mock.patch.object(_files.Path, "read_text",
                               side_effect=[PermissionError("busy"), "body"]), \
                mock.patch.object(_files.os, "name", "nt"):
            self.assertEqual(_files.read_text("x"), "body")

    def test_read_raises_on_posix_without_retry(self):
        with mock.patch.object(_files.Path, "read_text",
                               side_effect=PermissionError("busy")), \
                mock.patch.object(_files.os, "name", "posix"):
            with self.assertRaises(PermissionError):
                _files.read_text("x")
