"""DB 接続・ORM モデル・キャッシュ層 — src.db.database のテスト

実際の PostgreSQL へは接続せず、テーブル定義とキャッシュ実装を検証する。
"""

from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

import src.db.database as database
from src.db.database import (
    Base,
    DynamoDBClient,
    FundamentalEvent,
    InMemoryCache,
    OHLCVRecord,
    create_cache_client,
    get_db,
    init_database,
)


def column_names(model) -> set:
    """モデルのカラム名集合を返す。"""
    return {c.name for c in model.__table__.columns}


class TestOhlcvRecord:
    """OHLCVRecord テーブル定義のテスト"""

    def test_table_name(self):
        """テーブル名が ohlcv_data であること"""
        assert OHLCVRecord.__tablename__ == "ohlcv_data"

    def test_columns(self):
        """必要なカラムが揃っていること"""
        assert column_names(OHLCVRecord) == {
            "id", "symbol", "timestamp", "open", "high", "low", "close", "volume", "timeframe",
        }

    def test_price_columns_are_not_nullable(self):
        """OHLC は必須であること"""
        for name in ("open", "high", "low", "close", "symbol", "timestamp"):
            assert OHLCVRecord.__table__.c[name].nullable is False

    def test_prices_use_high_precision_numeric(self):
        """価格は浮動小数ではなく Numeric(18, 6) で保持すること（丸め誤差の回避）"""
        column = OHLCVRecord.__table__.c.close
        assert column.type.precision == 18
        assert column.type.scale == 6

    def test_volume_defaults_to_zero(self):
        """FX では出来高が無い場合があるため既定値 0 であること"""
        assert OHLCVRecord.__table__.c.volume.default.arg == 0

    def test_timeframe_defaults_to_daily(self):
        """時間足の既定値は日足であること"""
        assert OHLCVRecord.__table__.c.timeframe.default.arg == "1d"


class TestFundamentalEvent:
    """FundamentalEvent テーブル定義のテスト"""

    def test_table_name(self):
        """テーブル名が fundamental_events であること"""
        assert FundamentalEvent.__tablename__ == "fundamental_events"

    def test_columns(self):
        """必要なカラムが揃っていること"""
        assert column_names(FundamentalEvent) == {
            "id", "event_type", "country", "title", "event_date",
            "actual_value", "forecast_value", "previous_value", "unit", "impact",
        }

    def test_required_fields(self):
        """種別・国・タイトル・日付は必須であること"""
        for name in ("event_type", "country", "title", "event_date"):
            assert FundamentalEvent.__table__.c[name].nullable is False

    def test_values_are_optional(self):
        """実績・予想・前回値は未定のこともあるため任意であること"""
        for name in ("actual_value", "forecast_value", "previous_value"):
            assert FundamentalEvent.__table__.c[name].nullable is True

    def test_impact_defaults_to_medium(self):
        """影響度の既定値は medium であること"""
        assert FundamentalEvent.__table__.c.impact.default.arg == "medium"

    def test_models_share_the_declarative_base(self):
        """両モデルが同じ Base を継承していること"""
        assert issubclass(OHLCVRecord, Base)
        assert issubclass(FundamentalEvent, Base)


class TestGetDb:
    """get_db() 依存性のテスト"""

    def test_yields_a_session(self):
        """セッションを 1 つ払い出すこと"""
        session = MagicMock()
        with patch("src.db.database.SessionLocal", return_value=session):
            gen = get_db()
            assert next(gen) is session
            with pytest.raises(StopIteration):
                next(gen)

    def test_closes_the_session_afterwards(self):
        """使用後にセッションを閉じること"""
        session = MagicMock()
        with patch("src.db.database.SessionLocal", return_value=session):
            gen = get_db()
            next(gen)
            gen.close()

        session.close.assert_called_once()

    def test_closes_the_session_on_error(self):
        """例外が起きてもセッションを閉じること"""
        session = MagicMock()
        with patch("src.db.database.SessionLocal", return_value=session):
            gen = get_db()
            next(gen)
            with pytest.raises(RuntimeError):
                gen.throw(RuntimeError("handler failed"))

        session.close.assert_called_once()


