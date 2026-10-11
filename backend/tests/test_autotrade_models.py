"""自動売買の設定・実行ログ永続化 — src.autotrade.models のテスト

DB へは接続せず SessionLocal をモックに差し替え、
設定マージ・UPSERT・メモリフォールバック・集計ロジックを検証する。
"""

import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

import src.autotrade.models as models
from src.autotrade.models import (
    DEFAULT_CONFIG,
    AutoTradeConfig,
    AutoTradeRun,
    count_today_trades,
    get_config,
    last_executed_at,
    list_runs,
    merge_config,
    save_config,
    save_run,
)


@pytest.fixture(autouse=True)
def clean_memory_fallback():
    """メモリフォールバックをテストごとに初期化する。"""
    models._memory_configs = {}
    models._memory_runs = []
    with patch("src.autotrade.models._ensure_tables"):
        yield
    models._memory_configs = {}
    models._memory_runs = []


def mock_session(scalar_one=None, scalars_all=None, raises=None):
    """execute() の戻り値を制御するモックセッションを返す。"""
    session = MagicMock()
    if raises is not None:
        session.execute.side_effect = raises
    else:
        result = session.execute.return_value
        result.scalar_one_or_none.return_value = scalar_one
        result.scalars.return_value.all.return_value = scalars_all or []
    return session


def run_row(**kwargs):
    """AutoTradeRun 相当のスタブを返す。"""
    defaults = dict(id=1, symbol="USDJPY", action="buy", decision="executed",
                    confidence=71.0, units=1000, fill_price=151.5, order_id="o-1",
                    trigger="manual", reason="ok", signal_snapshot="{}",
                    created_at=datetime.now(timezone.utc))
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


class TestDefaultConfig:
    """DEFAULT_CONFIG のテスト"""

    def test_autotrade_is_off_by_default(self):
        """安全のため既定では無効であること"""
        assert DEFAULT_CONFIG["enabled"] is False

    def test_paper_mode_by_default(self):
        """既定はペーパートレードであること（誤発注の防止）"""
        assert DEFAULT_CONFIG["mode"] == "paper"

    def test_risk_guards_are_present(self):
        """リスク管理の既定値が設定されていること"""
        assert DEFAULT_CONFIG["risk_percent"] > 0
        assert DEFAULT_CONFIG["max_daily_trades"] >= 1
        assert DEFAULT_CONFIG["cooldown_minutes"] >= 0
        assert DEFAULT_CONFIG["min_confidence"] > 0

    def test_protective_orders_are_enabled(self):
        """SL / TP は既定で有効であること"""
        assert DEFAULT_CONFIG["use_stop_loss"] is True
        assert DEFAULT_CONFIG["use_take_profit"] is True

    def test_averaging_down_is_disabled(self):
        """ナンピンは既定で無効であること"""
        assert DEFAULT_CONFIG["allow_add_to_position"] is False

    def test_lot_bounds_are_ordered(self):
        """最小ロット <= 最大ロットであること"""
        assert DEFAULT_CONFIG["min_lots"] <= DEFAULT_CONFIG["max_lots"]


class TestMergeConfig:
    """merge_config() のテスト"""

    def test_none_returns_defaults(self):
        """None を渡すと既定設定を返すこと"""
        assert merge_config(None) == {**DEFAULT_CONFIG, "symbols": ["USDJPY"]}

    def test_empty_dict_returns_defaults(self):
        """空辞書でも既定設定が埋まること"""
        assert merge_config({})["min_confidence"] == DEFAULT_CONFIG["min_confidence"]

    def test_user_values_take_precedence(self):
        """指定した値が既定値を上書きすること"""
        assert merge_config({"min_confidence": 80})["min_confidence"] == 80

    def test_missing_keys_are_filled(self):
        """未指定のキーは既定値で補完されること"""
        merged = merge_config({"enabled": True})
        assert merged["enabled"] is True
        assert merged["mode"] == DEFAULT_CONFIG["mode"]

    def test_empty_symbols_fall_back_to_usdjpy(self):
        """通貨ペアが空なら USDJPY を既定として設定すること"""
        assert merge_config({"symbols": []})["symbols"] == ["USDJPY"]

    def test_explicit_symbols_are_kept(self):
        """指定された通貨ペアは維持すること"""
        assert merge_config({"symbols": ["EURUSD", "GBPUSD"]})["symbols"] == ["EURUSD", "GBPUSD"]

    def test_does_not_mutate_the_defaults(self):
        """既定設定そのものを書き換えないこと"""
        merge_config({"enabled": True})
        assert DEFAULT_CONFIG["enabled"] is False


