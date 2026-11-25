"""rsync 通道：二进制探测 + 命令封装；Windows 无 rsync 时走同接口的本地树同步。

边界与约束：

- 启动（首次调用）经 ``shutil.which("rsync")`` 探测；探测不到时所有调用返回
  ``{"ok": False, "code": "unsupported_platform", "detail": "rsync not installed"}``；
- 封装参数：``-a --checksum --partial``，``--partial-dir`` 由调用方指定；
  ``--delete`` 按显式开关开启；ssh 选项经 ``-e ssh ...`` 透传；
- 退出码映射：0 成功；23/24 部分传输（可续跑，``resumable=True``）；
  12/30/35 超时；其余归 ``rsync_error`` 并带回退出码与 stderr；
- 纯标准库（subprocess / shutil），不引第三方包；Python 3.8 兼容。

适配面签名（供 ``_providers.py`` 按名接线）::

    probe() -> {"ok": bool, "code": "available"|"unsupported_platform",
                "path": str|None, "detail": str}
    is_available() -> bool
    sync(source: str, target: str, *, delete=False, checksum=True,
         partial_dir=None, ssh_args=None, extra_args=None, timeout=300) ->
      {"ok": True, "exit": 0, "sent": str, "received": str, "stdout": str}
      | {"ok": False, "code": "unsupported_platform"|"partial_transfer"|"timeout"
         |"rsync_error", "exit": int, "resumable": bool, "stderr": str}

``source`` / ``target`` 由调用方按 rsync 语义拼好：本地目录末尾带 ``/`` 表示同步内容；
远端形式 ``user@host:/path`` 原样透传。
"""
from __future__ import annotations

import os
import shutil
import subprocess

PLATFORM = "nt" if os.name == "nt" else "posix"

_UNSUPPORTED = {
    "ok": False,
    "code": "unsupported_platform",
    "detail": "rsync not installed",
}

# 部分传输：远端/本地部分文件未传完，重跑即可续传。
_PARTIAL_EXITS = (23, 24)
# 超时类退出码：12 传输超时 / 30 守护进程超时 / 35 ssh 超时。
_TIMEOUT_EXITS = (12, 30, 35)


def detect():
    """返回 rsync 二进制路径；未安装返回 None。结果按进程缓存。"""
    path = getattr(detect, "_cached", None)
    if path is None:
        path = shutil.which("rsync") or ""
        detect._cached = path  # type: ignore[attr-defined]
    return path or None


def probe():
    """探测结果结构化：可用 / 不可用都显式给出 code 与 detail。

    Windows 没有 rsync 时，本地目录同步由 Python ``shutil`` 实现；接口仍报
    ``available``，但 ``mechanism`` 明示不是 rsync，远端 ``user@host:`` 形式拒绝。
    """
    path = detect()
    if path:
        return {"ok": True, "code": "available", "path": path,
                "mechanism": "rsync",
                "detail": "rsync resolved at %s" % path}
    if PLATFORM == "nt":
        return {"ok": True, "code": "available", "path": None,
                "mechanism": "python-shutil",
                "detail": "windows local tree sync via python shutil"}
    return dict(_UNSUPPORTED)


def is_available():
    """同步接口是否可用：POSIX 看 rsync；Windows 有本地 shutil 兜底。"""
    return detect() is not None or PLATFORM == "nt"


