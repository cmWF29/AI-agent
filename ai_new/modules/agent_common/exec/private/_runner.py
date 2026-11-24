"""进程执行：起进程、喂输入、收输出，超时与打断都能停。

异步核心走 ``asyncio.create_subprocess_exec``：stdout/stderr 由协程逐行泵出，
等待子进程期间挂起事件循环而不占线程；另留同步壳桥接到进程级事件循环，
供同步内部调用与兼容路径使用。
"""
from __future__ import annotations

import asyncio
import os
import posixpath
import shutil
import time
from pathlib import Path


def _virtual_path(raw, label):
    """规范 bwrap 命名空间内的虚拟路径，拒绝 ``..``/空字节/相对路径。

    bwrap 的 ``--chdir`` 和 ``--bind`` 目的地都是命名空间内路径，不能拿真实宿主
    路径的字符串前缀直接判断；否则 ``/workspace/../etc`` 能绕过“落在挂载点内”
    的检查。这里先按 POSIX 段归一，再做包含判断。
    """
    value = str(raw or "")
    if "\x00" in value:
        return "", "%s 含空字节" % label
    if not value.startswith("/"):
        return "", "%s 必须是绝对路径" % label
    parts = [p for p in value.split("/") if p not in ("", ".")]
    if any(p == ".." for p in parts):
        return "", "%s 含越界片段" % label
    norm = posixpath.normpath(value)
    if norm == "/" or not norm.startswith("/"):
        return "", "%s 归一后不是有效路径" % label
    return norm, None


def _bwrap_command(payload, cwd):
    """把一次 shell 调用包进 bwrap mount namespace；只认显式 sandbox 描述。

    - 项目根以 ``/workspace`` 为唯一可写挂载点进入新根，宿主其余路径不可见；
    - 系统工具链只读挂载，/tmp 与 /dev 每次执行新建；
    - 描述不完整或 bwrap 起不来时 fail-closed，不静默退回普通 cwd。
    """
    sandbox = payload.get("sandbox") or {}
    if sandbox.get("engine") != "bwrap":
        return [], None
    bwrap = shutil.which("bwrap")
    if not bwrap:
        return [], "bwrap 不在 PATH，强档隔离不可用"
    root = str(sandbox.get("root") or "")
    mount_raw = str(sandbox.get("mount") or "")
    inner_raw = str(sandbox.get("cwd") or "")
    if not root or not mount_raw or not inner_raw:
        return [], "sandbox 描述缺少 root/mount/cwd"
    if not os.path.isabs(root) or root == "/":
        return [], "sandbox root 必须是非根绝对路径"
    mount, err = _virtual_path(mount_raw, "mount")
    if err:
        return [], "sandbox " + err
    inner, err = _virtual_path(inner_raw, "cwd")
    if err:
        return [], "sandbox " + err
    if inner != mount and not inner.startswith(mount.rstrip("/") + "/"):
        return [], "sandbox cwd 必须落在项目根挂载点内"
    try:
        Path(root).mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        return [], "项目根不可创建: %s" % exc
    binds = sandbox.get("binds") or [{"src": root, "dst": mount}]
    prepared = []
    root_real = Path(root).resolve(strict=False)
    for bind in binds:
        src = str(bind.get("src") or "")
        dst_raw = str(bind.get("dst") or "")
        if not src or not dst_raw or not os.path.isabs(src):
            return [], "sandbox bind 描述不完整"
        dst, err = _virtual_path(dst_raw, "bind 目的地")
        if err:
            return [], "sandbox " + err
        if dst != mount and not dst.startswith(mount.rstrip("/") + "/"):
            return [], "sandbox bind 目的地越出挂载点"
        try:
            src_real = Path(src).resolve(strict=False)
        except OSError as exc:
            return [], "sandbox bind 源不可用: %s" % exc
        try:
            src_real.relative_to(root_real)
        except ValueError:
            return [], "sandbox bind 源越出项目根"
        try:
            Path(src).mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            return [], "sandbox bind 源不可用: %s" % exc
        prepared.append((str(src_real), dst))
    args = [bwrap, "--unshare-all", "--share-net", "--die-with-parent",
            "--new-session"]
    parents = {mount}
    for _, dst in prepared:
        parts = dst.strip("/").split("/")
        for i in range(1, len(parts)):
            parents.add("/" + "/".join(parts[:i]))
    for parent in sorted(parents, key=len):
        args += ["--dir", parent]
    for src, dst in prepared:
        args += ["--bind", src, dst]
    args += ["--chdir", inner, "--tmpfs", "/tmp", "--dev", "/dev"]
    for path in ("/usr", "/bin", "/sbin", "/lib", "/lib64", "/etc"):
        if Path(path).exists():
            args += ["--ro-bind", path, path]
    args += ["--", "/usr/bin/env", "-i",
             "PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
             "HOME=" + mount, "TMPDIR=/tmp"]
    for key in ("LANG", "LC_ALL", "TZ"):
        value = os.environ.get(key)
        if value:
            args += ["%s=%s" % (key, value)]
    return args, None