class TestGetConfig:
    """get_config() のテスト"""

    def test_reads_from_the_database(self):
        """DB に設定があればそれを読み出すこと"""
        row = SimpleNamespace(config_json=json.dumps({"min_confidence": 88}))
        with patch("src.autotrade.models.SessionLocal", return_value=mock_session(scalar_one=row)):
            assert get_config(tenant_id=1)["min_confidence"] == 88

    def test_result_is_always_merged_with_defaults(self):
        """DB の部分設定でも既定値で補完して返すこと"""
        row = SimpleNamespace(config_json=json.dumps({"min_confidence": 88}))
        with patch("src.autotrade.models.SessionLocal", return_value=mock_session(scalar_one=row)):
            config = get_config(tenant_id=1)

        assert config["mode"] == DEFAULT_CONFIG["mode"]
        assert set(config) >= set(DEFAULT_CONFIG)

    def test_falls_back_to_memory_cache(self):
        """DB が使えない場合はメモリキャッシュを使うこと"""
        models._memory_configs[7] = {**DEFAULT_CONFIG, "min_confidence": 42}
        with patch("src.autotrade.models.SessionLocal",
                   return_value=mock_session(raises=OSError("db down"))):
            assert get_config(tenant_id=7)["min_confidence"] == 42

    def test_falls_back_to_defaults_when_nothing_is_stored(self):
        """設定が無ければ既定値を返すこと"""
        with patch("src.autotrade.models.SessionLocal",
                   return_value=mock_session(scalar_one=None)):
            assert get_config(tenant_id=1)["enabled"] is False

    def test_closes_the_session(self):
        """セッションを閉じること"""
        session = mock_session(scalar_one=None)
        with patch("src.autotrade.models.SessionLocal", return_value=session):
            get_config(tenant_id=1)
        session.close.assert_called_once()


class TestSaveConfig:
    """save_config() のテスト"""

    def test_inserts_when_absent(self):
        """設定が無ければ新規行を追加すること"""
        session = mock_session(scalar_one=None)
        with patch("src.autotrade.models.SessionLocal", return_value=session):
            save_config({"min_confidence": 70}, tenant_id=1)

        session.add.assert_called_once()
        session.commit.assert_called_once()

    def test_updates_when_present(self):
        """既存行があれば更新すること（UPSERT）"""
        row = SimpleNamespace(config_json="{}", updated_at=None)
        session = mock_session(scalar_one=row)
        with patch("src.autotrade.models.SessionLocal", return_value=session):
            save_config({"min_confidence": 70}, tenant_id=1)

        assert json.loads(row.config_json)["min_confidence"] == 70
        assert isinstance(row.updated_at, datetime)
        session.add.assert_not_called()

    def test_returns_the_merged_config(self):
        """保存後はマージ済みの完全な設定を返すこと"""
        with patch("src.autotrade.models.SessionLocal",
                   return_value=mock_session(scalar_one=None)):
            saved = save_config({"min_confidence": 70}, tenant_id=1)

        assert saved["min_confidence"] == 70
        assert saved["mode"] == DEFAULT_CONFIG["mode"]

    def test_stores_japanese_text_unescaped(self):
        """日本語が \\uXXXX へエスケープされないこと（ログの可読性）"""
        row = SimpleNamespace(config_json="{}", updated_at=None)
        with patch("src.autotrade.models.SessionLocal", return_value=mock_session(scalar_one=row)):
            save_config({"note": "バランス型"}, tenant_id=1)

        assert "バランス型" in row.config_json

    def test_falls_back_to_memory_on_failure(self):
        """DB 保存に失敗したらメモリへ退避すること"""
        session = mock_session(scalar_one=None)
        session.commit.side_effect = OSError("db down")
        with patch("src.autotrade.models.SessionLocal", return_value=session):
            save_config({"min_confidence": 70}, tenant_id=5)

        session.rollback.assert_called_once()
        assert models._memory_configs[5]["min_confidence"] == 70


