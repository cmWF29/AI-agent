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


def _msg_tpl(ctx):
    """消息模板表：语音模块自己的 data，读不到就退化成空。"""
    row = ctx.api.call("store.read", {
        "module": "agent/asr", "path": "messages.yaml"}, caller=None)
    return row.get("value") or {}


def _route_transcribe(ctx, payload):
    tpl = _msg_tpl(ctx)
    audio = payload.get("audio")
    check = ctx.api.call("asr.validate", {"audio": audio, "tpl": tpl}, caller=None)
    if not check.get("ok"):
        return check
    heard = _engine.transcribe(ctx, audio)
    if not heard.get("ok"):
        return heard
    return ctx.api.call("asr.present", {"text": heard.get("text"), "tpl": tpl}, caller=None)