async def _arun(ctx, payload):
    payload = payload or {}
    argv = [str(a) for a in (payload.get("argv") or []) if str(a) != ""]
    if not argv:
        return {"ok": False, "code": "no_argv", "error": "没有可执行的命令"}
    sandbox = payload.get("sandbox") or {}
    if sandbox.get("engine") != "bwrap" and shutil.which(argv[0]) is None:
        return {"ok": False, "code": "command_not_found", "error": "找不到命令: %s" % argv[0]}

    limit = float(payload.get("timeout") or 300)
    cancel = payload.get("cancel") or {}
    stream_key = payload.get("stream_key") or ""
    runtime = getattr(ctx, "runtime", None)
    stdin_text = str(payload.get("stdin") or "")
    cwd = str(payload.get("cwd") or "")
    if cwd and payload.get("ensure_cwd"):
        # 只由已校验过的工作区调用方传入；进程执行层只补目录，不做路径策略。
        try:
            Path(cwd).mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            return {"ok": False, "code": "cwd_unavailable", "error": str(exc)}

    prefix, sandbox_error = _bwrap_command(payload, cwd)
    if sandbox_error:
        return {"ok": False, "code": "sandbox_unavailable", "error": sandbox_error}
    command = prefix + argv

    try:
        proc = await asyncio.create_subprocess_exec(
            *command,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=(cwd or None),
        )
    except OSError as exc:
        return {"ok": False, "code": "spawn_failed", "error": str(exc)}

    try:
        if stdin_text:
            proc.stdin.write(stdin_text.encode("utf-8", "replace"))
            await proc.stdin.drain()
        proc.stdin.close()
    except (OSError, BrokenPipeError):
        pass

    buf = {"out": [], "err": []}

    async def pump(stream, key):
        try:
            # 逐行读：块读会在管道没填满、没到 EOF 时一直阻塞，流式增量就看不到
            while True:
                raw = await stream.readline()
                if not raw:
                    break
                line = raw.decode("utf-8", "replace")
                buf[key].append(line)
                # 正文逐行吐进运行期草稿；stderr 不算答复，不进缓冲
                if key == "out" and stream_key and runtime is not None:
                    runtime.stream_put(stream_key, line)
        except Exception:  # noqa: BLE001 — 进程被 kill 时泵协程收尾即可
            pass

    pump_task = asyncio.gather(pump(proc.stdout, "out"), pump(proc.stderr, "err"))

    start = time.time()
    killed = None
    while proc.returncode is None:
        if time.time() - start > limit:
            killed = "timeout"
            proc.kill()
            break
        if cancel and runtime is not None:
            if runtime.cancelled(cancel.get("key") or cancel.get("id"), cancel.get("since")):
                killed = "cancelled"
                proc.kill()
                break
        try:
            await asyncio.wait_for(proc.wait(), timeout=0.1)
        except asyncio.TimeoutError:
            pass
    try:
        await pump_task
    except Exception:  # noqa: BLE001
        pass

    out = "".join(buf["out"])
    err = "".join(buf["err"])
    code = proc.returncode
    ok = (code == 0 and killed is None)
    result = {"ok": ok, "code": code, "out": out, "err": err,
              "seconds": round(time.time() - start, 2)}
    if killed:
        result["killed"] = killed
    if not ok:
        cap = int(ctx.api.call("config.get", {"key": "exec.error_chars"},
                               caller=None).get("value") or 0)
        result["error"] = (err or out or "进程退出码 %s" % code).strip()[:cap]
    return result


def run(ctx, payload):
    """同步壳：桥接异步核心到进程级事件循环，供同步内部调用与兼容路径使用。"""
    loop = ctx.api._ensure_loop()
    return asyncio.run_coroutine_threadsafe(_arun(ctx, payload), loop).result()
