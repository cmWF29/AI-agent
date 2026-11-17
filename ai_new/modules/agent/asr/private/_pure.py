"""ASR 纯函数：入参校验与结果成形。不碰盘、不取时钟、不加载模型。"""
from __future__ import annotations


def validate(p):
    """校验音频字节非空。音频解码与识别在引擎层，这里只守住空输入。"""
    audio = p.get("audio")
    if not audio:
        return {"ok": False, "code": "empty_audio", "status": 400,
                "error": "音频为空，请先录音"}
    return {"ok": True}


def present(p):
    """识别文本成形：空文本报未听清，否则返正文与字数。分支在模块内部。"""
    text = str(p.get("text") or "").strip()
    if not text:
        return {"ok": False, "code": "empty_transcript", "status": 422,
                "error": "未识别到语音内容，请再录一次"}
    return {"ok": True, "text": text, "chars": len(text)}