class TestSaveRun:
    """save_run() のテスト"""

    def test_persists_the_record(self):
        """実行ログを保存し、ID と日時を付与して返すこと"""
        session = MagicMock()

        def refresh(row):
            row.id = 99

        session.refresh.side_effect = refresh
        with patch("src.autotrade.models.SessionLocal", return_value=session):
            result = save_run({"symbol": "USDJPY", "action": "buy", "decision": "executed"},
                              tenant_id=1)

        assert result["id"] == 99
        assert result["created_at"]
        session.commit.assert_called_once()

    def test_applies_defaults_for_missing_fields(self):
        """未指定のフィールドは既定値で保存すること"""
        session = MagicMock()
        with patch("src.autotrade.models.SessionLocal", return_value=session):
            save_run({"symbol": "USDJPY"})

        row = session.add.call_args[0][0]
        assert row.action == "hold"
        assert row.decision == "skipped"
        assert row.trigger == "manual"

    def test_serialises_the_signal_snapshot(self):
        """シグナルのスナップショットを JSON で保存すること"""
        session = MagicMock()
        with patch("src.autotrade.models.SessionLocal", return_value=session):
            save_run({"symbol": "USDJPY", "signal_snapshot": {"bias": "買い"}})

        snapshot = json.loads(session.add.call_args[0][0].signal_snapshot)
        assert snapshot == {"bias": "買い"}

    def test_falls_back_to_memory_on_failure(self):
        """DB 保存に失敗しても例外を投げないこと"""
        session = MagicMock()
        session.commit.side_effect = OSError("db down")
        with patch("src.autotrade.models.SessionLocal", return_value=session):
            result = save_run({"symbol": "USDJPY"}, tenant_id=1)

        session.rollback.assert_called_once()
        assert result["symbol"] == "USDJPY"


class TestListRuns:
    """list_runs() のテスト"""

    def test_maps_rows_to_dicts(self):
        """行を辞書へ変換して返すこと"""
        with patch("src.autotrade.models.SessionLocal",
                   return_value=mock_session(scalars_all=[run_row()])):
            runs = list_runs(tenant_id=1)

        assert runs[0]["symbol"] == "USDJPY"
        assert runs[0]["decision"] == "executed"
        assert runs[0]["confidence"] == 71.0
        assert runs[0]["signal_snapshot"] == {}

    def test_timestamps_are_iso_strings(self):
        """作成日時は ISO 文字列で返すこと"""
        with patch("src.autotrade.models.SessionLocal",
                   return_value=mock_session(scalars_all=[run_row()])):
            assert isinstance(list_runs()[0]["created_at"], str)

    def test_null_fields_stay_none(self):
        """未設定の数値フィールドは None のままにすること"""
        with patch("src.autotrade.models.SessionLocal",
                   return_value=mock_session(scalars_all=[run_row(confidence=None,
                                                                 fill_price=None)])):
            row = list_runs()[0]

        assert row["confidence"] is None
        assert row["fill_price"] is None

    def test_symbol_filter_is_uppercased(self):
        """シンボルのフィルタは大文字へ正規化すること"""
        session = mock_session(scalars_all=[])
        with patch("src.autotrade.models.SessionLocal", return_value=session):
            list_runs(symbol="usdjpy")

        compiled = str(session.execute.call_args[0][0].compile(
            compile_kwargs={"literal_binds": True}))
        assert "USDJPY" in compiled

    def test_falls_back_to_memory_runs(self):
        """DB が使えない場合はメモリ上のログを返すこと"""
        models._memory_runs = [{"symbol": "USDJPY", "tenant_id": 3}]
        with patch("src.autotrade.models.SessionLocal",
                   return_value=mock_session(raises=OSError("db down"))):
            assert list_runs(tenant_id=3) == [{"symbol": "USDJPY", "tenant_id": 3}]

    def test_memory_fallback_filters_by_tenant(self):
        """メモリフォールバックでもテナントで絞り込むこと"""
        models._memory_runs = [{"symbol": "USDJPY", "tenant_id": 3},
                               {"symbol": "EURUSD", "tenant_id": 4}]
        with patch("src.autotrade.models.SessionLocal",
                   return_value=mock_session(raises=OSError("db down"))):
            assert len(list_runs(tenant_id=3)) == 1

    def test_memory_fallback_respects_the_limit(self):
        """メモリフォールバックでも件数上限を守ること"""
        models._memory_runs = [{"symbol": "USDJPY"} for _ in range(10)]
        with patch("src.autotrade.models.SessionLocal",
                   return_value=mock_session(raises=OSError("db down"))):
            assert len(list_runs(limit=3)) == 3


