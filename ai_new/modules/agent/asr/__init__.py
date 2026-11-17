"""语音识别模块：离线小模型本地转写，只服务会话输入框。

校验与成形归纯函数，模型加载与识别归引擎层；需求树只做解码→识别→返文本。
"""
from __future__ import annotations

from .private import _pure, _engine


def setup(ctx):
    pairs = [
        ("asr.validate", _pure.validate),
        ("asr.present", _pure.present),
    ]
    for name, fn in pairs:
        ctx.api.register(name, lambda payload, fn=fn: fn(payload), module="asr")
    ctx.api.register("asr.transcribe", _route_transcribe,
                     "语音转写：校验音频 → 离线模型识别 → 文本成形", module="asr")
    return True


def _route_transcribe(ctx, payload):
    audio = payload.get("audio")
    check = ctx.api.call("asr.validate", {"audio": audio}, caller=None)
    if not check.get("ok"):
        return check
    heard = _engine.transcribe(ctx, audio)
    if not heard.get("ok"):
        return heard
    return ctx.api.call("asr.present", {"text": heard.get("text")}, caller=None)
