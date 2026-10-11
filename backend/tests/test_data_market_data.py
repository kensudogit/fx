"""市場データ取得 — src.data.market_data のテスト

Yahoo Finance と DB はモックへ差し替え、
DB → Yahoo → サンプルデータのフォールバック階層を検証する。
"""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from src.data.market_data import (
    YAHOO_HEADERS,
    YAHOO_TICKERS,
    fetch_from_yahoo,
    fetch_from_yahoo_chart_api,
    fetch_from_yfinance,
    get_ohlcv_data,
    load_ohlcv_from_db,
    save_ohlcv_to_db,
    sync_symbol_data,
)


def chart_payload(n=3, close=None):
    """Yahoo Chart API のレスポンス構造を組み立てる。"""
    close = close if close is not None else [151.0 + i for i in range(n)]
    return {
        "chart": {
            "result": [
                {
                    "timestamp": [1_700_000_000 + i * 86_400 for i in range(n)],
                    "indicators": {
                        "quote": [
                            {
                                "open": [None if c is None else c - 0.2 for c in close],
                                "high": [None if c is None else c + 0.3 for c in close],
                                "low": [None if c is None else c - 0.4 for c in close],
                                "close": list(close),
                                "volume": [1000] * n,
                            }
                        ]
                    },
                }
            ]
        }
    }


def http_client(payload=None, error=None):
    """httpx.Client のコンテキストマネージャをモックする。"""
    response = MagicMock()
    response.json.return_value = payload or {}
    response.raise_for_status = MagicMock()
    client = MagicMock()
    if error is not None:
        client.get.side_effect = error
    else:
        client.get.return_value = response
    ctx = MagicMock()
    ctx.__enter__.return_value = client
    ctx.__exit__.return_value = False
    return ctx, client


def failing_fetcher(message):
    """__name__ を持つ失敗フェッチャー（ログ出力で参照されるため）。"""
    mock = MagicMock(side_effect=ValueError(message))
    mock.__name__ = "fetcher"
    return mock


def db_record(ts, close=151.0):
    """OHLCVRecord 相当のスタブ。"""
    return SimpleNamespace(timestamp=ts, open=close - 0.1, high=close + 0.2,
                           low=close - 0.3, close=close, volume=1000)


def query_db(records):
    """db.query(...).filter(...).order_by(...).limit(...).all() を再現する。"""
    db = MagicMock()
    db.query.return_value.filter.return_value.order_by.return_value.limit.return_value.all.return_value = records
    return db


class TestTickerTable:
    """YAHOO_TICKERS / YAHOO_HEADERS のテスト"""

    def test_maps_symbols_to_yahoo_tickers(self):
        """通貨ペアを Yahoo のティッカー形式へ変換できること"""
        assert YAHOO_TICKERS["USDJPY"] == "USDJPY=X"
        assert all(t.endswith("=X") for t in YAHOO_TICKERS.values())

    def test_sends_a_user_agent(self):
        """User-Agent を送ること（無いと 403/429 が返るため）"""
        assert "User-Agent" in YAHOO_HEADERS


