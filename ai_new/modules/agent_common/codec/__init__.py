"""编解码能力：JSON 与 SSE 帧解析。纯计算，不碰网络/文件。

**为什么单独成模块**：序列化不是"对话"，也不是"存储"。谁需要 JSON 就该问 codec，
而不是各自 `import json` —— 否则每个模块都偷偷带着一份"数据格式知识"。
"""
from __future__ import annotations

from .private import _codec


def setup(ctx):
    ctx.codec = _codec
    ctx.api.register("codec.json_encode", lambda c, p: _codec.json_encode(p.get("value")),
                     "对象 → JSON 文本", module="codec")
    ctx.api.register("codec.json_decode", lambda c, p: _codec.json_decode(p.get("text")),
                     "JSON 文本 → 对象", module="codec")
    ctx.api.register("codec.sse_decode", lambda c, p: _codec.sse_decode(p.get("text")),
                     "SSE 文本 → 事件对象列表", module="codec")
    ctx.api.register("codec.digest", lambda c, p: _codec.digest(p.get("text"), p.get("algorithm") or "sha256"),
                     "内容摘要", module="codec")
    ctx.api.register("codec.nonce", lambda c, p: _codec.nonce(p.get("length")),
                     "安全随机令牌", module="codec")
    ctx.api.register("codec.hex_from_base64", lambda c, p: _codec.hex_from_base64(p.get("text")),
                     "base64 → hex", module="codec")
    ctx.api.register("codec.base64_decode_bytes", lambda c, p: _codec.base64_decode_bytes(p.get("text")),
                     "base64 → 原始字节", module="codec")
    ctx.api.register("codec.decode_hex", lambda c, p: _codec.decode_hex(
        p.get("hex"), p.get("max_bytes"), p.get("size")),
        "hex → utf8 文本，非 utf8 退 base64", module="codec")
    ctx.api.register("codec.wave_decode", lambda c, p: _codec.wave_decode(p.get("raw")),
                     "WAV(PCM) 字节 → PCM 帧/采样率", module="codec")
    return True


def json_encode(ctx, value):
    return _codec.json_encode(value)


def json_decode(ctx, text):
    return _codec.json_decode(text)


def sse_decode(ctx, text):
    return _codec.sse_decode(text)
