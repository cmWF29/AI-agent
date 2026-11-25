"""Windows Job Object 进程约束：与 POSIX 强档在 exec 接口层归一。

Linux 用 bwrap mount namespace；Windows 没有等价 namespace，用 Job Object 把
进程树、活动进程数、内存上限与 kill-on-close 收口。接口只暴露
``engine`` / ``assign`` / ``close``，调用方不按 OS 名分支。

本模块只在 Windows 上真正加载 kernel32；Linux import 安全，函数返回
``unsupported_platform``，不冒充支持。
"""
from __future__ import annotations

import os
import subprocess
import sys

PLATFORM = "nt" if os.name == "nt" else "posix"
_STATE = None

# Win32 常量
_JOB_OBJECT_LIMIT_ACTIVE_PROCESS = 0x00000008
_JOB_OBJECT_LIMIT_JOB_MEMORY = 0x00000200
_JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
_JOB_OBJECT_EXTENDED_LIMIT_INFORMATION = 9
_PROCESS_SET_QUOTA = 0x0100
_PROCESS_TERMINATE = 0x0001


class JobError(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code
        self.message = message


def _kernel32():
    if PLATFORM != "nt":
        raise JobError("unsupported_platform", "Job Object 仅 Windows 可用")
    import ctypes
    from ctypes import wintypes
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)

    class _Basic(ctypes.Structure):
        _fields_ = [
            ("PerProcessUserTimeLimit", wintypes.LARGE_INTEGER),
            ("PerJobUserTimeLimit", wintypes.LARGE_INTEGER),
            ("LimitFlags", wintypes.DWORD),
            ("MinimumWorkingSetSize", ctypes.c_size_t),
            ("MaximumWorkingSetSize", ctypes.c_size_t),
            ("ActiveProcessLimit", wintypes.DWORD),
            ("Affinity", ctypes.c_size_t),
            ("PriorityClass", wintypes.DWORD),
            ("SchedulingClass", wintypes.DWORD),
        ]

    class _Io(ctypes.Structure):
        _fields_ = [("ReadOperationCount", ctypes.c_ulonglong),
                    ("WriteOperationCount", ctypes.c_ulonglong),
                    ("OtherOperationCount", ctypes.c_ulonglong),
                    ("ReadTransferCount", ctypes.c_ulonglong),
                    ("WriteTransferCount", ctypes.c_ulonglong),
                    ("OtherTransferCount", ctypes.c_ulonglong)]

    class _Ext(ctypes.Structure):
        _fields_ = [("BasicLimitInformation", _Basic),
                    ("IoInfo", _Io),
                    ("ProcessMemoryLimit", ctypes.c_size_t),
                    ("JobMemoryLimit", ctypes.c_size_t),
                    ("PeakProcessMemoryUsed", ctypes.c_size_t),
                    ("PeakJobMemoryUsed", ctypes.c_size_t)]

    k32.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
    k32.CreateJobObjectW.restype = wintypes.HANDLE
    k32.SetInformationJobObject.argtypes = [
        wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
    k32.SetInformationJobObject.restype = wintypes.BOOL
    k32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    k32.AssignProcessToJobObject.restype = wintypes.BOOL
    k32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    k32.OpenProcess.restype = wintypes.HANDLE
    k32.CloseHandle.argtypes = [wintypes.HANDLE]
    k32.CloseHandle.restype = wintypes.BOOL
    return k32, _Ext


class Job:
    """一个 Job Object 生命周期；close 时 kill-on-close 收掉整棵进程树。"""

    def __init__(self, memory_mb=None, active_processes=None):
        self._handle = None
        if PLATFORM != "nt":
            return
        k32, ext_cls = _kernel32()
        self._k32 = k32
        handle = k32.CreateJobObjectW(None, None)
        if not handle:
            raise JobError("job_create_failed", "CreateJobObject 失败")
        info = ext_cls()
        flags = _JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if active_processes:
            flags |= _JOB_OBJECT_LIMIT_ACTIVE_PROCESS
            info.BasicLimitInformation.ActiveProcessLimit = int(active_processes)
        if memory_mb:
            flags |= _JOB_OBJECT_LIMIT_JOB_MEMORY
            info.JobMemoryLimit = int(memory_mb) * 1024 * 1024
        info.BasicLimitInformation.LimitFlags = flags
        ok = k32.SetInformationJobObject(
            handle, _JOB_OBJECT_EXTENDED_LIMIT_INFORMATION,
            __import__("ctypes").byref(info), __import__("ctypes").sizeof(info))
        if not ok:
            k32.CloseHandle(handle)
            raise JobError("job_config_failed", "SetInformationJobObject 失败")
        self._handle = handle

    @property
    def supported(self):
        return self._handle is not None

    def assign(self, pid):
        if self._handle is None:
            return False
        k32 = self._k32
        import ctypes
        from ctypes import wintypes
        proc = k32.OpenProcess(_PROCESS_SET_QUOTA | _PROCESS_TERMINATE, False, int(pid))
        if not proc:
            return False
        try:
            return bool(k32.AssignProcessToJobObject(self._handle,
                                                     wintypes.HANDLE(proc)))
        finally:
            k32.CloseHandle(proc)

    def close(self):
        if self._handle is not None:
            try:
                self._k32.CloseHandle(self._handle)
            finally:
                self._handle = None

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        self.close()
        return False


def probe():
    """真起一次短进程并 assign；成功才算支持。结果进程内缓存。"""
    global _STATE
    if _STATE is not None:
        return dict(_STATE)
    if PLATFORM != "nt":
        _STATE = {"supported": False, "verified": False,
                  "code": "unsupported_platform", "engine": "job-object"}
        return dict(_STATE)
    try:
        with Job(active_processes=4) as job:
            proc = subprocess.Popen([sys.executable, "-c", "pass"],
                                    stdout=subprocess.DEVNULL,
                                    stderr=subprocess.DEVNULL)
            assigned = job.assign(proc.pid)
            proc.wait(timeout=10)
        _STATE = {"supported": True, "verified": bool(assigned),
                  "code": "" if assigned else "assign_failed",
                  "engine": "job-object"}
    except (OSError, JobError, subprocess.SubprocessError) as exc:
        _STATE = {"supported": True, "verified": False,
                  "code": "probe_failed", "engine": "job-object",
                  "error": str(exc)}
    return dict(_STATE)


def ready():
    """强档是否已验证可用；调用方只看这一处，不按 OS 名分支。"""
    return bool(probe().get("verified"))
