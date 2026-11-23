"""凭证封装层：AES-256-GCM 信封加密。

密钥来源（优先级从高到低）：

1. 环境变量 ``AI_NEW_SECRET_KEY``：32 字节主密钥的 base64（标准/URL-safe 均可）；
2. 密钥文件：路径取环境变量 ``AI_NEW_SECRET_KEY_FILE``，默认
   ``~/.ai_new/secrets.key``；文件内为 32 字节 base64 文本。文件不存在时以 0600
   权限安全生成；已存在则校验长度，非法即报错，不回退明文。

信封格式（版本化）::

    v1:<base64(nonce(12B) || ciphertext || GCM tag)>

AAD 绑定 ``profile 标识 + provider``：密封串跨 profile/提供方互换时 GCM 校验
失败（``seal_invalid``），防止凭证在不同配置间被拆包复用。

硬约束：

- 主密钥只在内存中用于加解密；不落仓库、不落配置文件、不进日志、不进前端响应；
- 缺密钥/密钥非法时显式抛 ``SealError``，绝不回落明文存储；
- 任何对外视图（列表/详情/状态/审计/错误信息）一律先经 ``mask`` 脱敏；
- 旧版可逆混淆串（``obf1:``）按非密封串拒绝，不做兼容解封。

兼容说明：仅使用 ``cryptography`` 2.8 起即有的 ``AESGCM`` 原语，不引用 3.x 专属 API。
编解码/随机数一律经 ``codec`` 能力接缝；密钥文件 IO 归本模块自持（见能力台账豁免）。
"""
from __future__ import annotations

import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

ENV_KEY = "AI_NEW_SECRET_KEY"
ENV_KEY_FILE = "AI_NEW_SECRET_KEY_FILE"
DEFAULT_KEY_FILE = os.path.join(os.path.expanduser("~"), ".ai_new", "secrets.key")

_PREFIX = "v1"
_KEY_LEN = 32
_NONCE_LEN = 12
REDACTED = "<redacted>"

_AAD_PREFIX = b"agent/cloud/v1:"


class SealError(Exception):
    """封装层错误：code 稳定可匹配，message 不携带密钥或明文。"""

    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


# ---------------------------------------------------------------- codec 接缝

def _b64encode(ctx, raw):
    row = ctx.api.call("codec.base64_encode", {"text": raw}, caller=None)
    if not row.get("ok"):
        raise SealError("seal_invalid", "base64 encode failed")
    return row["text"]


def _b64decode(ctx, text, code="seal_invalid"):
    row = ctx.api.call("codec.base64_decode_bytes", {"text": str(text or "")},
                       caller=None)
    if not row.get("ok"):
        raise SealError(code, "base64 decode failed")
    return row["data"]


def _nonce_bytes(ctx):
    """12 字节随机数：两个 nonce 令牌喂摘要，取前 12 字节；随机数能力归 codec。"""
    t1 = ctx.api.call("codec.nonce", {"length": 16}, caller=None).get("token") or ""
    t2 = ctx.api.call("codec.nonce", {"length": 16}, caller=None).get("token") or ""
    digest = ctx.api.call("codec.digest", {"text": t1 + ":" + t2},
                          caller=None).get("hex") or ""
    return bytes.fromhex(digest)[:_NONCE_LEN]


def _random_key_material(ctx):
    """32 字节密钥材料：nonce 令牌经摘要派生；熵来自 codec 安全随机令牌。"""
    t1 = ctx.api.call("codec.nonce", {"length": 16}, caller=None).get("token") or ""
    t2 = ctx.api.call("codec.nonce", {"length": 16}, caller=None).get("token") or ""
    digest = ctx.api.call("codec.digest", {"text": "key:" + t1 + ":" + t2},
                          caller=None).get("hex") or ""
    return bytes.fromhex(digest)[:_KEY_LEN]


# ---------------------------------------------------------------- 密钥来源

def _key_path(ctx):
    row = ctx.api.call("host.env", {"name": ENV_KEY_FILE}, caller=None)
    override = (row or {}).get("value")
    return str(override).strip() if override else DEFAULT_KEY_FILE


def _decode_key(ctx, raw, code):
    """base64 文本 → 32 字节密钥；长度/编码非法抛 SealError。"""
    text = str(raw or "").strip()
    if not text:
        raise SealError(code, "secret key is empty")
    key = _b64decode(ctx, text, code)
    if len(key) != _KEY_LEN:
        raise SealError(code, "secret key must decode to %d bytes" % _KEY_LEN)
    return key


