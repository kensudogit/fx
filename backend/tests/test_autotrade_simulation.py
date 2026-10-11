"""運用前シミュレーション — src.autotrade.simulation のテスト

市場データ取得はモックへ差し替え、グレード判定・証拠金試算・
データ不足時のフォールバックを検証する。
"""

from unittest.mock import patch

import pandas as pd
import pytest

from src.autotrade.simulation import (
    _assessment_summary,
    _estimate_max_loss_streak,
    simulate_strategy,
)
from tests.conftest import make_ohlcv


def simulate(df: pd.DataFrame, backtest: dict | None = None, **kwargs) -> dict:
    """OHLCV とバックテスト結果を差し込んでシミュレーションを実行する。"""
    patches = [patch("src.autotrade.simulation.get_ohlcv_data", return_value=(df, "database"))]
    if backtest is not None:
        patches.append(patch("src.autotrade.simulation.backtest_signals", return_value=backtest))
    with patches[0]:
        if len(patches) > 1:
            with patches[1]:
                return simulate_strategy("USDJPY", **kwargs)
        return simulate_strategy("USDJPY", **kwargs)


def bt(win_rate=50.0, trades=30, avg_return=0.1) -> dict:
    """バックテスト結果を組み立てる。"""
    return {"total_trades": trades, "win_rate": win_rate, "avg_return_pct": avg_return,
            "buy_trades": trades // 2, "sell_trades": trades - trades // 2}


class TestEstimateMaxLossStreak:
    """_estimate_max_loss_streak() のテスト"""

    @pytest.mark.parametrize("win_rate,streak", [
        (70, 3), (60, 3), (59, 5), (50, 5), (49, 7), (0, 7),
    ])
    def test_streak_by_win_rate(self, win_rate, streak):
        """勝率が低いほど想定連敗数が増えること"""
        assert _estimate_max_loss_streak(win_rate) == streak

    def test_is_monotonic(self):
        """勝率が上がるほど連敗想定は減る（増えない）こと"""
        streaks = [_estimate_max_loss_streak(w) for w in (30, 50, 70)]
        assert streaks == sorted(streaks, reverse=True)


class TestAssessmentSummary:
    """_assessment_summary() のテスト"""

    def test_too_few_trades(self):
        """取引数が少なければデータ不足と伝えること"""
        assert "データ不足" in _assessment_summary("A", 60.0, trades=5)

    @pytest.mark.parametrize("grade", ["A", "B"])
    def test_passing_grades(self, grade):
        """A / B グレードは運用開始条件を満たすと伝えること"""
        assert "条件を満たしています" in _assessment_summary(grade, 55.0, trades=30)

    @pytest.mark.parametrize("grade", ["C", "D"])
    def test_failing_grades(self, grade):
        """C / D グレードは設定変更を促すこと"""
        assert "推奨します" in _assessment_summary(grade, 40.0, trades=30)

    def test_includes_the_win_rate(self):
        """勝率を文面に含めること"""
        assert "55.0%" in _assessment_summary("A", 55.0, trades=30)


class TestSimulateStrategy:
    """simulate_strategy() のテスト"""

    def test_returns_expected_sections(self, ohlcv):
        """結果セクションが揃っていること"""
        result = simulate(ohlcv)
        assert set(result) == {
            "symbol", "source", "period_days", "preset_id",
            "backtest", "position_sizing", "capital", "assessment",
        }

    def test_normalizes_the_symbol(self, ohlcv):
        """シンボルを大文字に正規化すること"""
        with patch("src.autotrade.simulation.get_ohlcv_data", return_value=(ohlcv, "database")):
            assert simulate_strategy("usdjpy")["symbol"] == "USDJPY"

    def test_reports_source_and_period(self, ohlcv):
        """データソースと期間を返すこと"""
        result = simulate(ohlcv, days=180)
        assert result["source"] == "database"
        assert result["period_days"] == 180

    @pytest.mark.parametrize("win_rate,grade", [
        (60.0, "A"), (55.0, "A"), (50.0, "B"), (48.0, "B"),
        (45.0, "C"), (42.0, "C"), (40.0, "D"), (0.0, "D"),
    ])
    def test_grade_thresholds(self, ohlcv, win_rate, grade):
        """勝率に応じたグレードを付けること"""
        assert simulate(ohlcv, backtest=bt(win_rate))["assessment"]["grade"] == grade

    def test_ready_to_deploy_requires_win_rate_and_volume(self, ohlcv):
        """運用可否は勝率 45% 以上かつ 20 取引以上を条件とすること"""
        assert simulate(ohlcv, backtest=bt(50.0, 30))["assessment"]["ready_to_deploy"] is True
        assert simulate(ohlcv, backtest=bt(50.0, 10))["assessment"]["ready_to_deploy"] is False
        assert simulate(ohlcv, backtest=bt(40.0, 30))["assessment"]["ready_to_deploy"] is False

    def test_recommended_margin_exceeds_the_balance(self, ohlcv):
        """推奨証拠金は入力残高以上になること（連敗を考慮）"""
        capital = simulate(ohlcv, backtest=bt(50.0), account_balance=10_000)["capital"]
        assert capital["recommended_margin_usd"] >= capital["input_balance"]

    def test_safe_margin_is_1_5x_recommended(self, ohlcv):
        """安全証拠金は推奨の 1.5 倍であること"""
        capital = simulate(ohlcv, backtest=bt(50.0))["capital"]
        assert capital["safe_margin_usd"] == round(capital["recommended_margin_usd"] * 1.5, 0)

    def test_lower_win_rate_requires_more_margin(self, ohlcv):
        """勝率が低いほど必要証拠金が増えること"""
        high = simulate(ohlcv, backtest=bt(65.0))["capital"]["recommended_margin_usd"]
        low = simulate(ohlcv, backtest=bt(40.0))["capital"]["recommended_margin_usd"]
        assert low > high

    def test_includes_position_sizing(self, ohlcv):
        """ポジションサイズ試算を含むこと"""
        sizing = simulate(ohlcv, backtest=bt())["position_sizing"]
        assert sizing["recommended_lots"] > 0
        assert sizing["stop_pips"] > 0

    def test_applies_the_preset(self, ohlcv):
        """指定したプリセット ID を記録すること"""
        assert simulate(ohlcv, backtest=bt(), preset_id="aggressive")["preset_id"] == "aggressive"

    def test_works_without_a_preset(self, ohlcv):
        """プリセット未指定でも動作すること"""
        assert simulate(ohlcv, backtest=bt(), preset_id=None)["preset_id"] is None


class TestInsufficientData:
    """データ不足時のフォールバックテスト"""

    def test_returns_grade_d_without_crashing(self):
        """データが少なすぎても例外を投げず D 評価を返すこと"""
        tiny = make_ohlcv(n=10)
        with patch("src.autotrade.simulation.get_ohlcv_data", return_value=(tiny, "sample")):
            result = simulate_strategy("USDJPY")

        assert result["assessment"]["grade"] == "D"
        assert result["assessment"]["ready_to_deploy"] is False
        assert "データ不足" in result["assessment"]["summary"]

    def test_backtest_is_zeroed(self):
        """バックテスト結果はゼロで返すこと"""
        tiny = make_ohlcv(n=10)
        with patch("src.autotrade.simulation.get_ohlcv_data", return_value=(tiny, "sample")):
            result = simulate_strategy("USDJPY")

        assert result["backtest"] == {"total_trades": 0, "win_rate": 0, "avg_return_pct": 0}

    def test_capital_falls_back_to_the_input_balance(self):
        """証拠金試算は入力残高をそのまま使うこと"""
        tiny = make_ohlcv(n=10)
        with patch("src.autotrade.simulation.get_ohlcv_data", return_value=(tiny, "sample")):
            capital = simulate_strategy("USDJPY", account_balance=25_000)["capital"]

        assert capital["recommended_margin_usd"] == 25_000
        assert capital["safe_margin_usd"] == 25_000 * 1.5
        assert "データ不足" in capital["note"]

    def test_retries_with_a_longer_window(self):
        """短いデータしか得られない場合はより長い期間で再取得すること"""
        short = make_ohlcv(n=50)
        long = make_ohlcv(n=200)
        with patch("src.autotrade.simulation.get_ohlcv_data",
                   side_effect=[(short, "database"), (long, "database")]) as get_data:
            simulate_strategy("USDJPY", days=60)

        assert get_data.call_count == 2
        assert get_data.call_args_list[1][0][1] == 200
