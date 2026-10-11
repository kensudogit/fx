"""テナント別 OANDA 認証情報 — src.broker.tenant_oanda のテスト

DB はモックへ差し替え、トークンのマスク・暗号化保存・
本番モードへの誤接続を防ぐ安全策を検証する。
"""

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from src.broker.tenant_oanda import (
    OandaCredentials,
    TenantOandaSettings,
    _mask_token,
    get_tenant_oanda_settings,
    resolve_oanda_credentials,
    save_tenant_oanda_settings,
)


@pytest.fixture(autouse=True)
def no_table_init():
    """テーブル初期化を無効化する。"""
    with patch("src.broker.tenant_oanda._ensure_table"):
        yield


def settings_row(**kwargs):
    """TenantOandaSettings 相当のスタブ。"""
    defaults = dict(tenant_id=1, account_id="101-001-123", environment="practice",
                    api_token=None, updated_at=datetime(2026, 1, 1, tzinfo=timezone.utc))
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


class TestTableDefinition:
    """TenantOandaSettings テーブル定義のテスト"""

    def test_table_name(self):
        """テーブル名が tenant_oanda_settings であること"""
        assert TenantOandaSettings.__tablename__ == "tenant_oanda_settings"

    def test_columns(self):
        """必要なカラムを備えること"""
        columns = {c.name for c in TenantOandaSettings.__table__.columns}
        assert {"tenant_id", "account_id", "environment", "api_token", "updated_at"} <= columns


class TestMaskToken:
    """_mask_token() のテスト"""

    def test_none_stays_none(self):
        """未設定なら None を返すこと"""
        assert _mask_token(None) is None
        assert _mask_token("") is None

    def test_short_tokens_are_fully_masked(self):
        """短いトークンは全マスクにすること（推測の手掛かりを与えない）"""
        assert _mask_token("12345678") == "****"

    def test_long_tokens_show_head_and_tail(self):
        """長いトークンは先頭 4 文字と末尾 4 文字のみ表示すること"""
        assert _mask_token("abcd1234567890wxyz") == "abcd...wxyz"

    def test_middle_is_never_exposed(self):
        """中央部分を露出しないこと"""
        token = "abcdSECRETMIDDLEwxyz"
        assert "SECRET" not in _mask_token(token)


class TestGetTenantOandaSettings:
    """get_tenant_oanda_settings() のテスト"""

    def _db(self, row):
        db = MagicMock()
        db.get.return_value = row
        return db

    def test_returns_none_when_unset(self):
        """設定が無ければ None を返すこと"""
        with patch("src.broker.tenant_oanda.SessionLocal", return_value=self._db(None)):
            assert get_tenant_oanda_settings(1) is None

    def test_returns_settings(self):
        """保存済みの設定を返すこと"""
        with patch("src.broker.tenant_oanda.SessionLocal",
                   return_value=self._db(settings_row())):
            result = get_tenant_oanda_settings(1)

        assert result["account_id"] == "101-001-123"
        assert result["environment"] == "practice"

    def test_token_is_never_returned_in_clear(self):
        """API トークンは平文で返さないこと"""
        row = settings_row(api_token="enc:supersecrettoken")
        with patch("src.broker.tenant_oanda.SessionLocal", return_value=self._db(row)):
            result = get_tenant_oanda_settings(1)

        assert "api_token" not in result
        assert result["api_token_set"] is True
        assert "supersecret" not in str(result)

    def test_reports_when_no_token_is_set(self):
        """トークン未設定を明示すること"""
        with patch("src.broker.tenant_oanda.SessionLocal",
                   return_value=self._db(settings_row(api_token=None))):
            result = get_tenant_oanda_settings(1)

        assert result["api_token_set"] is False
        assert result["api_token_masked"] is None

    def test_environment_defaults_to_practice(self):
        """環境が未設定なら practice にフォールバックすること（安全側）"""
        with patch("src.broker.tenant_oanda.SessionLocal",
                   return_value=self._db(settings_row(environment=None))):
            assert get_tenant_oanda_settings(1)["environment"] == "practice"

    def test_closes_the_session(self):
        """DB セッションを閉じること"""
        db = self._db(None)
        with patch("src.broker.tenant_oanda.SessionLocal", return_value=db):
            get_tenant_oanda_settings(1)
        db.close.assert_called_once()


