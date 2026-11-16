"""进程执行：起进程、喂输入、收输出，超时与打断都能停。"""
from __future__ import annotations

import shutil
import subprocess
import threading
import time


def run(ctx, payload):
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
    try:
        proc = subprocess.Popen(
            argv,
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, cwd=(payload.get("cwd") or None),
        )
    except OSError as exc:
        return {"ok": False, "code": "spawn_failed", "error": str(exc)}

    try:
        proc.stdin.write(str(payload.get("stdin") or ""))
        proc.stdin.close()
    except OSError:
        pass

    buf = {"out": [], "err": []}

    def pump(stream, key):
        try:
            # 逐行读：块读会在管道没填满、没到 EOF 时一直阻塞，流式增量就看不到
            for line in iter(lambda: stream.readline(), ""):
                buf[key].append(line)
                # 正文逐行吐进运行期草稿；stderr 不算答复，不进缓冲
                if key == "out" and stream_key and runtime is not None:
                    runtime.stream_put(stream_key, line)
        except Exception:  # noqa: BLE001 — 进程被 kill 时读线程收尾即可
            pass

    readers = [threading.Thread(target=pump, args=(proc.stdout, "out"), daemon=True),
               threading.Thread(target=pump, args=(proc.stderr, "err"), daemon=True)]
    for t in readers:
        t.start()

    start = time.time()
    killed = None
    while proc.poll() is None:
        if time.time() - start > limit:
            killed = "timeout"
            proc.kill()
            break
        if cancel and runtime is not None:
            if runtime.cancelled(cancel.get("key") or cancel.get("id"), cancel.get("since")):
                killed = "cancelled"
                proc.kill()
                break
        time.sleep(0.1)
    for t in readers:
        t.join(timeout=2)

    out = "".join(buf["out"])
    err = "".join(buf["err"])
    code = proc.poll()
    ok = (code == 0 and killed is None)
    result = {"ok": ok, "code": code, "out": out, "err": err,
              "seconds": round(time.time() - start, 2)}
    if killed:
        result["killed"] = killed
    if not ok:
        result["error"] = (err or out or "进程退出码 %s" % code).strip()[:400]
    return result