class TestFetchFromYahooChartApi:
    """fetch_from_yahoo_chart_api() のテスト"""

    def test_builds_an_ohlcv_frame(self):
        """レスポンスから OHLCV の DataFrame を組み立てること"""
        ctx, _ = http_client(chart_payload(3))
        with patch("src.data.market_data.httpx.Client", return_value=ctx):
            df = fetch_from_yahoo_chart_api("USDJPY", days=10)

        assert list(df.columns) == ["timestamp", "open", "high", "low", "close", "volume"]
        assert len(df) == 3

    def test_unknown_symbol_raises(self):
        """未対応シンボルは ValueError にすること"""
        with pytest.raises(ValueError, match="Unknown symbol"):
            fetch_from_yahoo_chart_api("XAUUSD")

    def test_symbol_is_case_insensitive(self):
        """小文字のシンボルも扱えること"""
        ctx, client = http_client(chart_payload(2))
        with patch("src.data.market_data.httpx.Client", return_value=ctx):
            fetch_from_yahoo_chart_api("usdjpy")

        assert "USDJPY=X" in client.get.call_args[0][0]

    def test_missing_result_raises(self):
        """チャートデータが無ければ ValueError にすること"""
        ctx, _ = http_client({"chart": {"result": []}})
        with patch("src.data.market_data.httpx.Client", return_value=ctx):
            with pytest.raises(ValueError, match="No chart data"):
                fetch_from_yahoo_chart_api("USDJPY")

    def test_empty_timestamps_raise(self):
        """タイムスタンプが空なら ValueError にすること"""
        payload = chart_payload(1)
        payload["chart"]["result"][0]["timestamp"] = []
        ctx, _ = http_client(payload)
        with patch("src.data.market_data.httpx.Client", return_value=ctx):
            with pytest.raises(ValueError, match="Empty timestamps"):
                fetch_from_yahoo_chart_api("USDJPY")

    def test_rows_without_close_are_dropped(self):
        """終値が欠けた足（市場クローズ等）を除外すること"""
        ctx, _ = http_client(chart_payload(4, close=[151.0, None, 152.0, None]))
        with patch("src.data.market_data.httpx.Client", return_value=ctx):
            df = fetch_from_yahoo_chart_api("USDJPY")

        assert len(df) == 2
        assert df["close"].tolist() == [151.0, 152.0]

    def test_all_rows_invalid_raises(self):
        """有効な足が 1 本も無ければ ValueError にすること"""
        ctx, _ = http_client(chart_payload(2, close=[None, None]))
        with patch("src.data.market_data.httpx.Client", return_value=ctx):
            with pytest.raises(ValueError, match="No valid OHLCV rows"):
                fetch_from_yahoo_chart_api("USDJPY")

    def test_volume_is_integral(self):
        """出来高は整数に変換すること"""
        ctx, _ = http_client(chart_payload(2))
        with patch("src.data.market_data.httpx.Client", return_value=ctx):
            df = fetch_from_yahoo_chart_api("USDJPY")

        assert df["volume"].dtype.kind == "i"

    def test_result_is_limited_to_the_requested_days(self):
        """要求日数を超える足は切り捨てること"""
        ctx, _ = http_client(chart_payload(10))
        with patch("src.data.market_data.httpx.Client", return_value=ctx):
            df = fetch_from_yahoo_chart_api("USDJPY", days=4)

        assert len(df) == 4

    @pytest.mark.parametrize("days,expected", [(200, "1y"), (400, "2y")])
    def test_daily_range_widens_for_long_requests(self, days, expected):
        """1 年を超える要求では 2 年分のレンジを指定すること"""
        ctx, client = http_client(chart_payload(2))
        with patch("src.data.market_data.httpx.Client", return_value=ctx):
            fetch_from_yahoo_chart_api("USDJPY", days=days)

        assert client.get.call_args.kwargs["params"]["range"] == expected

    def test_four_hour_uses_a_sixty_day_range(self):
        """4 時間足は 60 日レンジで取得すること"""
        ctx, client = http_client(chart_payload(2))
        with patch("src.data.market_data.httpx.Client", return_value=ctx):
            fetch_from_yahoo_chart_api("USDJPY", days=30, interval="4h")

        params = client.get.call_args.kwargs["params"]
        assert params == {"interval": "4h", "range": "60d"}

    def test_http_errors_propagate(self):
        """HTTP エラーは呼び出し元へ伝播すること"""
        ctx, _ = http_client(error=OSError("network down"))
        with patch("src.data.market_data.httpx.Client", return_value=ctx):
            with pytest.raises(OSError):
                fetch_from_yahoo_chart_api("USDJPY")


class TestFetchFromYfinance:
    """fetch_from_yfinance() のテスト"""

    def _raw(self, n=3):
        return pd.DataFrame({
            "Date": pd.date_range("2026-01-01", periods=n, freq="D"),
            "Open": [151.0] * n, "High": [151.5] * n,
            "Low": [150.5] * n, "Close": [151.2] * n, "Volume": [1000] * n,
        })

    def test_normalises_yfinance_columns(self):
        """yfinance の列名を小文字へ正規化すること"""
        with patch("src.data.market_data.yf.download", return_value=self._raw()):
            df = fetch_from_yfinance("USDJPY", days=10)

        assert list(df.columns) == ["timestamp", "open", "high", "low", "close", "volume"]

    def test_unknown_symbol_raises(self):
        """未対応シンボルは ValueError にすること"""
        with pytest.raises(ValueError, match="Unknown symbol"):
            fetch_from_yfinance("XAUUSD")

    def test_empty_download_raises(self):
        """データが空なら ValueError にすること"""
        with patch("src.data.market_data.yf.download", return_value=pd.DataFrame()):
            with pytest.raises(ValueError, match="No data returned"):
                fetch_from_yfinance("USDJPY")

    def test_flattens_multiindex_columns(self):
        """複数ティッカー取得時の MultiIndex 列を平坦化すること"""
        raw = self._raw()
        raw.columns = pd.MultiIndex.from_product([raw.columns, ["USDJPY=X"]])
        with patch("src.data.market_data.yf.download", return_value=raw):
            df = fetch_from_yfinance("USDJPY", days=10)

        assert df["close"].iloc[-1] == 151.2

    @pytest.mark.parametrize("days,interval,expected", [
        (200, "1d", "1y"), (400, "1d", "2y"), (30, "4h", "60d"),
    ])
    def test_period_matches_the_request(self, days, interval, expected):
        """足種と日数に応じた期間を指定すること"""
        with patch("src.data.market_data.yf.download", return_value=self._raw()) as download:
            fetch_from_yfinance("USDJPY", days=days, interval=interval)

        assert download.call_args.kwargs["period"] == expected

    def test_result_is_limited_to_the_requested_days(self):
        """要求日数を超える足は切り捨てること"""
        with patch("src.data.market_data.yf.download", return_value=self._raw(10)):
            assert len(fetch_from_yfinance("USDJPY", days=3)) == 3


