"""暗号化ユーティリティのテスト"""

from src.auth.secrets import decrypt_secret, encrypt_secret


def test_encrypt_decrypt_roundtrip():
    raw = "test-oanda-token-12345"
    enc = encrypt_secret(raw)
    assert enc.startswith("enc:") or enc == raw
    assert decrypt_secret(enc) == raw


def test_decrypt_plain_legacy():
    assert decrypt_secret("plain-token") == "plain-token"
