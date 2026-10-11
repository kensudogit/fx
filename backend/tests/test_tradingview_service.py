"""TradingView Webhook シグナル — src.tradingview.service のテスト

DB はモックへ差し替え、ペイロード正規化とメモリフォールバックを検証する。
"""

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

import src.tradingview.service as service
from src.tradingview.service import TradingViewSignal, list_signals, save_signal


@pytest.fixture(autouse=True)
def clean_state():
    """メモリフォールバックとテーブル初期化を無効化する。"""
    service._memory_signals = []
    with patch("src.tradingview.service._ensure_table"):
        yield
    service._memory_signals = []


def save(payload, tenant_id=1, fail=False):
    """DB をモックして保存する。"""
    session = MagicMock()
    if fail:
        session.commit.side_effect = OSError("db down")
    else:
        def refresh(row):
            row.id = 7
        session.refresh.side_effect = refresh

    with patch("src.tradingview.service.SessionLocal", return_value=session):
        return save_signal(payload, tenant_id), session


class TestTableDefinition:
    """TradingViewSignal テーブル定義のテスト"""

    def test_table_name(self):
        """テーブル名が tradingview_signals であること"""
        assert TradingViewSignal.__tablename__ == "tradingview_signals"

    def test_has_the_expected_columns(self):
        """必要なカラムを備えること"""
        columns = {c.name for c in TradingViewSignal.__table__.columns}
        assert {"symbol", "action", "price", "strategy", "message", "received_at"} <= columns

    def test_is_tenant_scoped(self):
        """テナント分離のため tenant_id を持つこと"""
        assert "tenant_id" in {c.name for c in TradingViewSignal.__table__.columns}


class TestSaveSignalNormalization:
    """save_signal() のペイロード正規化テスト"""

    def test_reads_the_symbol(self):
        """symbol フィールドを読むこと"""
        record, _ = save({"symbol": "usdjpy", "action": "buy"})
        assert record["symbol"] == "USDJPY"

    def test_falls_back_to_ticker(self):
        """symbol が無ければ ticker を使うこと"""
        record, _ = save({"ticker": "eurusd"})
        assert record["symbol"] == "EURUSD"

    def test_defaults_to_unknown(self):
        """シンボルが無ければ UNKNOWN にすること"""
        record, _ = save({})
        assert record["symbol"] == "UNKNOWN"

    @pytest.mark.parametrize("raw,expected", [
        ("OANDA:USDJPY", "USDJPY"),
        ("FX:EURUSD", "EURUSD"),
        ("BINANCE:BTCUSDT", "BTCUSDT"),
    ])
    def test_strips_exchange_prefixes(self, raw, expected):
        """取引所プレフィックスを除去すること"""
        record, _ = save({"symbol": raw})
        assert record["symbol"] == expected

    def test_symbol_is_truncated(self):
        """シンボルは 10 文字までに切り詰めること"""
        record, _ = save({"symbol": "A" * 30})
        assert len(record["symbol"]) == 10

    def test_reads_the_action(self):
        """action を小文字で取り込むこと"""
        record, _ = save({"symbol": "USDJPY", "action": "BUY"})
        assert record["action"] == "buy"

    def test_falls_back_to_side(self):
        """action が無ければ side を使うこと"""
        record, _ = save({"symbol": "USDJPY", "side": "SELL"})
        assert record["action"] == "sell"

    def test_defaults_to_alert(self):
        """売買方向が無ければ alert として扱うこと"""
        record, _ = save({"symbol": "USDJPY"})
        assert record["action"] == "alert"

    def test_reads_the_price(self):
        """price を float で取り込むこと"""
        record, _ = save({"symbol": "USDJPY", "price": "151.25"})
        assert record["price"] == 151.25

    def test_falls_back_to_close(self):
        """price が無ければ close を使うこと"""
        record, _ = save({"symbol": "USDJPY", "close": 150.0})
        assert record["price"] == 150.0

    def test_missing_price_is_none(self):
        """価格が無ければ None にすること"""
        record, _ = save({"symbol": "USDJPY"})
        assert record["price"] is None

    def test_strategy_is_truncated(self):
        """戦略名は 100 文字までに切り詰めること"""
        record, _ = save({"symbol": "USDJPY", "strategy": "s" * 200})
        assert len(record["strategy"]) == 100

    def test_message_is_truncated(self):
        """メッセージは 500 文字までに切り詰めること"""
        record, _ = save({"symbol": "USDJPY", "message": "m" * 1000})
        assert len(record["message"]) == 500

    def test_records_source_and_timestamp(self):
        """受信元と受信時刻を記録すること"""
        record, _ = save({"symbol": "USDJPY"})

        assert record["source"] == "tradingview"
        assert datetime.fromisoformat(record["received_at"])

    def test_records_the_tenant(self):
        """テナント ID を記録すること"""
        record, _ = save({"symbol": "USDJPY"}, tenant_id=42)
        assert record["tenant_id"] == 42


