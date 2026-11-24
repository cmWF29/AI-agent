"""ASR 引擎适配：懒加载离线小模型，把 WAV(PCM) 识别成文本。

引擎细节（模型路径、第三方库、识别器）只留在本层；路由与需求只拿文本结果。
模型包不进 git，部署时下载到 models/cn；未装包或未装模型时返明确错误，
不阻塞服务启动。读盘归 store，编解码归 codec，本层只持有本地模型调用。
"""
from __future__ import annotations

_MODEL_CACHE = {}


def _model_dir(ctx):
    """本模块 data/models/cn 目录（数据跟着模块走）。"""
    own = ctx.storage.own(__file__)
    return own.root / "models" / "cn"


def _load_model(ctx):
    """懒加载并缓存 vosk 模型；缺包/缺模型返结构化错误，不抛到路由外。"""
    if "model" in _MODEL_CACHE:
        return _MODEL_CACHE["model"], None
    own = ctx.storage.own(__file__)
    if not own.is_dir("models/cn") or not own.list_dir("models/cn"):
        return None, {"ok": False, "code": "model_missing", "status": 503,
                      "error": "语音模型未部署：请下载中文小模型到 models/cn 目录"}
    try:
        from vosk import Model  # 延迟导入：未装包时不影响服务启动
    except ImportError as exc:
        return None, {"ok": False, "code": "engine_unavailable", "status": 503,
                      "error": "语音识别引擎未安装：%s" % exc}
    try:
        model = Model(str(_model_dir(ctx)))
    except Exception as exc:  # 模型损坏/加载失败：明确报错，不崩进程
        return None, {"ok": False, "code": "model_load_failed", "status": 503,
                      "error": "语音模型加载失败：%s" % exc}
    _MODEL_CACHE["model"] = model
    return model, None


def _decode_json(ctx, raw):
    """识别器结果是 JSON 文本，解析归 codec。"""
    parsed = ctx.api.call("codec.json_decode", {"text": raw}, caller=None)
    if not parsed.get("ok"):
        return {}
    return parsed.get("value") or {}


def chunk_size(raw):
    """识别器每次喂入的采样点数：必须是正整数，否则明确失败而不是死循环。

    配置缺失或填 0 时，``pcm[:0]`` 永远不前进，``while pcm`` 会挂死请求线程。
    这里把非法值收口成结构化错误，由 transcribe 直接返回 503。
    """
    try:
        step = int(raw)
    except (TypeError, ValueError):
        step = 0
    if step <= 0:
        return 0, {"ok": False, "code": "bad_chunk_config", "status": 503}
    return step, None


def transcribe(ctx, audio):
    """WAV(PCM) 字节 → 识别文本。返回 {ok, text} 或结构化错误。"""
    model, err = _load_model(ctx)
    if err:
        return err
    wav = ctx.api.call("codec.wave_decode", {"raw": audio}, caller=None)
    if not wav.get("ok"):
        return {"ok": False, "code": wav.get("code") or "bad_audio", "status": 400,
                "error": wav.get("error") or "音频解析失败"}
    pcm = wav.get("pcm")
    rate = wav.get("rate")
    step, step_err = chunk_size(ctx.api.call("config.get", {
        "key": "asr.chunk_shorts"}, caller=None).get("value"))
    if step_err:
        tpl = ctx.api.call("store.read", {
            "module": "agent/asr", "path": "messages.yaml"}, caller=None)
        step_err["error"] = (tpl.get("value") or {}).get("bad_chunk_config") or ""
        return step_err
    try:
        from vosk import KaldiRecognizer
    except ImportError as exc:
        return {"ok": False, "code": "engine_unavailable", "status": 503,
                "error": "语音识别引擎未安装：%s" % exc}
    rec = KaldiRecognizer(model, rate)
    rec.SetWords(False)
    chunks = []
    while pcm:
        block, pcm = pcm[:step], pcm[step:]
        if rec.AcceptWaveform(block):
            part = _decode_json(ctx, rec.Result()).get("text") or ""
            if part:
                chunks.append(part)
    tail = _decode_json(ctx, rec.FinalResult()).get("text") or ""
    if tail:
        chunks.append(tail)
    return {"ok": True, "text": " ".join(chunks).strip()}
