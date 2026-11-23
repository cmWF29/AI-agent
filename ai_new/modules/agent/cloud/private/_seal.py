"""凭证封装层（seal/open）。

当前实现是 **可逆混淆（obfuscation）**，不是对称加密：标准库没有 AES 原语，
接入 ``cryptography`` 后的 AES-GCM 方案列为待改（见报告「凭证加密方案」）。

约束：
- 主密钥只从环境变量 ``AI_NEW_CLOUD_MASTER_KEY`` 读，不进仓库、不进配置文件、不打印；
- 落盘的是密封串；明文只在连接时在内存中解封，用完不回写；
- 任何对外视图（列表/详情/状态/错误信息）都不得带出密封串或明文。
"""
from __future__ import annotations

MASTER_KEY_ENV = "AI_NEW_CLOUD_MASTER_KEY"
_PREFIX = "obf1"


class SealError(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def _master(ctx):
    row = ctx.api.call("host.env", {"name": MASTER_KEY_ENV}, caller=None)
    value = row.get("value") if isinstance(row, dict) else None
    if not value:
        raise SealError("master_key_missing", "master key env missing")
    return str(value)


def _keystream(ctx, master, nonce, length):
    """由主密钥 + nonce 派生重复密钥流（混淆用，不具密码学强度）。"""
    stream = []
    counter = 0
    while len(stream) < length:
        digest = ctx.api.call("codec.digest", {
            "text": master + ":" + nonce + ":" + str(counter),
            "algorithm": "sha256"}, caller=None)
        hexv = digest.get("hex") if isinstance(digest, dict) else ""
        stream.extend(hexv)
        counter += 1
    return stream[:length]


def is_sealed(value):
    return isinstance(value, str) and value.startswith(_PREFIX + ":")


def seal(ctx, secret):
    """明文 → 密封串。secret 必须是非空字符串。

    不做 base64 往返：密文体直接按字符异或后随 nonce 落盘；编码位待 AES-GCM 接入后补齐。
    """
    text = str(secret or "")
    if not text:
        raise SealError("empty_secret", "secret is empty")
    master = _master(ctx)
    nonce_row = ctx.api.call("codec.nonce", {"length": 16}, caller=None)
    nonce = nonce_row.get("token") if isinstance(nonce_row, dict) else ""
    stream = _keystream(ctx, master, nonce, len(text))
    body = "".join(chr(ord(c) ^ ord(k)) for c, k in zip(text, stream))
    return _PREFIX + ":" + nonce + ":" + body


def open_sealed(ctx, sealed):
    """密封串 → 明文；格式不符或解封失败抛 SealError。"""
    if not is_sealed(sealed):
        raise SealError("not_sealed", "value is not a sealed blob")
    _, nonce, body = sealed.split(":", 2)
    master = _master(ctx)
    stream = _keystream(ctx, master, nonce, len(body))
    return "".join(chr(ord(c) ^ ord(k)) for c, k in zip(body, stream))


def seal_map(ctx, credentials):
    """整包凭证逐个密封；返回新字典。"""
    out = {}
    for key, value in (credentials or {}).items():
        out[key] = seal(ctx, value)
    return out


def open_map(ctx, sealed):
    """整包密封凭证逐个解封；返回明文字典（仅内存使用，勿回写）。"""
    out = {}
    for key, value in (sealed or {}).items():
        out[key] = open_sealed(ctx, value)
    return out
