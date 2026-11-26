"""cloud 纯计算/封装/rsync/守卫与 ASR 识别残余分支。

覆盖面：profile 校验的四类拒绝、项目同步视图两种结局、密钥文件生成的失败清理、
信封 base64 失败、带端口主机判定、rsync 无校验和参数、本地树同步异常与删除传播、
识别器返回空结果（空分片、空收尾）。
"""
from __future__ import annotations

import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).parent))

from ai_new.modules.agent.cloud.private import _guard, _pure, _rsync, _seal  # noqa: E402


# ---------------------------------------------------------------- 信封假 ctx

class _SealApi:
    """codec/host 接缝替身：按调用名回固定形状，可注入失败。"""

    def __init__(self, encode_fail=False):
        self.encode_fail = encode_fail
        self.calls = []

    def call(self, name, payload=None, caller=None):
        self.calls.append(name)
        if name == "host.env":
            return {"value": "AAAA"}
        if name == "codec.base64_encode":
            return {"ok": False} if self.encode_fail else {"ok": True, "text": "MEK"}
        if name == "codec.base64_decode_bytes":
            return {"ok": True, "data": b"A" * 32}
        if name in ("codec.nonce",):
            return {"token": "tok"}
        if name == "codec.digest":
            return {"hex": "ab" * 64}
        return {"ok": True}


class _SealCtx:
    def __init__(self, api=None):
        self.api = api or _SealApi()


class SealResidualTest(unittest.TestCase):
    def test_seal_b64_encode_failure(self):
        """信封成形阶段 base64 失败：显式报错，不吞成空串。"""
        ctx = _SealCtx(_SealApi(encode_fail=True))
        with self.assertRaises(_seal.SealError) as info:
            _seal.seal(ctx, "secret")
        self.assertEqual(info.exception.code, "seal_invalid")
        self.assertIn("base64 encode failed", str(info.exception))

    def test_generate_key_file_write_failure_cleans_tmp(self):
        """密钥落盘中途异常：临时文件被清掉，异常原样上抛。"""
        tmpdir = tempfile.TemporaryDirectory()
        path = os.path.join(tmpdir.name, "sub", "master.key")
        ctx = _SealCtx()
        try:
            with mock.patch.object(_seal.os, "fdopen", side_effect=RuntimeError("disk full")):
                with self.assertRaises(RuntimeError):
                    _seal._generate_key_file(ctx, path)
            self.assertEqual([n for n in os.listdir(os.path.dirname(path))], [])
        finally:
            tmpdir.cleanup()

    def test_generate_key_file_replace_failure_without_tmp(self):
        """改名阶段先丢临时文件再失败：清理分支按“不存在”走，异常仍上抛。"""
        tmpdir = tempfile.TemporaryDirectory()
        path = os.path.join(tmpdir.name, "master.key")
        ctx = _SealCtx()

        def boom(src, dst):
            os.unlink(src)
            raise RuntimeError("replace failed")

        try:
            with mock.patch.object(_seal.os, "replace", side_effect=boom):
                with self.assertRaises(RuntimeError):
                    _seal._generate_key_file(ctx, path)
            self.assertFalse(os.path.exists(path))
        finally:
            tmpdir.cleanup()

    def test_generate_key_file_oserror_mapped(self):
        """目录建不出来：OSError 归一成 master_key_missing 稳定错误码。"""
        ctx = _SealCtx()
        with mock.patch.object(_seal.os, "makedirs", side_effect=OSError("denied")):
            with self.assertRaises(_seal.SealError) as info:
                _seal._generate_key_file(ctx, "/nowhere/master.key")
        self.assertEqual(info.exception.code, "master_key_missing")


# ---------------------------------------------------------------- profile 校验

CFG = {"schemes": ("https",), "allowed_hosts": []}


def _payload(**over):
    base = {
        "id": "p1",
        "company": "acme",
        "provider": "s3",
        "endpoint": "https://s3.example.com/bucket",
        "root_dir": "cloud/root",
        "credentials": {"access": "a", "secret": "b"},
        "categories": ["session"],
        "policy": {"conflict_policy": "record"},
    }
    base.update(over)
    return base


class ValidateProfileResidualTest(unittest.TestCase):
    def test_bad_provider(self):
        out = _pure.validate_profile(_payload(provider="ghost"), CFG)
        self.assertFalse(out["ok"])
        self.assertIn("bad_provider", out["errors"])

    def test_unknown_category(self):
        out = _pure.validate_profile(_payload(categories=["session", "ghost"]), CFG)
        self.assertIn("unknown_category", out["errors"])

    def test_bad_conflict_policy(self):
        out = _pure.validate_profile(_payload(policy={"conflict_policy": "merge"}), CFG)
        self.assertIn("bad_conflict_policy", out["errors"])

    def test_bad_root_dir(self):
        """root_dir 含穿越段：委托 key 校验拒绝，不再靠前缀判断。"""
        out = _pure.validate_profile(_payload(root_dir="a/../b"), CFG)
        self.assertIn("bad_root_dir", out["errors"])

    def test_valid_profile_passes(self):
        out = _pure.validate_profile(_payload(), CFG)
        self.assertTrue(out["ok"])
        self.assertEqual(out["profile"]["state_dir"], "cloud/profiles/p1")

    def test_project_sync_view_included_and_excluded(self):
        state = {"active": "p1", "profiles": {
            "p1": {"exclude_projects": ["proj-x"]}}}
        self.assertEqual(_pure.project_sync_view(state, "proj-y"),
                         {"project": "proj-y", "included": True, "reason": ""})
        self.assertEqual(_pure.project_sync_view(state, "proj-x")["reason"],
                         "excluded_by_profile")