class TestInitDatabase:
    """init_database() のテスト"""

    def test_skips_when_init_sql_is_missing(self):
        """init.sql が無ければ何もしないこと"""
        with patch("src.db.database.Path") as path, patch("src.db.database.engine") as engine:
            path.return_value.resolve.return_value.parent.parent.parent.__truediv__\
                .return_value.__truediv__.return_value.exists.return_value = False
            init_database()

        engine.begin.assert_not_called()

    def test_ignores_already_exists_errors(self, tmp_path):
        """既存オブジェクトのエラーは無視して続行すること（冪等な初期化）"""
        sql_file = tmp_path / "init.sql"
        sql_file.write_text("CREATE TABLE a (id int); CREATE TABLE b (id int);",
                            encoding="utf-8")

        conn = MagicMock()
        conn.execute.side_effect = [RuntimeError("relation already exists"), None]
        engine = MagicMock()
        engine.begin.return_value.__enter__.return_value = conn

        with patch("src.db.database.engine", engine), \
             patch("src.db.database.Path") as path:
            path.return_value.resolve.return_value.parent.parent.parent.__truediv__\
                .return_value.__truediv__.return_value = sql_file
            init_database()

        assert conn.execute.call_count == 2


class TestInMemoryCache:
    """InMemoryCache のテスト"""

    def test_roundtrip(self):
        """保存した値を取り出せること"""
        cache = InMemoryCache()
        cache.put("k", {"v": 1}, ttl_seconds=60)
        assert cache.get("k") == {"v": 1}

    def test_missing_key_returns_none(self):
        """未保存のキーは None を返すこと"""
        assert InMemoryCache().get("missing") is None

    def test_expired_entry_returns_none(self):
        """TTL を過ぎた値は None を返すこと"""
        cache = InMemoryCache()
        cache.put("k", {"v": 1}, ttl_seconds=-1)
        assert cache.get("k") is None

    def test_expired_entry_is_evicted(self):
        """期限切れの値はストアから削除されること（メモリリーク防止）"""
        cache = InMemoryCache()
        cache.put("k", {"v": 1}, ttl_seconds=-1)
        cache.get("k")
        assert "k" not in cache._store

    def test_put_overwrites(self):
        """同じキーへの再保存で上書きされること"""
        cache = InMemoryCache()
        cache.put("k", {"v": 1}, ttl_seconds=60)
        cache.put("k", {"v": 2}, ttl_seconds=60)
        assert cache.get("k") == {"v": 2}

    def test_keys_are_independent(self):
        """キーごとに独立して保持されること"""
        cache = InMemoryCache()
        cache.put("a", {"v": 1}, ttl_seconds=60)
        cache.put("b", {"v": 2}, ttl_seconds=60)
        assert cache.get("a") != cache.get("b")

    def test_instances_do_not_share_state(self):
        """インスタンスごとにストアが分離されていること"""
        first, second = InMemoryCache(), InMemoryCache()
        first.put("k", {"v": 1}, ttl_seconds=60)
        assert second.get("k") is None

    def test_stores_expiry_timestamp(self):
        """TTL の分だけ先の有効期限を保持すること

        実装は `datetime.utcnow().timestamp()` を基準にしている。これは naive な
        UTC 時刻をローカル時刻として解釈するため `time.time()` とはタイムゾーン分
        ずれるが、保存・判定の両方が同じ基準なので TTL の動作自体は正しい。
        ここでは実装と同じ基準時刻で検証する。
        """
        cache = InMemoryCache()
        before = datetime.utcnow().timestamp()
        cache.put("k", {"v": 1}, ttl_seconds=60)

        expires_at = cache._store["k"]["expires_at"]
        assert before + 59 <= expires_at <= before + 61

    def test_ttl_boundary_is_honoured(self):
        """TTL が正なら有効、負なら無効と判定されること"""
        cache = InMemoryCache()
        cache.put("alive", {"v": 1}, ttl_seconds=60)
        cache.put("dead", {"v": 1}, ttl_seconds=-60)

        assert cache.get("alive") == {"v": 1}
        assert cache.get("dead") is None


class TestCreateCacheClient:
    """create_cache_client() のテスト"""

    def test_uses_memory_cache_without_endpoint(self, override_settings):
        """DynamoDB エンドポイント未設定ならインメモリを使うこと"""
        override_settings(dynamodb_endpoint="")
        assert isinstance(create_cache_client(), InMemoryCache)

    def test_falls_back_when_dynamodb_is_unavailable(self, override_settings):
        """DynamoDB へ接続できなければインメモリへフォールバックすること"""
        override_settings(dynamodb_endpoint="http://localhost:8000")
        with patch("src.db.database.DynamoDBClient", side_effect=OSError("unreachable")):
            assert isinstance(create_cache_client(), InMemoryCache)

    def test_uses_dynamodb_when_available(self, override_settings):
        """DynamoDB が使えればそちらを返すこと"""
        override_settings(dynamodb_endpoint="http://localhost:8000")
        fake = MagicMock()
        with patch("src.db.database.DynamoDBClient", return_value=fake):
            assert create_cache_client() is fake

    def test_module_level_client_supports_the_cache_protocol(self):
        """モジュール共有のクライアントが get / put を備えること"""
        assert hasattr(database.dynamodb_client, "get")
        assert hasattr(database.dynamodb_client, "put")
