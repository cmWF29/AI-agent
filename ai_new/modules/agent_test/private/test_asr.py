"""ASR 适配层：无模型/无引擎/坏配置/损坏音频/分块识别全部走结构化错误或真识别分支。"""
from __future__ import annotations

import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))

from ai_new.modules.agent.asr import _route_transcribe, setup  # noqa: E402
from ai_new.modules.agent.asr.private import _engine, _pure  # noqa: E402


class _Own:
    def __init__(self, directory=True, entries=None):
        self.directory = directory
        self.entries = entries or []
        self.root = Path("/tmp/asr-model")

    def is_dir(self, _rel):
        return self.directory

    def list_dir(self, _rel):
        return self.entries


class _Storage:
    def __init__(self, own):
        self._own = own

    def own(self, _file):
        return self._own


class _Ctx:
    """最小 ctx：storage 给模型目录，api.call 按路由回固定形状。"""

    def __init__(self, own=None, routes=None):
        self.storage = _Storage(own or _Own())
        self.routes = routes or {}

    @property
    def api(self):
        return self

    def call(self, name, payload=None, caller=None):
        value = self.routes.get(name)
        if callable(value):
            return value(payload or {})
        return value if value is not None else {"ok": True}


class AsrEngineTest(unittest.TestCase):
    def setUp(self):
        _engine._MODEL_CACHE.clear()

    def tearDown(self):
        _engine._MODEL_CACHE.clear()

    def test_chunk_size_guards(self):
        self.assertEqual(_engine.chunk_size("4000"), (4000, None))
        for bad in (None, "", "x", 0, -1):
            step, err = _engine.chunk_size(bad)
            self.assertEqual(step, 0)
            self.assertEqual(err["code"], "bad_chunk_config")

    def test_model_missing(self):
        model, err = _engine._load_model(_Ctx(_Own(directory=True, entries=[])))
        self.assertIsNone(model)
        self.assertEqual(err["code"], "model_missing")

    def test_engine_import_error(self):
        own = _Own(entries=["model.bin"])
        with patch.dict(sys.modules, {"vosk": None}):
            model, err = _engine._load_model(_Ctx(own))
        self.assertIsNone(model)
        self.assertEqual(err["code"], "engine_unavailable")

    def test_model_load_failed(self):
        own = _Own(entries=["model.bin"])
        mod = types.SimpleNamespace(Model=lambda _p: (_ for _ in ()).throw(RuntimeError("bad")))
        with patch.dict(sys.modules, {"vosk": mod}):
            model, err = _engine._load_model(_Ctx(own))
        self.assertIsNone(model)
        self.assertEqual(err["code"], "model_load_failed")

    def test_model_cache_hit(self):
        own = _Own(entries=["model.bin"])
        mod = types.SimpleNamespace(Model=lambda _p: object())
        with patch.dict(sys.modules, {"vosk": mod}):
            first, err = _engine._load_model(_Ctx(own))
            second, err2 = _engine._load_model(_Ctx(_Own(directory=False)))
        self.assertIsNone(err)
        self.assertIsNone(err2)
        self.assertIs(first, second)

    def test_transcribe_model_error_passthrough(self):
        out = _engine.transcribe(_Ctx(_Own(entries=[])), b"wav")
        self.assertEqual(out["code"], "model_missing")

    def test_transcribe_bad_audio(self):
        own = _Own(entries=["model.bin"])
        mod = types.SimpleNamespace(Model=lambda _p: object())
        ctx = _Ctx(own, {"codec.wave_decode": {"ok": False, "code": "bad_wave"}})
        with patch.dict(sys.modules, {"vosk": mod}):
            out = _engine.transcribe(ctx, b"wav")
        self.assertEqual(out["code"], "bad_wave")

    def test_transcribe_bad_chunk_config(self):
        own = _Own(entries=["model.bin"])
        mod = types.SimpleNamespace(Model=lambda _p: object())
        def api(payload):
            return {"value": 0}
        ctx = _Ctx(own, {"codec.wave_decode": {"ok": True, "pcm": b"\x00", "rate": 8000},
                         "config.get": api,
                         "store.read": {"value": {"bad_chunk_config": "分块配置错误"}}})
        with patch.dict(sys.modules, {"vosk": mod}):
            out = _engine.transcribe(ctx, b"wav")
        self.assertEqual(out["code"], "bad_chunk_config")
        self.assertEqual(out["error"], "分块配置错误")

    def test_transcribe_recognizer_import_error(self):
        own = _Own(entries=["model.bin"])
        mod = types.SimpleNamespace(Model=lambda _p: object())
        ctx = _Ctx(own, {"codec.wave_decode": {"ok": True, "pcm": b"\x00", "rate": 8000},
                         "config.get": {"value": 2}})
        with patch.dict(sys.modules, {"vosk": mod}):
            out = _engine.transcribe(ctx, b"wav")
        self.assertEqual(out["code"], "engine_unavailable")

    def test_transcribe_chunks_tail_and_decode_failure(self):
        own = _Own(entries=["model.bin"])
        calls = {"n": 0}
        class Rec:
            def __init__(self, model, rate):
                self.rate = rate
            def SetWords(self, _flag):
                return None
            def AcceptWaveform(self, _block):
                calls["n"] += 1
                return calls["n"] == 1
            def Result(self):
                return '{"text": "前半"}'
            def FinalResult(self):
                return '{"text": "收尾"}'
        mod = types.SimpleNamespace(Model=lambda _p: object(), KaldiRecognizer=Rec)
        def decode(payload):
            text = payload.get("text") or ""
            if "bad" in text:
                return {"ok": False}
            return {"ok": True, "value": {"text": text and text.split('"')[3]}}
        ctx = _Ctx(own, {"codec.wave_decode": {"ok": True, "pcm": b"\x00\x01\x02", "rate": 8000},
                         "config.get": {"value": 2},
                         "codec.json_decode": decode})
        with patch.dict(sys.modules, {"vosk": mod}):
            out = _engine.transcribe(ctx, b"wav")
        self.assertTrue(out["ok"])
        self.assertEqual(out["text"], "前半 收尾")

    def test_route_transcribe_invalid_then_present(self):
        """路由：坏音频直接回校验错误；好音频走识别并把文本交给 present。"""
        ctx = _Ctx(routes={
            "asr.validate": lambda p: ({"ok": False, "code": "bad_audio", "status": 400}
                                       if not p.get("audio") else {"ok": True}),
            "store.read": {"value": {}},
            "asr.present": lambda p: {"ok": True, "text": (p.get("text") or "").strip()},
        })
        self.assertEqual(_route_transcribe(ctx, {"audio": b""})["code"], "bad_audio")
        with patch.object(_engine, "transcribe", return_value={"ok": True, "text": " 你好 "}):
            out = _route_transcribe(ctx, {"audio": b"wav"})
        self.assertEqual(out["text"], "你好")

    def test_setup_and_route_failure_and_pure_empty(self):
        """装配登记、识别失败透出、空音频/空文本校验。"""
        class Api:
            def __init__(self):
                self.rows = []

            def register(self, name, fn, *a, **k):
                self.rows.append((name, fn))

        api = Api()
        self.assertTrue(setup(types.SimpleNamespace(api=api)))
        self.assertEqual([r[0] for r in api.rows],
                         ["asr.validate", "asr.present", "asr.transcribe"])
        ctx = _Ctx(routes={"asr.validate": {"ok": True},
                           "store.read": {"value": {}}})
        with patch.object(_engine, "transcribe",
                          return_value={"ok": False, "code": "asr_failed"}):
            self.assertEqual(_route_transcribe(ctx, {"audio": b"wav"})["code"], "asr_failed")
        self.assertEqual(_pure.validate({"audio": b"", "tpl": {"empty_audio": "空"}})["code"],
                         "empty_audio")
        self.assertEqual(_pure.present({"text": "  ", "tpl": {"empty_transcript": "空"}})["code"],
                         "empty_transcript")
        self.assertTrue(_pure.validate({"audio": b"x"})["ok"])
        self.assertTrue(_pure.present({"text": " a "})["text"], "a")

    def test_decode_json_bad_json(self):
        ctx = _Ctx(routes={"codec.json_decode": {"ok": False}})
        self.assertEqual(_engine._decode_json(ctx, "x"), {})


if __name__ == "__main__":
    unittest.main()