class TestCountTodayTrades:
    """count_today_trades() のテスト"""

    def test_counts_only_today(self):
        """当日（UTC）の約定のみを数えること"""
        now = datetime.now(timezone.utc)
        rows = [run_row(created_at=now), run_row(created_at=now - timedelta(days=2))]
        with patch("src.autotrade.models.SessionLocal",
                   return_value=mock_session(scalars_all=rows)):
            assert count_today_trades(tenant_id=1) == 1

    def test_returns_zero_without_history(self):
        """履歴が無ければ 0 を返すこと"""
        with patch("src.autotrade.models.SessionLocal", return_value=mock_session(scalars_all=[])):
            assert count_today_trades(tenant_id=1) == 0

    def test_only_executed_rows_are_queried(self):
        """約定（executed）のみを対象にすること"""
        session = mock_session(scalars_all=[])
        with patch("src.autotrade.models.SessionLocal", return_value=session):
            count_today_trades(tenant_id=1)

        compiled = str(session.execute.call_args[0][0].compile(
            compile_kwargs={"literal_binds": True}))
        assert "executed" in compiled

    def test_database_error_returns_zero(self):
        """DB エラー時は 0 を返すこと（上限判定を止めない）"""
        with patch("src.autotrade.models.SessionLocal",
                   return_value=mock_session(raises=OSError("db down"))):
            assert count_today_trades(tenant_id=1) == 0


class TestLastExecutedAt:
    """last_executed_at() のテスト"""

    def test_returns_the_latest_execution_time(self):
        """最後の約定日時を返すこと"""
        stamp = datetime.now(timezone.utc)
        with patch("src.autotrade.models.SessionLocal",
                   return_value=mock_session(scalar_one=run_row(created_at=stamp))):
            assert last_executed_at(1, "USDJPY") == stamp

    def test_returns_none_without_history(self):
        """約定履歴が無ければ None を返すこと"""
        with patch("src.autotrade.models.SessionLocal", return_value=mock_session(scalar_one=None)):
            assert last_executed_at(1, "USDJPY") is None

    def test_database_error_returns_none(self):
        """DB エラー時は None を返すこと"""
        with patch("src.autotrade.models.SessionLocal",
                   return_value=mock_session(raises=OSError("db down"))):
            assert last_executed_at(1, "USDJPY") is None


class TestTableDefinitions:
    """ORM テーブル定義のテスト"""

    def test_config_table_name(self):
        """設定テーブル名が autotrade_configs であること"""
        assert AutoTradeConfig.__tablename__ == "autotrade_configs"

    def test_run_table_name(self):
        """実行ログのテーブル名が autotrade_runs であること"""
        assert AutoTradeRun.__tablename__ == "autotrade_runs"

    def test_run_has_audit_fields(self):
        """監査に必要な列を備えること"""
        columns = {c.name for c in AutoTradeRun.__table__.columns}
        assert {"symbol", "action", "decision", "trigger", "reason", "created_at"} <= columns

    def test_both_tables_are_tenant_scoped(self):
        """マルチテナント分離のため tenant_id 列を持つこと"""
        assert "tenant_id" in {c.name for c in AutoTradeConfig.__table__.columns}
        assert "tenant_id" in {c.name for c in AutoTradeRun.__table__.columns}
