"""JSON / SSE 编解码实现。失败是结果：{ok: False, error}。"""
from __future__ import annotations

import base64
import hashlib
import io
import json
import secrets
import wave

import yaml

# 优先 C 扩展 Loader/Dumper（libyaml），解析/序列化大报文约快一个数量级；
# 环境无 C 扩展时回退纯 Python Safe 版本，语义同为安全子集。
_YAML_LOADER = getattr(yaml, "CSafeLoader", yaml.SafeLoader)
_YAML_DUMPER = getattr(yaml, "CSafeDumper", yaml.SafeDumper)


def json_encode(value):
    try:
        return {"ok": True, "text": json.dumps(value, ensure_ascii=False)}
    except (TypeError, ValueError) as exc:
        return {"ok": False, "error": str(exc), "code": "encode_failed"}


def json_decode(text):
    try:
        return {"ok": True, "value": json.loads(text or "null")}
    except ValueError as exc:
        return {"ok": False, "error": str(exc), "code": "decode_failed"}

def yaml_encode(value):
    try:
        text = yaml.dump(value, Dumper=_YAML_DUMPER, allow_unicode=True,
                         sort_keys=False, default_flow_style=False)
        return {"ok": True, "text": text}
    except (TypeError, ValueError, yaml.YAMLError) as exc:
        return {"ok": False, "error": str(exc), "code": "encode_failed"}


def yaml_encode_flow(value):
    """报文/SSE 用：YAML flow 单行，保持现有分帧与 Content-Length。"""
    try:
        # 无限宽度：不然长值会在 80 列处折行，SSE 只认 `data:` 首行，帧就被截断
        text = yaml.dump(value, Dumper=_YAML_DUMPER, allow_unicode=True,
                         sort_keys=False, default_flow_style=True, width=10 ** 9)
        return {"ok": True, "text": text.strip()}
    except (TypeError, ValueError, yaml.YAMLError) as exc:
        return {"ok": False, "error": str(exc), "code": "encode_failed"}


def yaml_decode(text):
    try:
        return {"ok": True, "value": yaml.load(text or "null", Loader=_YAML_LOADER)}
    except yaml.YAMLError as exc:
        return {"ok": False, "error": str(exc), "code": "decode_failed"}


def sse_decode(text):
    """把 `data: {...}` 行解析成对象列表；非 data 行（注释/空行）忽略。"""
    items = []
    for line in (text or "").splitlines():
        line = line.strip()
        if not line.startswith("data:"):
            continue
        chunk = line[5:].strip()
        if chunk == "[DONE]":
            continue
        try:
            items.append(json.loads(chunk))
        except ValueError:
            continue
    return {"ok": True, "items": items}


def base64_decode_bytes(text):
    try:
        return {"ok": True, "data": base64.b64decode(str(text or ""))}
    except (TypeError, ValueError) as exc:
        return {"ok": False, "error": str(exc), "code": "decode_failed"}


def digest(text, algorithm="sha256"):
    """摘要：内容指纹，不是业务语义。"""
    try:
        algo = getattr(hashlib, str(algorithm or "sha256"))
        raw = text if isinstance(text, (bytes, bytearray)) else str(text or "").encode("utf-8")
        return {"ok": True, "hex": algo(bytes(raw)).hexdigest()}
    except (AttributeError, TypeError, ValueError) as exc:
        return {"ok": False, "error": str(exc), "code": "bad_algorithm"}


def nonce(length=32):
    """安全随机令牌：URL 安全，给会话/一次性凭证用。随机数是能力，业务模块不自带。"""
    try:
        size = max(8, int(length or 32))
        return {"ok": True, "token": secrets.token_urlsafe(size)}
    except (TypeError, ValueError) as exc:
        return {"ok": False, "error": str(exc), "code": "nonce_failed"}


def decode_hex(hex_text, max_bytes=None, size=None):
    """hex 字节 → utf8 文本；非 utf8 退 base64 承载。截断阈值与截断标记在此成形。"""
    try:
        raw_all = bytes.fromhex(str(hex_text or ""))
        limit = int(max_bytes) if max_bytes is not None else len(raw_all)
        raw = raw_all[:limit]
        truncated = int(size or 0) > limit
    except (TypeError, ValueError) as exc:
        return {"ok": False, "error": str(exc), "code": "decode_failed"}
    try:
        return {"ok": True, "text": raw.decode("utf-8"), "encoding": "utf8",
                "truncated": truncated}
    except UnicodeDecodeError:
        return {"ok": True, "text": base64.b64encode(raw).decode("ascii"),
                "encoding": "binary", "needs_encode": True, "truncated": truncated}


def hex_from_base64(text):
    try:
        return {"ok": True, "hex": base64.b64decode(str(text or "")).hex()}
    except (TypeError, ValueError) as exc:
        return {"ok": False, "error": str(exc), "code": "decode_failed"}


def wave_decode(raw):
    """WAV(PCM) 字节 → {pcm 字节, rate, channels}；压缩/解析失败结构化报错。"""
    try:
        wav = wave.Wave_read(io.BytesIO(bytes(raw or b"")))
    except wave.Error as exc:
        return {"ok": False, "code": "bad_audio", "error": str(exc)}
    with wav:
        if wav.getcomptype() != "NONE":
            return {"ok": False, "code": "compressed_wav", "error": "仅支持未压缩 PCM WAV"}
        rate = wav.getframerate()
        channels = wav.getnchannels()
        pcm = wav.readframes(wav.getnframes())
    return {"ok": True, "pcm": pcm, "rate": rate, "channels": channels}