def _read_key_file(path):
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return fh.read()
    except OSError as exc:
        raise SealError("master_key_missing", "cannot read secret key file") from exc


def _generate_key_file(ctx, path):
    """密钥文件缺失：0600 安全生成 32 字节随机密钥并原子落盘。"""
    parent = os.path.dirname(os.path.abspath(path))
    try:
        os.makedirs(parent, mode=0o700, exist_ok=True)
        material = _b64encode(ctx, _random_key_material(ctx))
        # 临时文件（nonce 派生唯一名）+ 原子改名，避免半截密钥文件；权限先收窄再落盘。
        tag = ctx.api.call("codec.digest", {"text": "tmp:" + material},
                           caller=None).get("hex")[:8]
        tmp = path + ".tmp." + tag
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(material + "\n")
            os.replace(tmp, path)
        except Exception:
            if os.path.exists(tmp):
                os.unlink(tmp)
            raise
        os.chmod(path, 0o600)
    except OSError as exc:
        raise SealError("master_key_missing", "cannot generate secret key file") from exc


def _load_key(ctx):
    """按优先级取 32 字节主密钥；任何来源失败都显式报错，不回退明文。"""
    row = ctx.api.call("host.env", {"name": ENV_KEY}, caller=None)
    env_value = (row or {}).get("value")
    if env_value:
        return _decode_key(ctx, env_value, "master_key_invalid")
    path = _key_path(ctx)
    if not os.path.exists(path):
        _generate_key_file(ctx, path)
    return _decode_key(ctx, _read_key_file(path), "master_key_invalid")


# ---------------------------------------------------------------- 信封原语

def _aad(profile_id, provider):
    return (_AAD_PREFIX + str(profile_id or "").encode("utf-8") + b":"
            + str(provider or "").encode("utf-8"))


def is_sealed(value):
    return isinstance(value, str) and value.startswith(_PREFIX + ":")


def seal(ctx, secret, profile_id="", provider=""):
    """明文 → v1 信封串。secret 必须是非空字符串；明文不回写、不落日志。"""
    text = str(secret or "")
    if not text:
        raise SealError("empty_secret", "secret is empty")
    key = _load_key(ctx)
    nonce = _nonce_bytes(ctx)
    ciphertext = AESGCM(key).encrypt(nonce, text.encode("utf-8"), _aad(profile_id, provider))
    body = _b64encode(ctx, nonce + ciphertext)
    return _PREFIX + ":" + body


def open_sealed(ctx, sealed, profile_id="", provider=""):
    """v1 信封串 → 明文；格式不符、tag/AAD 校验失败抛 SealError。"""
    if not is_sealed(sealed):
        raise SealError("not_sealed", "value is not a sealed blob")
    payload = sealed.split(":", 1)[1]
    body = _b64decode(ctx, payload)
    if len(body) <= _NONCE_LEN:
        raise SealError("seal_invalid", "sealed blob is truncated")
    nonce, ciphertext = body[:_NONCE_LEN], body[_NONCE_LEN:]
    key = _load_key(ctx)
    try:
        plain = AESGCM(key).decrypt(nonce, ciphertext, _aad(profile_id, provider))
    except Exception as exc:  # InvalidTag 等：tag 不符或 AAD 不匹配
        raise SealError("seal_invalid", "sealed blob failed authentication") from exc
    return plain.decode("utf-8")


def seal_map(ctx, credentials, profile_id="", provider=""):
    """整包凭证逐个密封；返回新字典，不改动入参。"""
    out = {}
    for key, value in (credentials or {}).items():
        out[str(key)] = seal(ctx, value, profile_id, provider)
    return out


def open_map(ctx, sealed, profile_id="", provider=""):
    """整包密封凭证逐个解封；返回明文字典（仅内存使用，勿回写、勿进视图）。"""
    out = {}
    for key, value in (sealed or {}).items():
        out[str(key)] = open_sealed(ctx, value, profile_id, provider)
    return out


# ---------------------------------------------------------------- 脱敏

def mask(_value):
    """统一脱敏：任何凭证值进日志/消息/视图前替换为占位符。"""
    return REDACTED


def mask_map(credentials):
    """整包凭证脱敏：键保留，值一律占位；不回显密封串或明文。"""
    return {str(k): REDACTED for k in (credentials or {}).keys()}
