"""認証の暗号処理 — src.auth.security のテスト"""

import time
from datetime import datetime, timedelta, timezone

import jwt
import pytest

from src.auth.security import (
    API_KEY_PREFIX,
    api_key_prefix,
    create_access_token,
    decode_access_token,
    generate_api_key,
    hash_api_key,
    hash_password,
    verify_password,
)
from src.config import settings


class TestPasswordHashing:
    """bcrypt によるパスワードハッシュのテスト"""

    def test_hash_is_not_plaintext(self):
        """ハッシュは平文を含まないこと"""
        hashed = hash_password("s3cret-password")
        assert "s3cret-password" not in hashed

    def test_hash_uses_bcrypt_format(self):
        """bcrypt 形式（$2b$ 始まり）で返ること"""
        assert hash_password("password1").startswith("$2b$")

    def test_same_password_yields_different_hashes(self):
        """ソルトがランダムなため、同じパスワードでもハッシュは毎回異なること"""
        assert hash_password("password1") != hash_password("password1")

    def test_verify_accepts_correct_password(self):
        """正しいパスワードは検証を通ること"""
        assert verify_password("password1", hash_password("password1")) is True

    def test_verify_rejects_wrong_password(self):
        """誤ったパスワードは拒否されること"""
        assert verify_password("wrong", hash_password("password1")) is False

    def test_verify_rejects_malformed_hash(self):
        """ハッシュが壊れていても例外を投げず False を返すこと"""
        assert verify_password("password1", "not-a-bcrypt-hash") is False

    def test_verify_rejects_empty_hash(self):
        """空のハッシュでも例外を投げないこと"""
        assert verify_password("password1", "") is False

    def test_unicode_password_roundtrip(self):
        """日本語などマルチバイトのパスワードも扱えること"""
        pwd = "ぱすわーど・テスト"
        assert verify_password(pwd, hash_password(pwd)) is True

    def test_password_is_truncated_at_72_bytes(self):
        """bcrypt の 72 バイト制限に合わせて切り詰めていること

        72 バイトを超える部分は無視されるため、先頭 72 バイトが同じなら検証を通る。
        これは bcrypt 由来の既知の挙動であり、実装が明示的に [:72] している。
        """
        base = "a" * 72
        assert verify_password(base + "DIFFERENT", hash_password(base + "XXXXXXXXX")) is True