def sync(source, target, *, delete=False, checksum=True, partial_dir=None,
         ssh_args=None, extra_args=None, timeout=300):
    """执行一次 rsync 同步；未安装直接返回 unsupported_platform。"""
    found = detect()
    if not found:
        if PLATFORM == "nt":
            return _sync_tree(source, target, delete=delete)
        return dict(_UNSUPPORTED)

    argv = [found, "-a"]
    if checksum:
        argv.append("--checksum")
    argv.append("--partial")
    if partial_dir:
        argv += ["--partial-dir", str(partial_dir)]
    if delete:
        argv.append("--delete")
    if ssh_args:
        argv += ["-e", "ssh " + str(ssh_args)]
    if extra_args:
        argv.extend(str(a) for a in extra_args)
    argv += [str(source), str(target)]

    try:
        proc = subprocess.run(
            argv, capture_output=True, text=True, timeout=float(timeout))
    except FileNotFoundError:
        return dict(_UNSUPPORTED)
    except subprocess.TimeoutExpired:
        return {"ok": False, "code": "timeout", "exit": -1,
                "resumable": True, "detail": "rsync timed out after %ss" % timeout}
    except OSError as exc:
        return {"ok": False, "code": "rsync_error", "exit": -1,
                "resumable": False, "detail": str(exc)}

    rc = proc.returncode
    if rc == 0:
        return {"ok": True, "exit": 0, "stdout": proc.stdout or "",
                "stderr": proc.stderr or ""}
    if rc in _PARTIAL_EXITS:
        return {"ok": False, "code": "partial_transfer", "exit": rc,
                "resumable": True, "stderr": proc.stderr or "",
                "detail": "partial transfer; rerun to continue"}
    if rc in _TIMEOUT_EXITS:
        return {"ok": False, "code": "timeout", "exit": rc,
                "resumable": True, "stderr": proc.stderr or ""}
    return {"ok": False, "code": "rsync_error", "exit": rc,
            "resumable": False, "stderr": proc.stderr or ""}



def _is_remote(value):
    text = str(value)
    return "://" not in text and not text.startswith(("/", "\\")) and ":" in text


def _sync_tree(source, target, *, delete=False):
    """Windows 本地目录同步：等价 ``rsync -a --checksum`` 的本地子集。

    只做本地目录，不冒充远端协议；源/目标带尾斜杠表示同步内容，否则同步目录本身。
    先复制后删除，保证中途失败不会先丢目标侧数据。
    """
    src = str(source)
    dst = str(target)
    if _is_remote(src) or _is_remote(dst):
        return {"ok": False, "code": "unsupported_platform",
                "detail": "remote rsync form unsupported by shutil fallback"}
    src_is_dir = os.path.isdir(src)
    if not src_is_dir and not os.path.exists(src):
        return {"ok": False, "code": "rsync_error", "exit": -1,
                "resumable": False, "detail": "source not found: %s" % src}
    try:
        os.makedirs(dst, exist_ok=True)
        if src_is_dir:
            if src.endswith(("/", "\\")):
                shutil.copytree(src, dst, dirs_exist_ok=True, copy_function=shutil.copy2)
            else:
                name = os.path.basename(os.path.normpath(src))
                shutil.copytree(src, os.path.join(dst, name),
                                dirs_exist_ok=True, copy_function=shutil.copy2)
        else:
            shutil.copy2(src, os.path.join(dst, os.path.basename(src)))
        if delete and src_is_dir and src.endswith(("/", "\\")):
            _delete_extras(src, dst)
    except OSError as exc:
        return {"ok": False, "code": "rsync_error", "exit": -1,
                "resumable": False, "detail": str(exc)}
    return {"ok": True, "exit": 0, "stdout": "", "stderr": "",
            "mechanism": "python-shutil"}


def _delete_extras(src_root, dst_root):
    """``--delete`` 的本地语义：目标多出的文件/目录删掉，源有的一律保留。"""
    src_root = os.path.abspath(src_root)
    dst_root = os.path.abspath(dst_root)
    for base, dirs, files in os.walk(dst_root, topdown=False):
        rel_base = os.path.relpath(base, dst_root)
        src_base = src_root if rel_base == "." else os.path.join(src_root, rel_base)
        for name in files:
            if not os.path.exists(os.path.join(src_base, name)):
                os.unlink(os.path.join(base, name))
        for name in dirs:
            target = os.path.join(base, name)
            if not os.path.exists(os.path.join(src_base, name)):
                shutil.rmtree(target, ignore_errors=True)
