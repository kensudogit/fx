"""暗号化ユーティリティのテスト"""

import pytest

try:
    from src.auth.secrets import decrypt_secret, encrypt_secret
except ImportError as exc:
    pytest.skip(f"依存関係不足: {exc}", allow_module_level=True)


class TestSecrets:
    """src.auth.secrets モジュールのテストクラス"""

    def test_encrypt_decrypt_roundtrip(self):
        raw = "test-oanda-token-12345"
        enc = encrypt_secret(raw)
        assert enc.startswith("enc:") or enc == raw
        assert decrypt_secret(enc) == raw

    def test_decrypt_plain_legacy(self):
        assert decrypt_secret("plain-token") == "plain-token"
