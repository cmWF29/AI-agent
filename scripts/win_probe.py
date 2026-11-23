#!/usr/bin/env python3
"""平台探针：在 CI 装配/用例之前先把 OS 与 plat 能力面打到日志里。

输出三段：
  1. 解释器/OS 基本面（sys.platform、os.name、版本、socket 地址族可用性）；
  2. plat.capability() 锁 / 传输 / 进程三档上报；
  3. 一次 loopback TCP 监听 + 回连自检（绑失败/连不上要显式报错，不静默降级）。

探针只读、不装配业务模块、不起常驻服务；任何一档异常都以非零退出码收口，
让 CI 在后续步骤之前先暴露平台侧问题。
"""
import os
import socket
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ai_new.modules.agent_common.plat import capability  # noqa: E402
from ai_new.modules.agent_common.plat.private import _net  # noqa: E402


def _families():
    """探测 socket 地址族可用性：属性存在不等于能绑，AF_UNIX 在 Windows 直接缺。"""
    out = {}
    for name in ("AF_UNIX", "AF_INET", "AF_INET6"):
        out[name] = hasattr(socket, name)
    return out


def _loopback_selfcheck():
    """起一个 loopback 监听并回连一次；返回 (ok, 细节)。"""
    srv = None
    try:
        srv, host, port = _net.loopback_listen()
        conn = _net.connect_loopback(host, port, timeout=3)
        try:
            peer = conn.getpeername()
        finally:
            conn.close()
        return True, "listen %s:%d -> peer %s" % (host, port, peer[1])
    except OSError as exc:
        return False, "%s: %s" % (type(exc).__name__, exc)
    finally:
        if srv is not None:
            try:
                srv.close()
            except OSError:
                pass


def main():
    print("== 解释器 / OS ==", flush=True)
    print("  sys.platform: %s" % sys.platform, flush=True)
    print("  os.name: %s" % os.name, flush=True)
    print("  version: %s" % sys.version.replace("\n", " "), flush=True)
    print("  socket families: %s" % _families(), flush=True)

    print("== plat.capability ==", flush=True)
    cap = capability()
    print("  platform: %s" % cap["platform"], flush=True)
    print("  lock: %s" % cap["lock"], flush=True)
    print("  transport: %s" % cap["transport"], flush=True)
    print("  proc: %s" % cap["proc"], flush=True)

    print("== loopback TCP 自检 ==", flush=True)
    ok, detail = _loopback_selfcheck()
    print("  ok=%s | %s" % (ok, detail), flush=True)
    if not ok:
        print("  探针失败：loopback TCP 不可用", flush=True)
        return 1

    print("  平台探针通过", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