class TestSaveSignalPersistence:
    """save_signal() の永続化テスト"""

    def test_persists_to_the_database(self):
        """DB へ保存して ID を返すこと"""
        record, session = save({"symbol": "USDJPY", "action": "buy"})

        session.add.assert_called_once()
        session.commit.assert_called_once()
        assert record["id"] == 7

    def test_falls_back_to_memory(self):
        """DB 保存に失敗したらメモリへ退避すること（シグナルを失わない）"""
        record, session = save({"symbol": "USDJPY"}, fail=True)

        session.rollback.assert_called_once()
        assert service._memory_signals[0]["symbol"] == "USDJPY"
        assert record["id"] == 1

    def test_memory_fallback_is_bounded(self):
        """メモリ保持件数に上限があること（メモリリーク防止）"""
        for i in range(service._MAX_MEMORY + 20):
            save({"symbol": "USDJPY"}, fail=True)

        assert len(service._memory_signals) == service._MAX_MEMORY

    def test_memory_fallback_keeps_newest_first(self):
        """メモリ上は新しいシグナルを先頭に置くこと"""
        save({"symbol": "USDJPY"}, fail=True)
        save({"symbol": "EURUSD"}, fail=True)

        assert service._memory_signals[0]["symbol"] == "EURUSD"


class TestListSignals:
    """list_signals() のテスト"""

    def _session(self, rows):
        session = MagicMock()
        session.execute.return_value.scalars.return_value.all.return_value = rows
        return session

    def _row(self, symbol="USDJPY"):
        return SimpleNamespace(id=1, symbol=symbol, action="buy", price=151.0,
                               strategy="RSI", message="", tenant_id=1,
                               source="tradingview",
                               received_at=datetime.now(timezone.utc))

    def test_maps_rows_to_dicts(self):
        """シグナル行を辞書へ変換すること"""
        with patch("src.tradingview.service.SessionLocal",
                   return_value=self._session([self._row()])):
            signals = list_signals()

        assert signals[0]["symbol"] == "USDJPY"
        assert signals[0]["action"] == "buy"

    def test_empty_result(self):
        """シグナルが無ければ空リストを返すこと"""
        with patch("src.tradingview.service.SessionLocal", return_value=self._session([])):
            assert list_signals() == []

    def test_timestamps_are_iso_strings(self):
        """受信日時を ISO 文字列で返すこと"""
        with patch("src.tradingview.service.SessionLocal",
                   return_value=self._session([self._row()])):
            assert isinstance(list_signals()[0]["received_at"], str)

    def test_symbol_filter_is_uppercased(self):
        """シンボルのフィルタを大文字へ正規化すること"""
        session = self._session([])
        with patch("src.tradingview.service.SessionLocal", return_value=session):
            list_signals(symbol="usdjpy")

        compiled = str(session.execute.call_args[0][0].compile(
            compile_kwargs={"literal_binds": True}))
        assert "USDJPY" in compiled

    def test_falls_back_to_memory(self):
        """DB が使えなければメモリ上のシグナルを返すこと"""
        service._memory_signals = [{"symbol": "USDJPY", "tenant_id": 1}]
        session = MagicMock()
        session.execute.side_effect = OSError("db down")

        with patch("src.tradingview.service.SessionLocal", return_value=session):
            assert list_signals(tenant_id=1)[0]["symbol"] == "USDJPY"

    def test_memory_fallback_filters_by_symbol(self):
        """メモリフォールバックでもシンボルで絞り込むこと"""
        service._memory_signals = [{"symbol": "USDJPY"}, {"symbol": "EURUSD"}]
        session = MagicMock()
        session.execute.side_effect = OSError("db down")

        with patch("src.tradingview.service.SessionLocal", return_value=session):
            assert [s["symbol"] for s in list_signals(symbol="eurusd")] == ["EURUSD"]

    def test_memory_fallback_respects_the_limit(self):
        """メモリフォールバックでも件数上限を守ること"""
        service._memory_signals = [{"symbol": "USDJPY"} for _ in range(10)]
        session = MagicMock()
        session.execute.side_effect = OSError("db down")

        with patch("src.tradingview.service.SessionLocal", return_value=session):
            assert len(list_signals(limit=3)) == 3
