"""アプリケーション設定 — src.config のテスト"""

import pytest

from src.config import Settings, settings


class TestSettingsDefaults:
    """既定値のテスト。開発環境ではそのまま起動できることを保証する。"""

    def test_singleton_is_settings_instance(self):
        """モジュールレベルの settings は Settings のインスタンスであること"""
        assert isinstance(settings, Settings)

    def test_postgres_defaults(self):
        """PostgreSQL の既定値（docker-compose と同じポート 5433）"""
        s = Settings()
        assert s.postgres_host == "localhost"
        assert s.postgres_port == 5433
        assert s.postgres_db == "fx_db"

    def test_jwt_defaults(self):
        """JWT は HS256・72 時間（3 日）が既定であること"""
        s = Settings()
        assert s.jwt_algorithm == "HS256"
        assert s.jwt_expire_hours == 72

    def test_saas_defaults(self):
        """SaaS モードは既定で有効、新規テナントは free プラン"""
        s = Settings()
        assert s.saas_enabled is True
        assert s.saas_default_plan == "free"

    def test_optional_api_keys_default_to_empty(self):
        """外部 API キーは未設定（空文字）が既定で、未設定でも起動できること"""
        s = Settings()
        for field in ("openai_api_key", "fred_api_key", "finnhub_api_key",
                      "stripe_secret_key", "oanda_api_token", "redis_url"):
            assert getattr(s, field) == ""

    def test_ttl_values_are_positive(self):
        """各種キャッシュ TTL は正の秒数であること"""
        s = Settings()
        for field in ("analysis_cache_ttl_seconds", "mtf_cache_ttl_seconds",
                      "ml_model_ttl_seconds", "signal_context_cache_ttl_seconds",
                      "sns_cache_ttl_seconds"):
            assert getattr(s, field) > 0

    def test_extra_env_vars_are_ignored(self, monkeypatch):
        """定義外の環境変数があってもエラーにならないこと（extra=ignore）"""
        monkeypatch.setenv("SOME_UNRELATED_VARIABLE", "1")
        assert Settings() is not None


class TestGetDatabaseUrl:
    """get_database_url() のテスト。psycopg3 互換スキームへの正規化を検証する。"""

    def test_builds_url_from_individual_fields(self):
        """DATABASE_URL 未設定時は個別フィールドから組み立てること"""
        s = Settings(database_url="", postgres_user="u", postgres_password="p",
                     postgres_host="h", postgres_port=1234, postgres_db="d")
        assert s.get_database_url() == "postgresql+psycopg://u:p@h:1234/d"

    def test_database_url_takes_precedence(self):
        """DATABASE_URL が設定されていれば個別フィールドより優先されること"""
        s = Settings(database_url="postgresql://a:b@c:5432/e", postgres_host="ignored")
        assert "ignored" not in s.get_database_url()
        assert s.get_database_url() == "postgresql+psycopg://a:b@c:5432/e"

    def test_normalizes_heroku_postgres_scheme(self):
        """Heroku / Railway の postgres:// を psycopg3 スキームへ変換すること"""
        s = Settings(database_url="postgres://a:b@c:5432/e")
        assert s.get_database_url() == "postgresql+psycopg://a:b@c:5432/e"

    def test_keeps_explicit_psycopg_scheme_unchanged(self):
        """すでに psycopg3 スキームなら二重変換しないこと"""
        url = "postgresql+psycopg://a:b@c:5432/e"
        assert Settings(database_url=url).get_database_url() == url

    @pytest.mark.parametrize("url", [
        "postgres://user:pass@host:5432/db",
        "postgresql://user:pass@host:5432/db",
    ])
    def test_result_is_always_psycopg_scheme(self, url):
        """どの入力形式でも psycopg3 スキームで返ること"""
        assert Settings(database_url=url).get_database_url().startswith("postgresql+psycopg://")


class TestGetCorsOrigins:
    """get_cors_origins() のテスト。カンマ区切り文字列をリストへ分解する。"""

    def test_single_origin(self):
        """単一オリジンは 1 要素のリストになること"""
        s = Settings(cors_origins="http://localhost:3000")
        assert s.get_cors_origins() == ["http://localhost:3000"]

    def test_multiple_origins_are_split(self):
        """カンマ区切りの複数オリジンを分割すること"""
        s = Settings(cors_origins="http://a.com,http://b.com")
        assert s.get_cors_origins() == ["http://a.com", "http://b.com"]

    def test_whitespace_is_trimmed(self):
        """要素前後の空白を除去すること"""
        s = Settings(cors_origins=" http://a.com , http://b.com ")
        assert s.get_cors_origins() == ["http://a.com", "http://b.com"]

    def test_empty_entries_are_dropped(self):
        """空要素（連続カンマ・末尾カンマ）は除外すること"""
        s = Settings(cors_origins="http://a.com,,http://b.com,")
        assert s.get_cors_origins() == ["http://a.com", "http://b.com"]

    def test_empty_string_returns_empty_list(self):
        """空文字なら空リストを返すこと"""
        assert Settings(cors_origins="").get_cors_origins() == []