# ---------------------------------------------------------------- 守卫带端口

class GuardPortResidualTest(unittest.TestCase):
    def test_host_with_port(self):
        """host:port 形式剥端口再判私网；公网域名的端口不误伤。"""
        self.assertTrue(_guard.host_is_blocked("10.0.0.1:8443"))
        self.assertFalse(_guard.host_is_blocked("example.com:8443"))


# ---------------------------------------------------------------- rsync 残余

class RsyncResidualTest(unittest.TestCase):
    def test_sync_without_checksum(self):
        """checksum=False 时命令行不带 --checksum，其余开关照旧。"""
        seen = {}

        class Proc:
            returncode = 0
            stdout = ""
            stderr = ""

        def run(argv, **kw):
            seen["argv"] = argv
            return Proc()

        with mock.patch.object(_rsync, "detect", return_value="/usr/bin/rsync"), \
                mock.patch.object(_rsync.subprocess, "run", side_effect=run):
            out = _rsync.sync("src", "dst", checksum=False, delete=True)
        self.assertTrue(out["ok"])
        self.assertNotIn("--checksum", seen["argv"])
        self.assertIn("--delete", seen["argv"])

    def test_sync_tree_copy_failure(self):
        """复制阶段 OSError 归一成 rsync_error，带原始细节。"""
        tmpdir = tempfile.TemporaryDirectory()
        src = os.path.join(tmpdir.name, "a.txt")
        Path(src).write_text("x", encoding="utf-8")
        dst = os.path.join(tmpdir.name, "dst")
        try:
            with mock.patch.object(_rsync.shutil, "copy2",
                                   side_effect=OSError("copy denied")):
                out = _rsync._sync_tree(src, dst)
            self.assertFalse(out["ok"])
            self.assertEqual(out["code"], "rsync_error")
            self.assertIn("copy denied", out["detail"])
        finally:
            tmpdir.cleanup()

    def test_sync_tree_delete_propagates(self):
        """delete=True 且源为目录内容形式：目标侧多出的文件与子目录一并删掉。"""
        tmpdir = tempfile.TemporaryDirectory()
        src = os.path.join(tmpdir.name, "src")
        dst = os.path.join(tmpdir.name, "dst")
        os.makedirs(src)
        os.makedirs(os.path.join(dst, "extra_dir"))
        Path(os.path.join(src, "keep.txt")).write_text("k", encoding="utf-8")
        Path(os.path.join(dst, "keep.txt")).write_text("old", encoding="utf-8")
        Path(os.path.join(dst, "stale.txt")).write_text("s", encoding="utf-8")
        Path(os.path.join(dst, "extra_dir", "x.txt")).write_text("x", encoding="utf-8")
        try:
            out = _rsync._sync_tree(src + "/", dst, delete=True)
            self.assertTrue(out["ok"])
            self.assertFalse(os.path.exists(os.path.join(dst, "stale.txt")))
            self.assertFalse(os.path.exists(os.path.join(dst, "extra_dir")))
            self.assertTrue(os.path.exists(os.path.join(dst, "keep.txt")))
        finally:
            tmpdir.cleanup()


# ---------------------------------------------------------------- ASR 空结果

class AsrEmptyResultResidualTest(unittest.TestCase):
    def setUp(self):
        from ai_new.modules.agent.asr.private import _engine
        self.engine = _engine
        _engine._MODEL_CACHE.clear()

    def tearDown(self):
        self.engine._MODEL_CACHE.clear()

    def test_transcribe_empty_parts(self):
        """识别器分片与收尾都返回空文本：结果为空串而不是拼出空洞。"""
        from ai_new.modules.agent_test.private.test_asr import _Ctx, _Own

        class Rec:
            def __init__(self, model, rate):
                self.rate = rate

            def SetWords(self, _flag):
                return None

            def AcceptWaveform(self, _block):
                return True

            def Result(self):
                return '{"text": ""}'

            def FinalResult(self):
                return '{"text": ""}'

        mod = types.SimpleNamespace(Model=lambda _p: object(), KaldiRecognizer=Rec)
        ctx = _Ctx(_Own(entries=["model.bin"]), {
            "codec.wave_decode": {"ok": True, "pcm": b"\x00\x01", "rate": 8000},
            "config.get": {"value": 1},
            "codec.json_decode": lambda p: {"ok": True, "value": {"text": ""}},
        })
        with mock.patch.dict(sys.modules, {"vosk": mod}):
            out = self.engine.transcribe(ctx, b"wav")
        self.assertTrue(out["ok"])
        self.assertEqual(out["text"], "")


if __name__ == "__main__":
    unittest.main()