class TestSaveTenantOandaSettings:
    """save_tenant_oanda_settings() のテスト"""

    def _db(self, row=None):
        db = MagicMock()
        db.get.return_value = row
        return db

    def test_rejects_unknown_environments(self):
        """practice / live 以外の環境は拒否すること"""
        with pytest.raises(ValueError, match="practice or live"):
            save_tenant_oanda_settings(1, environment="production")

    def test_creates_a_row_when_absent(self):
        """設定が無ければ新規作成すること"""
        db = self._db(None)
        with patch("src.broker.tenant_oanda.SessionLocal", return_value=db), \
             patch("src.broker.tenant_oanda.get_tenant_oanda_settings", return_value={}):
            save_tenant_oanda_settings(1, account_id="101-001")

        db.add.assert_called_once()
        db.commit.assert_called_once()

    def test_updates_an_existing_row(self):
        """既存の設定は更新すること"""
        row = settings_row()
        db = self._db(row)
        with patch("src.broker.tenant_oanda.SessionLocal", return_value=db), \
             patch("src.broker.tenant_oanda.get_tenant_oanda_settings", return_value={}):
            save_tenant_oanda_settings(1, account_id="101-999")

        assert row.account_id == "101-999"
        db.add.assert_not_called()

    def test_token_is_encrypted(self):
        """API トークンは暗号化して保存すること"""
        row = settings_row()
        with patch("src.broker.tenant_oanda.SessionLocal", return_value=self._db(row)), \
             patch("src.broker.tenant_oanda.encrypt_secret",
                   side_effect=lambda v: f"enc:{v}") as encrypt, \
             patch("src.broker.tenant_oanda.get_tenant_oanda_settings", return_value={}):
            save_tenant_oanda_settings(1, api_token="  raw-token  ")

        encrypt.assert_called_once_with("raw-token")
        assert row.api_token == "enc:raw-token"

    def test_blank_token_is_ignored(self):
        """空白のみのトークンは無視すること（誤消去を防ぐ）"""
        row = settings_row(api_token="enc:existing")
        with patch("src.broker.tenant_oanda.SessionLocal", return_value=self._db(row)), \
             patch("src.broker.tenant_oanda.get_tenant_oanda_settings", return_value={}):
            save_tenant_oanda_settings(1, api_token="   ")

        assert row.api_token == "enc:existing"

    def test_clear_token_removes_it(self):
        """削除フラグでトークンを消去できること"""
        row = settings_row(api_token="enc:existing")
        with patch("src.broker.tenant_oanda.SessionLocal", return_value=self._db(row)), \
             patch("src.broker.tenant_oanda.get_tenant_oanda_settings", return_value={}):
            save_tenant_oanda_settings(1, clear_token=True)

        assert row.api_token is None

    def test_blank_account_id_becomes_none(self):
        """空の口座 ID は None にすること"""
        row = settings_row()
        with patch("src.broker.tenant_oanda.SessionLocal", return_value=self._db(row)), \
             patch("src.broker.tenant_oanda.get_tenant_oanda_settings", return_value={}):
            save_tenant_oanda_settings(1, account_id="   ")

        assert row.account_id is None

    def test_rolls_back_on_failure(self):
        """保存に失敗したらロールバックして例外を伝えること"""
        db = self._db(settings_row())
        db.commit.side_effect = OSError("db down")
        with patch("src.broker.tenant_oanda.SessionLocal", return_value=db):
            with pytest.raises(OSError):
                save_tenant_oanda_settings(1, account_id="101-001")

        db.rollback.assert_called_once()


class TestResolveOandaCredentials:
    """resolve_oanda_credentials() のテスト"""

    def _db(self, row):
        db = MagicMock()
        db.get.return_value = row
        return db

    def test_paper_mode_never_touches_the_database(self):
        """ペーパーモードでは DB も参照せず未設定として扱うこと"""
        with patch("src.broker.tenant_oanda.SessionLocal") as session_local:
            creds = resolve_oanda_credentials(1, trading_mode="paper")

        assert creds.configured is False
        assert creds.mode == "paper"
        assert creds.source == "paper"
        session_local.assert_not_called()

    def test_default_mode_is_paper(self):
        """モード未指定ならペーパーにすること（誤発注の防止）"""
        assert resolve_oanda_credentials(1).mode == "paper"

    def test_returns_tenant_credentials(self):
        """テナントの認証情報を復号して返すこと"""
        row = settings_row(api_token="enc:token", environment="practice")
        with patch("src.broker.tenant_oanda.SessionLocal", return_value=self._db(row)), \
             patch("src.broker.tenant_oanda.decrypt_secret", return_value="plain-token"):
            creds = resolve_oanda_credentials(1, trading_mode="practice")

        assert creds.configured is True
        assert creds.api_token == "plain-token"
        assert creds.account_id == "101-001-123"

    def test_undecryptable_token_falls_back_to_paper(self):
        """復号できないトークンではペーパーへ退避すること（誤接続の防止）"""
        row = settings_row(api_token="enc:broken")
        with patch("src.broker.tenant_oanda.SessionLocal", return_value=self._db(row)), \
             patch("src.broker.tenant_oanda.decrypt_secret", return_value=None):
            creds = resolve_oanda_credentials(1, trading_mode="live")

        assert creds.configured is False
        assert creds.mode == "paper"

    def test_live_mode_requires_a_live_environment(self):
        """設定が practice のまま live 発注しようとしても practice に固定すること"""
        row = settings_row(api_token="enc:token", environment="practice")
        with patch("src.broker.tenant_oanda.SessionLocal", return_value=self._db(row)), \
             patch("src.broker.tenant_oanda.decrypt_secret", return_value="plain-token"):
            creds = resolve_oanda_credentials(1, trading_mode="live")

        assert creds.mode == "practice"

    def test_live_environment_is_honoured(self):
        """設定が live なら live として解決すること"""
        row = settings_row(api_token="enc:token", environment="live")
        with patch("src.broker.tenant_oanda.SessionLocal", return_value=self._db(row)), \
             patch("src.broker.tenant_oanda.decrypt_secret", return_value="plain-token"):
            creds = resolve_oanda_credentials(1, trading_mode="live")

        assert creds.mode == "live"

    def test_incomplete_settings_are_ignored(self):
        """口座 ID かトークンが欠けていれば未設定扱いにすること"""
        row = settings_row(api_token=None, account_id="101-001")
        with patch("src.broker.tenant_oanda.SessionLocal", return_value=self._db(row)):
            creds = resolve_oanda_credentials(1, trading_mode="live")

        assert creds.configured is False


class TestOandaCredentialsDataclass:
    """OandaCredentials データクラスのテスト"""

    def test_holds_the_expected_fields(self):
        """必要なフィールドを保持すること"""
        creds = OandaCredentials(configured=True, mode="live", api_token="t",
                                 account_id="a", source="tenant")

        assert creds.configured is True
        assert creds.mode == "live"
        assert creds.source == "tenant"
