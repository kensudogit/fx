"""ウォークフォワード分析 — src.backtest.walk_forward のテスト

IS（学習）/ OOS（検証）ウィンドウの生成と、頑健性判定を検証する。
"""

from unittest.mock import patch

import pytest

from src.backtest.walk_forward import run_walk_forward
from tests.conftest import make_ohlcv


def with_timestamp(df):
    """timestamp 列を付けた OHLCV を返す。"""
    out = df.copy()
    out["timestamp"] = out.index
    return out


def run(df=None, **kwargs):
    """市場データをモックして実行する。"""
    data = with_timestamp(df if df is not None else make_ohlcv(n=400))
    with patch("src.backtest.walk_forward.get_ohlcv_data", return_value=(data, "database")):
        return run_walk_forward("USDJPY", **kwargs)


class TestWindowGeneration:
    """ウィンドウ生成のテスト"""

    def test_succeeds_with_enough_data(self):
        """十分なデータがあれば成功すること"""
        assert run()["status"] == "success"

    def test_insufficient_data_is_reported(self):
        """データが足りなければエラーとして返すこと"""
        result = run(df=make_ohlcv(n=100))

        assert result["status"] == "error"
        assert "データ不足" in result["message"]

    def test_generates_multiple_windows(self):
        """複数のウィンドウを生成すること"""
        assert len(run()["windows"]) > 1

    def test_window_count_depends_on_the_step(self):
        """ステップ幅が小さいほどウィンドウ数が増えること"""
        fine = run(step_bars=20)["summary"]["window_count"]
        coarse = run(step_bars=80)["summary"]["window_count"]
        assert fine > coarse

    def test_windows_are_numbered_sequentially(self):
        """ウィンドウ番号が 1 から連番であること"""
        windows = run()["windows"]
        assert [w["window"] for w in windows] == list(range(1, len(windows) + 1))

    def test_each_window_reports_its_period(self):
        """各ウィンドウが学習・検証の期間を返すこと"""
        window = run()["windows"][0]
        for key in ("train_start", "train_end", "test_start", "test_end"):
            assert len(window[key]) == 10  # YYYY-MM-DD

    def test_test_period_follows_the_training_period(self):
        """検証期間は学習期間の直後であること（データリーク防止）"""
        window = run()["windows"][0]
        assert window["train_end"] <= window["test_start"]

    def test_each_window_has_both_result_sets(self):
        """各ウィンドウが IS / OOS の結果を持つこと"""
        window = run()["windows"][0]
        for section in ("in_sample", "out_of_sample"):
            assert {"win_rate", "total_trades", "avg_return_pct"} <= set(window[section])

    def test_echoes_the_window_settings(self):
        """指定したウィンドウ設定を返すこと"""
        result = run(train_bars=100, test_bars=30, step_bars=30)

        assert result["train_bars"] == 100
        assert result["test_bars"] == 30
        assert result["step_bars"] == 30


class TestSummary:
    """サマリー計算のテスト"""

    def test_reports_average_win_rates(self):
        """IS / OOS の平均勝率を返すこと"""
        summary = run()["summary"]

        assert 0 <= summary["avg_in_sample_win_rate"] <= 100
        assert 0 <= summary["avg_out_of_sample_win_rate"] <= 100

    def test_degradation_is_the_difference(self):
        """劣化幅が IS − OOS であること"""
        summary = run()["summary"]
        expected = round(summary["avg_in_sample_win_rate"]
                         - summary["avg_out_of_sample_win_rate"], 1)
        assert summary["is_oos_degradation_pct"] == expected

    def test_robustness_is_one_of_three_levels(self):
        """頑健性は 3 段階のいずれかであること"""
        assert run()["summary"]["robustness"] in ("good", "moderate", "weak")

    def test_robustness_label_is_japanese(self):
        """頑健性のラベルが日本語であること"""
        assert run()["summary"]["robustness_label"]

    def test_window_count_matches_the_list(self):
        """ウィンドウ数がリストの長さと一致すること"""
        result = run()
        assert result["summary"]["window_count"] == len(result["windows"])

    def test_normalizes_the_symbol(self):
        """シンボルを大文字化すること"""
        data = with_timestamp(make_ohlcv(n=400))
        with patch("src.backtest.walk_forward.get_ohlcv_data", return_value=(data, "database")):
            assert run_walk_forward("usdjpy")["symbol"] == "USDJPY"

    def test_reports_the_data_source(self):
        """データソースを返すこと"""
        assert run()["source"] == "database"
