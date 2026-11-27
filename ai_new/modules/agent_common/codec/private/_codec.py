"""JSON / SSE 编解码实现。失败是结果：{ok: False, error}。"""
from __future__ import annotations

import base64
import hashlib
import io
import json
import re
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
    except (TypeError, ValueError) as exc:
        return {"ok": False, "error": str(exc), "code": "decode_failed"}

def _jsonish(raw):
    """尽量解一段 JSON 字面量：先严格，再把模型写坏的反斜杠去掉重试。"""
    for candidate in (raw, re.sub(r'\\(?!["\\/bfnrtu])', "", raw)):
        try:
            return json.loads(candidate, strict=False)
        except (TypeError, ValueError):
            continue
    return None


def _json_field(text, key):
    """从坏 JSON 里抽一个字符串字段：只认开引号后的原文，按 JSON 字符串规则收口。

    返回 None 表示没有这个字段；空串是合法值。
    """
    hit = re.search(r'"%s"\s*:\s*"' % re.escape(key), text or "")
    if not hit:
        return None
    body, escaped = [], False
    for ch in text[hit.end():]:
        if escaped:
            body.append("\\")
            body.append(ch)
            escaped = False
        elif ch == "\\":
            escaped = True
        elif ch == '"':
            break
        else:
            body.append(ch)
    raw = "".join(body)
    out = _jsonish('"' + raw + '"')
    return out if isinstance(out, str) else raw


def _json_array(text, key):
    """从坏 JSON 里抽数组字段：按括号深度和字符串状态截取，再走同一套容错解码。"""
    hit = re.search(r'"%s"\s*:\s*\[' % re.escape(key), text or "")
    if not hit:
        return None
    depth, in_str, escaped = 1, False, False
    raw = ["["]
    for ch in text[hit.end():]:
        raw.append(ch)
        if in_str:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "[":
            depth += 1
        elif ch == "]":
            depth -= 1
            if depth == 0:
                out = _jsonish("".join(raw))
                return out if isinstance(out, list) else None
    return None


def json_salvage(text):
    """坏收口报文的最小抢救：逐字段抽字符串/数组，抽到任何一项就算结构化。

    只在整段 JSON 解码失败时兜底，避免把普通正文误当协议报文。
    """
    out, found = {}, False
    for key in ("reply", "summary", "stage"):
        value = _json_field(text, key)
        if value is not None:
            out[key] = value.strip() if key in ("summary", "stage") else value
            found = True
    for key in ("checklist", "violations", "questions"):
        value = _json_array(text, key)
        if value is not None:
            out[key] = value
            found = True
    if not found:
        return {"ok": False, "error": "no protocol fields", "code": "decode_failed"}
    return {"ok": True, "value": out}


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
    if not isinstance(text, (str, bytes, bytearray)):
        return {"ok": False, "error": "SSE 文本必须是字符串", "code": "decode_failed"}
    if isinstance(text, (bytes, bytearray)):
        text = bytes(text).decode("utf-8", "replace")
    items = []
    for line in text.splitlines():
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


def base64_encode(text):
    """文本/字节 → base64 文本；与 base64_decode_bytes 成对，供契约里成对声明的调用方使用。"""
    try:
        raw = text if isinstance(text, (bytes, bytearray)) else str(text or "").encode("utf-8")
        return {"ok": True, "text": base64.b64encode(bytes(raw)).decode("ascii")}
    except (TypeError, ValueError) as exc:
        return {"ok": False, "error": str(exc), "code": "encode_failed"}


_DIGEST_ALGOS = {"md5", "sha1", "sha224", "sha256", "sha384", "sha512", "blake2b", "blake2s"}
_NONCE_MIN = 8
_NONCE_MAX = 4096


def digest(text, algorithm="sha256"):
    """摘要：内容指纹，不是业务语义。

    算法名来自不可信输入，不能直接 ``getattr(hashlib, name)``：那会把
    ``pbkdf2_hmac``/``scrypt`` 这类高开销函数当成摘要调用，形成 CPU/内存放大。
    只放行固定摘要族，未知算法返回结构化错误。
    """
    algo_name = str(algorithm or "sha256").strip().lower()
    if algo_name not in _DIGEST_ALGOS:
        return {"ok": False, "error": "不支持的摘要算法: %s" % algo_name,
                "code": "bad_algorithm"}
    try:
        algo = getattr(hashlib, algo_name)
        raw = text if isinstance(text, (bytes, bytearray)) else str(text or "").encode("utf-8")
        return {"ok": True, "hex": algo(bytes(raw)).hexdigest()}
    except (AttributeError, TypeError, ValueError) as exc:
        return {"ok": False, "error": str(exc), "code": "bad_algorithm"}


def nonce(length=32):
    """安全随机令牌：URL 安全，给会话/一次性凭证用。

    长度是调用方可控值，必须有硬上限；否则一个请求就能让 ``token_urlsafe``
    分配超大字符串，拖垮进程。低于 8 仍按 8，高于 4096 按 4096。
    """
    try:
        size = max(_NONCE_MIN, min(_NONCE_MAX, int(length or 32)))
        return {"ok": True, "token": secrets.token_urlsafe(size)}
    except (TypeError, ValueError) as exc:
        return {"ok": False, "error": str(exc), "code": "nonce_failed"}


def decode_hex(hex_text, max_bytes=None, size=None):
    """hex 字节 → utf8 文本；非 utf8 退 base64 承载。截断阈值与截断标记在此成形。"""
    try:
        raw_all = bytes.fromhex(str(hex_text or ""))
        if max_bytes is None:
            limit = len(raw_all)
        else:
            limit = max(0, min(len(raw_all), int(max_bytes)))
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
    if not isinstance(raw, (bytes, bytearray)):
        return {"ok": False, "code": "bad_audio", "error": "音频必须是字节"}
    try:
        wav = wave.Wave_read(io.BytesIO(bytes(raw)))
    except (wave.Error, EOFError, OSError, ValueError) as exc:
        return {"ok": False, "code": "bad_audio", "error": str(exc)}
    with wav:
        if wav.getcomptype() != "NONE":
            return {"ok": False, "code": "compressed_wav", "error": "仅支持未压缩 PCM WAV"}
        rate = wav.getframerate()
        channels = wav.getnchannels()
        pcm = wav.readframes(wav.getnframes())
    return {"ok": True, "pcm": pcm, "rate": rate, "channels": channels}
