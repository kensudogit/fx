"""Backtrader バックテスト — src.backtest.backtrader_runner のテスト

実際に backtrader を動かして戦略実行を検証しつつ、
未インストール・データ不足・例外時のフォールバックも確認する。
"""

import sys
from unittest.mock import patch

import pytest

from src.backtest.backtrader_runner import run_backtrader_backtest
from tests.conftest import make_ohlcv


def with_timestamp(df):
    """backtrader が要求する timestamp 列を付けた OHLCV を返す。"""
    out = df.copy()
    out["timestamp"] = out.index
    return out


class TestRunBacktraderBacktest:
    """run_backtrader_backtest() のテスト"""

    def test_runs_and_reports_results(self, ohlcv):
        """バックテストを実行して結果を返すこと"""
        with patch("src.backtest.backtrader_runner.get_ohlcv_data",
                   return_value=(with_timestamp(ohlcv), "database")):
            result = run_backtrader_backtest("USDJPY")

        assert result["status"] == "success"
        assert result["engine"] == "backtrader"
        assert result["strategy"] == "RSI(30/70) + MACD crossover"

    def test_normalizes_the_symbol(self, ohlcv):
        """シンボルを大文字化すること"""
        with patch("src.backtest.backtrader_runner.get_ohlcv_data",
                   return_value=(with_timestamp(ohlcv), "database")):
            assert run_backtrader_backtest("usdjpy")["symbol"] == "USDJPY"

    def test_reports_capital_and_return(self, ohlcv):
        """初期資金・最終評価額・リターンを返すこと"""
        with patch("src.backtest.backtrader_runner.get_ohlcv_data",
                   return_value=(with_timestamp(ohlcv), "database")):
            result = run_backtrader_backtest("USDJPY", cash=50_000)

        assert result["initial_cash"] == 50_000
        assert result["final_value"] > 0
        assert isinstance(result["total_return_pct"], float)

    def test_return_matches_the_values(self, ohlcv):
        """リターン率が初期資金と最終評価額から算出されていること"""
        with patch("src.backtest.backtrader_runner.get_ohlcv_data",
                   return_value=(with_timestamp(ohlcv), "database")):
            result = run_backtrader_backtest("USDJPY", cash=10_000)

        expected = (result["final_value"] - 10_000) / 10_000 * 100
        assert result["total_return_pct"] == pytest.approx(round(expected, 2), abs=0.01)

    def test_reports_the_bar_count(self, ohlcv):
        """評価に使ったバー数を返すこと"""
        with patch("src.backtest.backtrader_runner.get_ohlcv_data",
                   return_value=(with_timestamp(ohlcv), "database")):
            assert run_backtrader_backtest("USDJPY")["bars"] > 0

    def test_insufficient_data_is_reported(self):
        """データが少なければエラーとして返すこと（例外にしない）"""
        short = with_timestamp(make_ohlcv(n=30))
        with patch("src.backtest.backtrader_runner.get_ohlcv_data",
                   return_value=(short, "sample")):
            result = run_backtrader_backtest("USDJPY")

        assert result["status"] == "error"
        assert result["message"] == "データ不足"

    def test_missing_backtrader_is_reported(self, ohlcv):
        """backtrader が未インストールでも例外にせずメッセージを返すこと"""
        with patch.dict(sys.modules, {"backtrader": None}):
            result = run_backtrader_backtest("USDJPY")

        assert result["status"] == "error"
        assert "backtrader" in result["message"]

    def test_unexpected_errors_are_caught(self):
        """想定外のエラーもメッセージとして返すこと"""
        with patch("src.backtest.backtrader_runner.get_ohlcv_data",
                   side_effect=RuntimeError("db down")):
            result = run_backtrader_backtest("USDJPY")

        assert result["status"] == "error"
        assert "db down" in result["message"]

    def test_reports_the_data_source(self, ohlcv):
        """データソースを返すこと"""
        with patch("src.backtest.backtrader_runner.get_ohlcv_data",
                   return_value=(with_timestamp(ohlcv), "yahoo_finance")):
            assert run_backtrader_backtest("USDJPY")["source"] == "yahoo_finance"