class TestFetchFromYahoo:
    """fetch_from_yahoo() のテスト（フォールバック付きラッパー）"""

    def test_prefers_the_chart_api(self):
        """まず Chart API を試すこと"""
        frame = pd.DataFrame({"close": [151.0]})
        with patch("src.data.market_data.fetch_from_yahoo_chart_api", return_value=frame), \
             patch("src.data.market_data.fetch_from_yfinance") as yfinance:
            result = fetch_from_yahoo("USDJPY")

        assert result is frame
        yfinance.assert_not_called()

    def test_falls_back_to_yfinance(self):
        """Chart API が失敗したら yfinance を試すこと"""
        frame = pd.DataFrame({"close": [151.0]})
        with patch("src.data.market_data.fetch_from_yahoo_chart_api",
                   new=failing_fetcher("chart down")), \
             patch("src.data.market_data.fetch_from_yfinance", return_value=frame):
            assert fetch_from_yahoo("USDJPY") is frame

    def test_all_failures_raise_with_details(self):
        """全て失敗したら各エラーを含めて ValueError にすること"""
        with patch("src.data.market_data.fetch_from_yahoo_chart_api",
                   new=failing_fetcher("chart down")), \
             patch("src.data.market_data.fetch_from_yfinance",
                   new=failing_fetcher("yf down")):
            with pytest.raises(ValueError) as exc:
                fetch_from_yahoo("USDJPY")

        assert "chart down" in str(exc.value)
        assert "yf down" in str(exc.value)

    def test_arguments_are_forwarded(self):
        """日数と足種をフェッチャーへ渡すこと"""
        with patch("src.data.market_data.fetch_from_yahoo_chart_api",
                   return_value=pd.DataFrame()) as chart:
            fetch_from_yahoo("USDJPY", 90, "4h")

        assert chart.call_args[0] == ("USDJPY", 90, "4h")


class TestSaveOhlcvToDb:
    """save_ohlcv_to_db() のテスト"""

    def _frame(self, n=3):
        return pd.DataFrame({
            "timestamp": pd.date_range("2026-01-01", periods=n, freq="D"),
            "open": [151.0] * n, "high": [151.5] * n,
            "low": [150.5] * n, "close": [151.2] * n, "volume": [1000] * n,
        })

    def test_returns_the_saved_row_count(self):
        """保存した件数を返すこと"""
        db = MagicMock()
        assert save_ohlcv_to_db(db, "USDJPY", self._frame(3)) == 3

    def test_commits_the_transaction(self):
        """変更をコミットすること"""
        db = MagicMock()
        save_ohlcv_to_db(db, "USDJPY", self._frame())

        db.execute.assert_called_once()
        db.commit.assert_called_once()

    def test_empty_frame_touches_nothing(self):
        """空データでは DB を触らず 0 を返すこと"""
        db = MagicMock()
        empty = self._frame(0)

        assert save_ohlcv_to_db(db, "USDJPY", empty) == 0
        db.execute.assert_not_called()

    def test_upserts_on_the_unique_key(self):
        """(symbol, timestamp, timeframe) で upsert すること（重複を作らない）"""
        db = MagicMock()
        save_ohlcv_to_db(db, "USDJPY", self._frame())
        compiled = str(db.execute.call_args[0][0])

        assert "ON CONFLICT" in compiled.upper()

    def test_symbol_is_normalised(self):
        """シンボルを大文字へ正規化すること"""
        db = MagicMock()
        save_ohlcv_to_db(db, "usdjpy", self._frame(1))
        params = db.execute.call_args[0][0].compile().params

        assert "USDJPY" in params.values()