class TestAccessToken:
    """JWT アクセストークンの生成・検証テスト"""

    def test_token_is_a_string(self):
        """トークンは文字列で返ること（PyJWT のバージョン差を吸収している）"""
        assert isinstance(create_access_token(1, 2, "a@example.com", "owner"), str)

    def test_payload_contains_expected_claims(self):
        """sub / tenant_id / email / role を含むこと"""
        payload = decode_access_token(create_access_token(7, 42, "a@example.com", "owner"))
        assert payload["sub"] == "7"
        assert payload["tenant_id"] == 42
        assert payload["email"] == "a@example.com"
        assert payload["role"] == "owner"

    def test_sub_is_a_string_per_jwt_spec(self):
        """JWT 標準に従い sub は文字列であること"""
        payload = decode_access_token(create_access_token(7, 42, "a@example.com", "owner"))
        assert isinstance(payload["sub"], str)

    def test_expiry_matches_configured_hours(self, override_settings):
        """exp が設定値（jwt_expire_hours）どおりに設定されること"""
        override_settings(jwt_expire_hours=3)
        payload = decode_access_token(create_access_token(1, 1, "a@example.com", "owner"))
        delta = datetime.fromtimestamp(payload["exp"], timezone.utc) - datetime.now(timezone.utc)
        assert timedelta(hours=2, minutes=55) < delta <= timedelta(hours=3)

    def test_issued_at_is_before_expiry(self):
        """iat < exp であること"""
        payload = decode_access_token(create_access_token(1, 1, "a@example.com", "owner"))
        assert payload["iat"] < payload["exp"]

    def test_decode_rejects_tampered_token(self):
        """署名が一致しない改ざんトークンは None を返すこと"""
        token = create_access_token(1, 1, "a@example.com", "owner")
        header, body, sig = token.split(".")
        tampered = f"{header}.{body}.{sig[:-2]}xx"
        assert decode_access_token(tampered) is None

    def test_decode_rejects_token_signed_with_other_secret(self):
        """別のシークレットで署名されたトークンを受け付けないこと"""
        forged = jwt.encode({"sub": "1", "tenant_id": 1}, "attacker-secret", algorithm="HS256")
        assert decode_access_token(forged) is None

    def test_decode_rejects_expired_token(self, override_settings):
        """有効期限切れのトークンは None を返すこと"""
        override_settings(jwt_expire_hours=-1)
        assert decode_access_token(create_access_token(1, 1, "a@example.com", "owner")) is None

    def test_decode_rejects_garbage(self):
        """JWT 形式ですらない文字列でも例外を投げず None を返すこと"""
        for bad in ("", "abc", "a.b.c", "....."):
            assert decode_access_token(bad) is None

    def test_decode_rejects_none_algorithm_attack(self):
        """alg=none による署名回避攻撃を拒否すること"""
        forged = jwt.encode({"sub": "1", "tenant_id": 1}, key="", algorithm="none")
        assert decode_access_token(forged) is None

    def test_token_uses_configured_algorithm(self):
        """設定されたアルゴリズム（既定 HS256）で署名されること"""
        token = create_access_token(1, 1, "a@example.com", "owner")
        assert jwt.get_unverified_header(token)["alg"] == settings.jwt_algorithm


class TestApiKeys:
    """API キーの生成・ハッシュ化・表示のテスト"""

    def test_generated_key_has_prefix(self):
        """生成されたキーは fx_ プレフィックスを持つこと"""
        assert generate_api_key().startswith(API_KEY_PREFIX)

    def test_generated_keys_are_unique(self):
        """CSPRNG を使うため、生成のたびに異なるキーになること"""
        keys = {generate_api_key() for _ in range(50)}
        assert len(keys) == 50

    def test_generated_key_has_sufficient_entropy(self):
        """32 バイト（256 ビット）相当の長さがあること"""
        assert len(generate_api_key()) >= len(API_KEY_PREFIX) + 40

    def test_hash_is_sha256_hex(self):
        """ハッシュは SHA-256 の 16 進 64 文字であること"""
        digest = hash_api_key("fx_example")
        assert len(digest) == 64
        assert all(c in "0123456789abcdef" for c in digest)

    def test_hash_is_deterministic(self):
        """同じキーからは常に同じハッシュが得られること（DB 照合に必要）"""
        assert hash_api_key("fx_example") == hash_api_key("fx_example")

    def test_different_keys_hash_differently(self):
        """異なるキーは異なるハッシュになること"""
        assert hash_api_key("fx_a") != hash_api_key("fx_b")

    def test_hash_does_not_contain_raw_key(self):
        """ハッシュから生のキーが読み取れないこと"""
        raw = generate_api_key()
        assert raw not in hash_api_key(raw)

    def test_prefix_truncates_long_keys(self):
        """12 文字を超えるキーは先頭 12 文字 + '...' にすること"""
        assert api_key_prefix("fx_abcdefghijklmnop") == "fx_abcdefghi..."

    def test_prefix_keeps_short_keys_intact(self):
        """12 文字以下のキーはそのまま返すこと"""
        assert api_key_prefix("fx_short") == "fx_short"

    def test_prefix_of_generated_key_hides_most_of_it(self):
        """生成キーの表示用プレフィックスは大半を隠すこと"""
        raw = generate_api_key()
        shown = api_key_prefix(raw)
        assert len(shown) < len(raw)
        assert raw not in shown
