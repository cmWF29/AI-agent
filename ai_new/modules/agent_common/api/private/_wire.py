"""通信报文协议：单点定义，服务端与客户端共用同一份。

一帧 = 4 字节长度前缀（网络字节序）+ UTF-8 的 YAML flow 报文：

    {v: 1, token: "...", route: "module.fn", payload: {...}}

应答同为 flow 报文：`{ok: true, result: ...}` 或 `{ok: false, error, code}`。
`v` 是协议版本：将来加压缩、分片、幂等键都从这里扩，不再各写一份。

socket 通道的 seq 恒为 0；共享内存信箱用 seq 区分"这一次请求/应答"，
避免读到上一轮的残留应答。
"""
from __future__ import annotations

import struct

VERSION = 1
HDR = struct.Struct("!ii")      # (length, seq)
LEN = struct.Struct("!i")       # 纯长度前缀（socket 帧）
MAX_PAYLOAD = 512 * 1024        # 单帧上限：超了就是协议错，不是业务错


def pack(codec, route, payload, token="", seq=0):
    """请求报文：route + payload（+ 令牌）。"""
    rec = {"v": VERSION, "route": route, "payload": payload or {}}
    if token:
        rec["token"] = token
    return codec.yaml_encode_flow(rec)["text"].encode("utf-8")


def unpack(codec, text):
    """请求/应答报文 → dict（结构不对就抛，由调用方归一成协议错误）。"""
    return (codec.yaml_decode(text or "{}")["value"] or {})


def send_frame(sock, body):
    """发一帧：长度前缀 + 报文。"""
    sock.sendall(LEN.pack(len(body)) + body)


def read_frame(sock, exhausted=None):
    """收一帧；对端提前断开返回 None（错误语义由调用方决定）。"""
    head = b""
    while len(head) < 4:
        chunk = sock.recv(4 - len(head))
        if not chunk:
            return None
        head += chunk
    length = LEN.unpack(head)[0]
    if length <= 0 or length > MAX_PAYLOAD:
        return None
    data = b""
    while len(data) < length:
        chunk = sock.recv(length - len(data))
        if not chunk:
            return None
        data += chunk
    return data
