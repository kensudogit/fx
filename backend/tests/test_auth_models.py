"""SaaS の ORM モデル — src.auth.models のテスト

DB へは接続せず、テーブル定義（スキーマ）と利用実績ヘルパーの挙動を検証する。
SessionLocal / engine はモックに差し替える。
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

from src.auth.models import (
    Tenant,
    TenantApiKey,
    UsageEvent,
    User,
    count_daily_usage,
    init_auth_tables,
    record_usage,
)


def column_names(model) -> set:
    """モデルのカラム名集合を返す。"""
    return {c.name for c in model.__table__.columns}


class TestTenantModel:
    """Tenant テーブル定義のテスト"""

    def test_table_name(self):
        """テーブル名が tenants であること"""
        assert Tenant.__tablename__ == "tenants"

    def test_columns(self):
        """必要なカラムが揃っていること"""
        assert column_names(Tenant) == {
            "id", "name", "slug", "plan", "stripe_customer_id",
            "stripe_subscription_id", "created_at",
        }

    def test_slug_is_unique(self):
        """slug は一意であること（URL 識別子の重複を防ぐ）"""
        assert Tenant.__table__.c.slug.unique is True

    def test_plan_defaults_to_free(self):
        """プランの既定値が free であること"""
        assert Tenant.__table__.c.plan.default.arg == "free"

    def test_required_columns_are_not_nullable(self):
        """name / slug / plan は NOT NULL であること"""
        for name in ("name", "slug", "plan", "created_at"):
            assert Tenant.__table__.c[name].nullable is False

    def test_stripe_columns_are_optional(self):
        """Stripe 連携前のテナントも保存できること"""
        assert Tenant.__table__.c.stripe_customer_id.nullable is True
        assert Tenant.__table__.c.stripe_subscription_id.nullable is True

    def test_has_users_and_api_keys_relationships(self):
        """users / api_keys のリレーションを持つこと"""
        assert "users" in Tenant.__mapper__.relationships
        assert "api_keys" in Tenant.__mapper__.relationships


class TestUserModel:
    """User テーブル定義のテスト"""

    def test_table_name(self):
        """テーブル名が users であること"""
        assert User.__tablename__ == "users"

    def test_columns(self):
        """必要なカラムが揃っていること"""
        assert column_names(User) == {
            "id", "tenant_id", "email", "password_hash", "role", "created_at",
        }

    def test_email_is_unique_across_system(self):
        """メールアドレスはシステム全体で一意であること"""
        constraints = {c.name for c in User.__table__.constraints}
        assert "uq_users_email" in constraints

    def test_belongs_to_a_tenant(self):
        """必ずテナントに属すること（外部キー・NOT NULL）"""
        assert User.__table__.c.tenant_id.nullable is False
        fks = {fk.target_fullname for fk in User.__table__.c.tenant_id.foreign_keys}
        assert fks == {"tenants.id"}

    def test_stores_hash_not_raw_password(self):
        """生パスワード用のカラムが存在しないこと"""
        assert "password_hash" in column_names(User)
        assert "password" not in column_names(User)

    def test_role_defaults_to_owner(self):
        """ロールの既定値が owner であること"""
        assert User.__table__.c.role.default.arg == "owner"


class TestTenantApiKeyModel:
    """TenantApiKey テーブル定義のテスト"""

    def test_table_name(self):
        """テーブル名が tenant_api_keys であること"""
        assert TenantApiKey.__tablename__ == "tenant_api_keys"

    def test_columns(self):
        """必要なカラムが揃っていること"""
        assert column_names(TenantApiKey) == {
            "id", "tenant_id", "name", "key_prefix", "key_hash",
            "last_used_at", "created_at",
        }

    def test_stores_only_the_hash(self):
        """生のキーは保存せず、ハッシュとプレフィックスのみ保持すること"""
        cols = column_names(TenantApiKey)
        assert "key_hash" in cols
        assert "raw_key" not in cols

    def test_hash_column_fits_sha256_hex(self):
        """SHA-256 の 16 進 64 文字を保存できる長さであること"""
        assert TenantApiKey.__table__.c.key_hash.type.length >= 64

    def test_last_used_at_is_optional(self):
        """未使用のキーも保存できること"""
        assert TenantApiKey.__table__.c.last_used_at.nullable is True

    def test_belongs_to_a_tenant(self):
        """テナントへの外部キーを持つこと"""
        fks = {fk.target_fullname for fk in TenantApiKey.__table__.c.tenant_id.foreign_keys}
        assert fks == {"tenants.id"}


class TestUsageEventModel:
    """UsageEvent テーブル定義のテスト"""

    def test_table_name(self):
        """テーブル名が usage_events であること"""
        assert UsageEvent.__tablename__ == "usage_events"

    def test_has_tenant_and_timestamp(self):
        """テナント ID と作成日時を持つこと（日次集計に必要）"""
        cols = column_names(UsageEvent)
        assert "tenant_id" in cols
        assert "created_at" in cols


class TestInitAuthTables:
    """init_auth_tables() のテスト"""

    def test_creates_all_tables_with_checkfirst(self):
        """既存テーブルを壊さないよう checkfirst=True で作成すること"""
        with patch("src.auth.models.engine") as engine:
            with patch.object(Tenant.__table__, "create") as t_create, \
                 patch.object(User.__table__, "create") as u_create, \
                 patch.object(TenantApiKey.__table__, "create") as k_create, \
                 patch.object(UsageEvent.__table__, "create") as e_create:
                init_auth_tables()

        for create in (t_create, u_create, k_create, e_create):
            create.assert_called_once()
            assert create.call_args.kwargs["checkfirst"] is True

    def test_swallows_database_errors(self):
        """DB へ接続できなくても例外を送出しないこと（起動を止めない）"""
        with patch.object(Tenant.__table__, "create", side_effect=OSError("no db")):
            init_auth_tables()  # 例外が出なければ成功


class TestCountDailyUsage:
    """count_daily_usage() のテスト"""

    def _session(self, scalar_value):
        """scalar() が指定値を返すモックセッションを組み立てる。"""
        session = MagicMock()
        session.execute.return_value.scalar.return_value = scalar_value
        return session

    def test_returns_count(self):
        """クエリ結果の件数を int で返すこと"""
        session = self._session(17)
        with patch("src.auth.models.SessionLocal", return_value=session):
            assert count_daily_usage(1) == 17

    def test_returns_zero_when_no_rows(self):
        """レコードが無い（scalar が None）場合は 0 を返すこと"""
        session = self._session(None)
        with patch("src.auth.models.SessionLocal", return_value=session):
            assert count_daily_usage(1) == 0

    def test_closes_the_session(self):
        """集計後にセッションを閉じること（コネクションリーク防止）"""
        session = self._session(0)
        with patch("src.auth.models.SessionLocal", return_value=session):
            count_daily_usage(1)
        session.close.assert_called_once()

    def test_counts_from_utc_midnight(self):
        """UTC の当日 0:00 以降を集計範囲にすること"""
        session = self._session(0)
        with patch("src.auth.models.SessionLocal", return_value=session):
            count_daily_usage(1)

        # クエリの WHERE 句に渡された境界値を取り出して検証する
        compiled = str(session.execute.call_args[0][0].compile(
            compile_kwargs={"literal_binds": True}))
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        assert f"{today} 00:00:00" in compiled


class TestRecordUsage:
    """record_usage() のテスト"""

    def test_persists_an_event(self):
        """イベントを追加してコミットすること"""
        session = MagicMock()
        with patch("src.auth.models.SessionLocal", return_value=session):
            record_usage(3, "/api/symbols")

        session.add.assert_called_once()
        event = session.add.call_args[0][0]
        assert event.tenant_id == 3
        assert event.path == "/api/symbols"
        assert event.event_type == "api_call"
        session.commit.assert_called_once()

    def test_custom_event_type(self):
        """イベント種別を指定できること"""
        session = MagicMock()
        with patch("src.auth.models.SessionLocal", return_value=session):
            record_usage(3, "/api/ai/report/USDJPY", event_type="ai_call")
        assert session.add.call_args[0][0].event_type == "ai_call"

    def test_truncates_long_paths(self):
        """長すぎるパスは 200 文字に切り詰めること（カラム長超過を防ぐ）"""
        session = MagicMock()
        with patch("src.auth.models.SessionLocal", return_value=session):
            record_usage(3, "/api/" + "x" * 500)
        assert len(session.add.call_args[0][0].path) == 200

    def test_rolls_back_on_failure(self):
        """書き込み失敗時はロールバックし、例外を伝播させないこと"""
        session = MagicMock()
        session.commit.side_effect = OSError("db down")
        with patch("src.auth.models.SessionLocal", return_value=session):
            record_usage(3, "/api/symbols")  # 例外が出ないこと

        session.rollback.assert_called_once()

    def test_always_closes_the_session(self):
        """成功・失敗いずれでもセッションを閉じること"""
        session = MagicMock()
        session.commit.side_effect = OSError("db down")
        with patch("src.auth.models.SessionLocal", return_value=session):
            record_usage(3, "/api/symbols")
        session.close.assert_called_once()
