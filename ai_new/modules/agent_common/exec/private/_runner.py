"""进程执行：起进程、喂输入、收输出，超时与打断都能停。

异步核心走 ``asyncio.create_subprocess_exec``：stdout/stderr 由协程逐行泵出，
等待子进程期间挂起事件循环而不占线程；另留同步壳桥接到进程级事件循环，
供同步内部调用与兼容路径使用。
"""
from __future__ import annotations

import asyncio
import shutil
import time
from pathlib import Path


async def _arun(ctx, payload):
    payload = payload or {}
    argv = [str(a) for a in (payload.get("argv") or []) if str(a) != ""]
    if not argv:
        return {"ok": False, "code": "no_argv", "error": "没有可执行的命令"}
    if shutil.which(argv[0]) is None:
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

    try:
        proc = await asyncio.create_subprocess_exec(
            *argv,
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
