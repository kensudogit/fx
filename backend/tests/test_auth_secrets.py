"""機密値の暗号化 — src.auth.secrets のテスト"""

import base64
import hashlib

import pytest
from cryptography.fernet import Fernet

from src.auth.secrets import _fernet, decrypt_secret, encrypt_secret

# config の既定値。この値のままだと暗号化は無効になる仕様。
PLACEHOLDER_SECRET = "change-me-in-production-use-long-random-string"
STRONG_SECRET = "a-long-random-production-secret-value-0123456789"


@pytest.fixture
def encryption_enabled(override_settings):
    """jwt_secret を本番相当の値にして暗号化を有効にする。"""
    override_settings(jwt_secret=STRONG_SECRET)


@pytest.fixture
def encryption_disabled(override_settings):
    """jwt_secret を既定のプレースホルダに戻して暗号化を無効にする。"""
    override_settings(jwt_secret=PLACEHOLDER_SECRET)


class TestFernetDerivation:
    """_fernet() による鍵導出のテスト"""

    def test_returns_none_for_placeholder_secret(self, encryption_disabled):
        """既定のプレースホルダでは鍵を作らないこと（設定漏れの検知）"""
        assert _fernet() is None

    def test_returns_none_for_empty_secret(self, override_settings):
        """空文字・空白のみでも鍵を作らないこと"""
        override_settings(jwt_secret="   ")
        assert _fernet() is None

    def test_returns_fernet_for_strong_secret(self, encryption_enabled):
        """十分な秘密鍵があれば Fernet を返すこと"""
        assert isinstance(_fernet(), Fernet)

    def test_key_is_sha256_of_secret(self, encryption_enabled):
        """鍵は jwt_secret の SHA-256 から導出されること"""
        expected = Fernet(base64.urlsafe_b64encode(hashlib.sha256(STRONG_SECRET.encode()).digest()))
        # 同じ鍵なら、片方で暗号化した値をもう片方で復号できる
        assert expected.decrypt(_fernet().encrypt(b"hello")) == b"hello"


class TestEncryptSecret:
    """encrypt_secret() のテスト"""

    def test_output_is_marked_with_prefix(self, encryption_enabled):
        """暗号化済みの値は enc: プレフィックスで識別できること"""
        assert encrypt_secret("oanda-token").startswith("enc:")

    def test_ciphertext_does_not_contain_plaintext(self, encryption_enabled):
        """暗号文に平文が現れないこと"""
        assert "oanda-token" not in encrypt_secret("oanda-token")

    def test_encryption_is_randomized(self, encryption_enabled):
        """同じ平文でも毎回異なる暗号文になること（Fernet は IV を含む）"""
        assert encrypt_secret("same") != encrypt_secret("same")

    def test_returns_plaintext_when_disabled(self, encryption_disabled):
        """jwt_secret 未設定時は平文のまま返すこと（開発環境向けの仕様）"""
        assert encrypt_secret("oanda-token") == "oanda-token"

    def test_unicode_value_is_supported(self, encryption_enabled):
        """マルチバイト文字も暗号化できること"""
        value = "トークン・秘密鍵"
        assert decrypt_secret(encrypt_secret(value)) == value


class TestDecryptSecret:
    """decrypt_secret() のテスト"""

    def test_roundtrip(self, encryption_enabled):
        """暗号化→復号で元の値に戻ること"""
        assert decrypt_secret(encrypt_secret("oanda-token")) == "oanda-token"

    def test_plaintext_passthrough_for_legacy_values(self, encryption_enabled):
        """enc: が付いていない値は平文とみなしてそのまま返すこと（後方互換）"""
        assert decrypt_secret("legacy-plain-token") == "legacy-plain-token"

    @pytest.mark.parametrize("empty", [None, ""])
    def test_empty_input_returns_none(self, empty, encryption_enabled):
        """None・空文字は None を返すこと"""
        assert decrypt_secret(empty) is None

    def test_tampered_ciphertext_returns_none(self, encryption_enabled):
        """改ざんされた暗号文は復号せず None を返すこと（Fernet の認証付き暗号）"""
        enc = encrypt_secret("oanda-token")
        tampered = enc[:-4] + "AAAA"
        assert decrypt_secret(tampered) is None

    def test_garbage_ciphertext_returns_none(self, encryption_enabled):
        """enc: 付きの不正な文字列でも例外を投げず None を返すこと"""
        assert decrypt_secret("enc:not-a-valid-fernet-token") is None

    def test_returns_none_when_key_rotated(self, override_settings):
        """jwt_secret を変更すると既存の暗号文は復号できなくなること"""
        override_settings(jwt_secret=STRONG_SECRET)
        enc = encrypt_secret("oanda-token")

        override_settings(jwt_secret="a-completely-different-production-secret-98765")
        assert decrypt_secret(enc) is None

    def test_returns_none_when_key_removed(self, override_settings):
        """暗号文はあるのに鍵が未設定になった場合は None を返すこと"""
        override_settings(jwt_secret=STRONG_SECRET)
        enc = encrypt_secret("oanda-token")

        override_settings(jwt_secret=PLACEHOLDER_SECRET)
        assert decrypt_secret(enc) is None

    def test_plaintext_still_readable_when_key_removed(self, encryption_disabled):
        """鍵が無くても平文フォールバックの値は読めること"""
        assert decrypt_secret("legacy-plain-token") == "legacy-plain-token"
