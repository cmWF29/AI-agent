"""JSON / SSE 编解码实现。失败是结果：{ok: False, error}。"""
from __future__ import annotations

import base64
import hashlib
import json
import secrets

import yaml


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
        text = yaml.safe_dump(value, allow_unicode=True, sort_keys=False,
                              default_flow_style=False)
        return {"ok": True, "text": text}
    except (TypeError, ValueError, yaml.YAMLError) as exc:
        return {"ok": False, "error": str(exc), "code": "encode_failed"}


def yaml_encode_flow(value):
    """报文/SSE 用：YAML flow 单行，保持现有分帧与 Content-Length。"""
    try:
        text = yaml.safe_dump(value, allow_unicode=True, sort_keys=False,
                              default_flow_style=True)
        return {"ok": True, "text": text.strip()}
    except (TypeError, ValueError, yaml.YAMLError) as exc:
        return {"ok": False, "error": str(exc), "code": "encode_failed"}


def yaml_decode(text):
    try:
        return {"ok": True, "value": yaml.safe_load(text or "null")}
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


def base64_encode(value):
    """文本/字节 → base64 文本（交付件里的二进制内容走这条）。"""
    try:
        raw = value if isinstance(value, (bytes, bytearray)) else str(value or "").encode("utf-8")
        return {"ok": True, "text": base64.b64encode(bytes(raw)).decode("ascii")}
    except (TypeError, ValueError) as exc:
        return {"ok": False, "error": str(exc), "code": "encode_failed"}


def base64_decode(text):
    try:
        return {"ok": True, "value": base64.b64decode(str(text or "")).decode("utf-8")}
    except (TypeError, ValueError) as exc:
        return {"ok": False, "error": str(exc), "code": "decode_failed"}


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


def base64_from_hex(text):
    """字节的十六进制写法 → base64（二进制跨越消息边界时用 hex 承载）。"""
    try:
        return {"ok": True, "text": base64.b64encode(bytes.fromhex(str(text or ""))).decode("ascii")}
    except (TypeError, ValueError) as exc:
        return {"ok": False, "error": str(exc), "code": "decode_failed"}


def hex_from_base64(text):
    try:
        return {"ok": True, "hex": base64.b64decode(str(text or "")).hex()}
    except (TypeError, ValueError) as exc:
        return {"ok": False, "error": str(exc), "code": "decode_failed"}
