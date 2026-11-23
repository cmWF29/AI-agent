"""本机传输的平台适配：Unix domain socket 在 Windows 不可用，退 loopback TCP。

能力探测在导入期不崩：只在真正建连时才触达平台原语。:func:`transport_capability`
显式声明当前档位是 ``unix_socket`` 还是 ``tcp_loopback``，不支持的通道不冒充。
"""
from __future__ import annotations

import os
import socket
import time

PLATFORM = "nt" if os.name == "nt" else "posix"

# 绑端口重试上限：瞬时占用 / TIME_WAIT 退避重试；超过上限显式报错，不静默降级。
LISTEN_RETRIES = 5
# 监听 socket 轮询超时（秒）：stop() 后 accept 能及时醒来退出，不卡在阻塞 accept 上。
LISTEN_TIMEOUT = 1.0


def supports_unix_socket():
    """本机是否可用 AF_UNIX：Windows 没有该地址族。"""
    return PLATFORM != "nt" and hasattr(socket, "AF_UNIX")


def default_transport():
    """当前本机通道默认档位。"""
    return "unix_socket" if supports_unix_socket() else "tcp_loopback"


def transport_capability():
    """传输档位上报：支持哪些本机通道、当前默认走哪条。"""
    return {
        "ok": True,
        "platform": PLATFORM,
        "transport": default_transport(),
        "unix_socket": supports_unix_socket(),
        "tcp_loopback": True,
        "note": ("Windows 无 AF_UNIX：本机通道退到 127.0.0.1 随机端口，"
                 "端口记在连接文件。" if PLATFORM == "nt"
                 else "POSIX 本机通道优先 AF_UNIX。"),
    }


def loopback_listen(host="127.0.0.1", backlog=64):
    """绑 loopback 随机端口；返回 ``(socket, host, port)``。

    绑定失败按退避重试到上限；监听 socket 带轮询超时，便于 stop 后及时退出。
    重试耗尽抛 OSError，由调用方显式报错，不许静默起不来还假装在监听。
    """
    last_exc = None
    for attempt in range(LISTEN_RETRIES):
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            srv.bind((host, 0))
            srv.listen(backlog)
            srv.settimeout(LISTEN_TIMEOUT)
            return srv, host, srv.getsockname()[1]
        except OSError as exc:
            srv.close()
            last_exc = exc
            time.sleep(0.05 * (attempt + 1))
    raise OSError("loopback 监听重试 %d 次仍失败: %s" % (LISTEN_RETRIES, last_exc))


def addr_file_for(unix_path):
    """Unix 路径对应的 loopback 连接文件路径（端口侧车文件）。"""
    return str(unix_path) + ".port"


def write_addr_file(addr_file, host, port):
    """连接文件记录 loopback 地址（``host:port``），供对端回连。"""
    with open(str(addr_file), "w", encoding="utf-8") as fh:
        fh.write("%s:%d" % (host, port))


def read_addr_file(addr_file):
    """读连接文件 -> ``(host, port)``；不存在/损坏返回 None。"""
    try:
        with open(str(addr_file), "r", encoding="utf-8") as fh:
            host, _, port = fh.read().strip().partition(":")
        if not host or not port:
            return None
        return host, int(port)
    except (OSError, ValueError, AttributeError):
        return None


def connect_loopback(host, port, timeout=None):
    """连到 loopback 监听；返回已连接 socket。"""
    conn = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    if timeout is not None:
        conn.settimeout(timeout)
    conn.connect((host, int(port)))
    return conn