class TestLoadOhlcvFromDb:
    """load_ohlcv_from_db() のテスト"""

    def test_returns_none_when_empty(self):
        """レコードが無ければ None を返すこと"""
        assert load_ohlcv_from_db(query_db([]), "USDJPY") is None

    def test_builds_a_dataframe(self):
        """レコードを DataFrame へ変換すること"""
        records = [db_record(pd.Timestamp("2026-01-0%d" % i)) for i in (3, 2, 1)]
        df = load_ohlcv_from_db(query_db(records), "USDJPY")

        assert list(df.columns) == ["timestamp", "open", "high", "low", "close", "volume"]
        assert len(df) == 3

    def test_result_is_chronological(self):
        """DB は降順で取得するため昇順へ並べ直すこと"""
        records = [db_record(pd.Timestamp(f"2026-01-0{i}"), close=150.0 + i) for i in (3, 2, 1)]
        df = load_ohlcv_from_db(query_db(records), "USDJPY")

        assert df["timestamp"].is_monotonic_increasing
        assert df["close"].tolist() == [151.0, 152.0, 153.0]

    def test_limits_to_the_requested_days(self):
        """要求日数を limit として渡すこと"""
        db = query_db([])
        load_ohlcv_from_db(db, "USDJPY", days=45)
        limit = db.query.return_value.filter.return_value.order_by.return_value.limit

        limit.assert_called_once_with(45)


class TestGetOhlcvData:
    """get_ohlcv_data() のテスト"""

    def test_unknown_symbol_raises(self):
        """未対応シンボルは ValueError にすること"""
        with pytest.raises(ValueError, match="Unknown symbol"):
            get_ohlcv_data("XAUUSD")

    def test_prefers_the_database(self, ohlcv):
        """DB に十分なデータがあれば DB を使うこと"""
        with patch("src.data.market_data.SessionLocal", return_value=MagicMock()), \
             patch("src.data.market_data.load_ohlcv_from_db", return_value=ohlcv), \
             patch("src.data.market_data.fetch_from_yahoo") as yahoo:
            df, source = get_ohlcv_data("USDJPY", days=100)

        assert source == "database"
        assert len(df) == len(ohlcv)
        yahoo.assert_not_called()

    def test_thin_database_data_falls_through(self, ohlcv):
        """DB のデータが 30 本未満なら Yahoo から取り直すこと"""
        with patch("src.data.market_data.SessionLocal", return_value=MagicMock()), \
             patch("src.data.market_data.load_ohlcv_from_db", return_value=ohlcv.head(5)), \
             patch("src.data.market_data.fetch_from_yahoo", return_value=ohlcv), \
             patch("src.data.market_data.save_ohlcv_to_db"):
            _, source = get_ohlcv_data("USDJPY", days=200)

        assert source == "yahoo_finance"

    def test_database_errors_fall_through(self, ohlcv):
        """DB 読み込みが失敗しても Yahoo で継続すること"""
        with patch("src.data.market_data.SessionLocal", return_value=MagicMock()), \
             patch("src.data.market_data.load_ohlcv_from_db", side_effect=OSError("db down")), \
             patch("src.data.market_data.fetch_from_yahoo", return_value=ohlcv), \
             patch("src.data.market_data.save_ohlcv_to_db"):
            _, source = get_ohlcv_data("USDJPY")

        assert source == "yahoo_finance"

    def test_yahoo_results_are_cached(self, ohlcv):
        """Yahoo で取得したデータを DB に保存すること"""
        with patch("src.data.market_data.SessionLocal", return_value=MagicMock()), \
             patch("src.data.market_data.load_ohlcv_from_db", return_value=None), \
             patch("src.data.market_data.fetch_from_yahoo", return_value=ohlcv), \
             patch("src.data.market_data.save_ohlcv_to_db") as save:
            get_ohlcv_data("USDJPY")

        save.assert_called_once()

    def test_cache_write_failure_is_tolerated(self, ohlcv):
        """DB への保存に失敗してもデータは返すこと"""
        with patch("src.data.market_data.SessionLocal", return_value=MagicMock()), \
             patch("src.data.market_data.load_ohlcv_from_db", return_value=None), \
             patch("src.data.market_data.fetch_from_yahoo", return_value=ohlcv), \
             patch("src.data.market_data.save_ohlcv_to_db", side_effect=OSError("db down")):
            _, source = get_ohlcv_data("USDJPY")

        assert source == "yahoo_finance"

    def test_falls_back_to_sample_data(self):
        """DB も Yahoo も失敗したらサンプルデータを返すこと（画面を空にしない）"""
        with patch("src.data.market_data.SessionLocal", return_value=MagicMock()), \
             patch("src.data.market_data.load_ohlcv_from_db", return_value=None), \
             patch("src.data.market_data.fetch_from_yahoo", side_effect=ValueError("down")):
            df, source = get_ohlcv_data("USDJPY", days=60)

        assert source == "sample"
        assert len(df) == 60

    def test_intraday_bypasses_the_database(self, ohlcv):
        """4 時間足は DB キャッシュを使わず Yahoo から直接取ること"""
        with patch("src.data.market_data.fetch_from_yahoo", return_value=ohlcv) as yahoo, \
             patch("src.data.market_data.SessionLocal") as session_local:
            _, source = get_ohlcv_data("USDJPY", days=30, timeframe="4h")

        assert source == "yahoo_finance"
        assert yahoo.call_args.kwargs["interval"] == "4h"
        session_local.assert_not_called()

    def test_intraday_falls_back_to_sample_data(self):
        """4 時間足の取得失敗時もサンプルデータで代替すること"""
        with patch("src.data.market_data.fetch_from_yahoo", side_effect=ValueError("down")):
            df, source = get_ohlcv_data("USDJPY", days=200, timeframe="4h")

        assert source == "sample"
        assert len(df) == 90  # サンプルは最大 90 本に制限される

    def test_symbol_is_case_insensitive(self, ohlcv):
        """小文字のシンボルも扱えること"""
        with patch("src.data.market_data.SessionLocal", return_value=MagicMock()), \
             patch("src.data.market_data.load_ohlcv_from_db", return_value=ohlcv) as load:
            get_ohlcv_data("usdjpy", days=100)

        assert load.call_args[0][1] == "USDJPY"


