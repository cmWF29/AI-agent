"""凭证加密专项：AES-256-GCM v1 信封、密钥来源、AAD 绑定、脱敏不泄漏、旧格式拒绝。

不连外网；主密钥经环境变量/临时密钥文件注入。兼容 cryptography 2.8 可用的 AESGCM 原语。
"""
import base64
import os
import shutil
import stat
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).parent))

from ai_new.modules.agent_common.boot.private._boot import _build as build  # noqa: E402
from ai_new.modules.agent_common.boot.private._context import Context  # noqa: E402
from _fixtures import stage, write_config  # noqa: E402

from ai_new.modules.agent.cloud.private import _seal  # noqa: E402

KEY_A = base64.b64encode(b"A" * 32).decode()
KEY_B = base64.b64encode(b"B" * 32).decode()


def _make_ctx(root):
    stage(root)
    write_config(root, {
        "server": {"host": "127.0.0.1", "port": 0, "token": "t"},
        "llm": {"base_url": "http://stub.local/v1", "api_key": "k", "model": "stub"},
        "tickets": {"stall_check": {"enabled": False}},
        "cloud": {"allowed_hosts": []},
    })
    ctx = Context(root)
    build(ctx)
    return ctx


class SealTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        os.environ["AI_NEW_DATA"] = str(self.root)
        os.environ["AI_NEW_SECRET_KEY"] = KEY_A
        os.environ["AI_NEW_SECRET_KEY_FILE"] = str(self.root / "missing.key")
        self.ctx = _make_ctx(self.root)

    def tearDown(self):
        os.environ.pop("AI_NEW_DATA", None)
        os.environ.pop("AI_NEW_SECRET_KEY", None)
        os.environ.pop("AI_NEW_SECRET_KEY_FILE", None)
        shutil.rmtree(self.root, ignore_errors=True)

    # ---- 信封格式与往返 ----

    def test_envelope_roundtrip_and_nonce_random(self):
        secret = "tok-roundtrip-001"
        s1 = _seal.seal(self.ctx, secret, "p-a", "stub")
        s2 = _seal.seal(self.ctx, secret, "p-a", "stub")
        self.assertTrue(s1.startswith("v1:"))
        self.assertNotEqual(s1, s2)  # 随机 nonce：同一明文两次密封串不同
        self.assertEqual(_seal.open_sealed(self.ctx, s1, "p-a", "stub"), secret)
        self.assertEqual(_seal.open_sealed(self.ctx, s2, "p-a", "stub"), secret)
        # 密文信封不含明文。
        self.assertNotIn(secret, s1)
        self.assertNotIn(secret, s2)

    def test_aad_binds_profile_and_provider(self):
        secret = "tok-aad-binding"
        blob = _seal.seal(self.ctx, secret, "p-a", "stub")
        # 正确上下文解封成功。
        self.assertEqual(_seal.open_sealed(self.ctx, blob, "p-a", "stub"), secret)
        # 换 profile 解封：AAD 不匹配 → 校验失败。
        with self.assertRaises(_seal.SealError) as cm:
            _seal.open_sealed(self.ctx, blob, "p-b", "stub")
        self.assertEqual(cm.exception.code, "seal_invalid")
        # 换 provider 解封：同样失败。
        with self.assertRaises(_seal.SealError) as cm2:
            _seal.open_sealed(self.ctx, blob, "p-a", "webdav")
        self.assertEqual(cm2.exception.code, "seal_invalid")

    def test_wrong_master_key_fails_authentication(self):
        secret = "tok-wrong-key"
        blob = _seal.seal(self.ctx, secret, "p-a", "stub")
        os.environ["AI_NEW_SECRET_KEY"] = KEY_B
        with self.assertRaises(_seal.SealError) as cm:
            _seal.open_sealed(self.ctx, blob, "p-a", "stub")
        self.assertEqual(cm.exception.code, "seal_invalid")

    def test_invalid_key_rejected_no_plaintext_fallback(self):
        # 非 base64 → 显式报错，不回落明文。
        os.environ["AI_NEW_SECRET_KEY"] = "!!!not-base64!!!"
        with self.assertRaises(_seal.SealError) as cm1:
            _seal.seal(self.ctx, "x", "p-a", "stub")
        self.assertEqual(cm1.exception.code, "master_key_invalid")
        # 解码后长度不是 32 字节 → 报错。
        os.environ["AI_NEW_SECRET_KEY"] = base64.b64encode(b"short").decode()
        with self.assertRaises(_seal.SealError) as cm2:
            _seal.seal(self.ctx, "x", "p-a", "stub")
        self.assertEqual(cm2.exception.code, "master_key_invalid")

    def test_mask_helpers_expose_neither_key_nor_plaintext(self):
        secret = "tok-mask-leak"
        blob = _seal.seal(self.ctx, secret, "p-a", "stub")
        masked_map = _seal.mask_map({"access_key": blob, "token": secret})
        rendered = str(masked_map)
        self.assertNotIn(secret, rendered)
        self.assertNotIn(KEY_A, rendered)
        self.assertNotIn("v1:", rendered)
        self.assertEqual(_seal.mask(secret), _seal.REDACTED)

    def test_key_file_generated_with_0600_when_missing(self):
        os.environ.pop("AI_NEW_SECRET_KEY")
        key_file = self.root / "nested" / "secrets.key"
        os.environ["AI_NEW_SECRET_KEY_FILE"] = str(key_file)
        self.assertFalse(key_file.exists())
        blob = _seal.seal(self.ctx, "tok-file-key", "p-a", "stub")
        self.assertTrue(key_file.exists())
        if os.name != "nt":
            mode = stat.S_IMODE(key_file.stat().st_mode)
            self.assertEqual(mode, 0o600)
        else:
            # Windows 不暴露 POSIX mode；密钥文件必须真实落盘且可被同一服务读回。
            self.assertTrue(key_file.is_file())
        # 再次加载同一文件密钥可解封。
        self.assertEqual(_seal.open_sealed(self.ctx, blob, "p-a", "stub"),
                         "tok-file-key")

    def test_old_obfuscation_blob_rejected(self):
        with self.assertRaises(_seal.SealError) as cm:
            _seal.open_sealed(self.ctx, "obf1:abc:def", "p-a", "stub")
        self.assertEqual(cm.exception.code, "not_sealed")

    def test_empty_secret_rejected(self):
        with self.assertRaises(_seal.SealError) as cm:
            _seal.seal(self.ctx, "", "p-a", "stub")
        self.assertEqual(cm.exception.code, "empty_secret")

    def test_seal_map_open_map_roundtrip(self):
        creds = {"access_key": "ak-1", "secret_key": "sk-2", "token": "tok-3"}
        sealed = _seal.seal_map(self.ctx, creds, "p-a", "stub")
        self.assertEqual(set(sealed.keys()), set(creds.keys()))
        opened = _seal.open_map(self.ctx, sealed, "p-a", "stub")
        self.assertEqual(opened, creds)


if __name__ == "__main__":
    unittest.main(verbosity=2)