class TestSyncSymbolData:
    """sync_symbol_data() のテスト"""

    def _frame(self):
        return pd.DataFrame({
            "timestamp": pd.date_range("2026-01-01", periods=3, freq="D"),
            "open": [151.0] * 3, "high": [151.5] * 3,
            "low": [150.5] * 3, "close": [151.0, 151.5, 152.25], "volume": [1000] * 3,
        })

    def test_returns_the_sync_summary(self):
        """同期結果の要約を返すこと"""
        with patch("src.data.market_data.fetch_from_yahoo", return_value=self._frame()), \
             patch("src.data.market_data.SessionLocal", return_value=MagicMock()), \
             patch("src.data.market_data.save_ohlcv_to_db", return_value=3):
            result = sync_symbol_data("USDJPY")

        assert result["symbol"] == "USDJPY"
        assert result["rows_synced"] == 3
        assert result["latest_close"] == 152.25
        assert result["source"] == "yahoo_finance"

    def test_latest_date_is_iso_formatted(self):
        """最新足の日時を ISO 8601 で返すこと"""
        with patch("src.data.market_data.fetch_from_yahoo", return_value=self._frame()), \
             patch("src.data.market_data.SessionLocal", return_value=MagicMock()), \
             patch("src.data.market_data.save_ohlcv_to_db", return_value=3):
            assert sync_symbol_data("USDJPY")["latest_date"].startswith("2026-01-03")

    def test_symbol_is_normalised(self):
        """シンボルを大文字へ正規化すること"""
        with patch("src.data.market_data.fetch_from_yahoo", return_value=self._frame()), \
             patch("src.data.market_data.SessionLocal", return_value=MagicMock()), \
             patch("src.data.market_data.save_ohlcv_to_db", return_value=3):
            assert sync_symbol_data("usdjpy")["symbol"] == "USDJPY"

    def test_fetch_failures_propagate(self):
        """取得に失敗したら例外を伝播すること（同期失敗を隠さない）"""
        with patch("src.data.market_data.fetch_from_yahoo", side_effect=ValueError("down")):
            with pytest.raises(ValueError):
                sync_symbol_data("USDJPY")

    def test_closes_the_session(self):
        """DB セッションを閉じること"""
        db = MagicMock()
        with patch("src.data.market_data.fetch_from_yahoo", return_value=self._frame()), \
             patch("src.data.market_data.SessionLocal", return_value=db), \
             patch("src.data.market_data.save_ohlcv_to_db", return_value=3):
            sync_symbol_data("USDJPY")

        db.close.assert_called_once()
