"""高度リスク管理 — src.analysis.risk_advanced のテスト

ドローダウン・VaR・ストレステスト・リスクスコアなどの純粋計算を中心に検証する。
"""

from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest

from src.analysis.risk_advanced import (
    _build_checklist,
    _compute_risk_score,
    _historical_var,
    _max_drawdown,
    _scenario_analysis,
    _stress_test,
    _trade_readiness,
    assess_advanced_risk,
    build_risk_report,
)


def dd(current=-2.0, maximum=-8.0) -> dict:
    """ドローダウン情報を組み立てる。"""
    return {"current_drawdown_pct": current, "max_drawdown_pct": maximum, "peak_price": 151.0}


def vol(atr_percent=0.8) -> dict:
    """ボラティリティ情報を組み立てる。"""
    return {"atr": 0.9, "atr_percent": atr_percent, "daily_volatility": 0.5}


class TestMaxDrawdown:
    """_max_drawdown() のテスト"""

    def test_monotonic_rise_has_no_drawdown(self):
        """一貫して上昇していればドローダウンは 0 であること"""
        result = _max_drawdown(pd.Series([100.0, 101.0, 102.0, 103.0]))
        assert result["max_drawdown_pct"] == 0.0
        assert result["current_drawdown_pct"] == 0.0

    def test_computes_the_worst_decline(self):
        """高値からの最大下落率を返すこと"""
        # 150 → 140 で -6.67%
        result = _max_drawdown(pd.Series([100.0, 150.0, 140.0, 145.0]))
        assert result["max_drawdown_pct"] == pytest.approx(-6.67, abs=0.01)

    def test_current_drawdown_is_from_the_running_peak(self):
        """現在のドローダウンは直近ピークからの下落率であること"""
        result = _max_drawdown(pd.Series([100.0, 150.0, 140.0]))
        assert result["current_drawdown_pct"] == pytest.approx(-6.67, abs=0.01)

    def test_recovery_resets_the_current_drawdown(self):
        """高値を更新すれば現在のドローダウンは 0 に戻ること"""
        result = _max_drawdown(pd.Series([100.0, 150.0, 140.0, 160.0]))
        assert result["current_drawdown_pct"] == 0.0
        assert result["max_drawdown_pct"] < 0

    def test_reports_the_peak_price(self):
        """直近のピーク価格を返すこと"""
        assert _max_drawdown(pd.Series([100.0, 150.0, 140.0]))["peak_price"] == 150.0

    def test_drawdowns_are_never_positive(self, ohlcv):
        """ドローダウンは 0 以下であること"""
        result = _max_drawdown(ohlcv["close"])
        assert result["max_drawdown_pct"] <= 0
        assert result["current_drawdown_pct"] <= 0


class TestHistoricalVar:
    """_historical_var() のテスト"""

    def test_insufficient_data_returns_zero(self):
        """観測数が足りなければ 0 を返すこと"""
        result = _historical_var(pd.Series([100.0] * 10), 10_000)
        assert result["daily_var_pct"] == 0.0
        assert result["daily_var_usd"] == 0.0

    def test_reports_observation_count(self, ohlcv):
        """観測数を返すこと"""
        result = _historical_var(ohlcv["close"], 10_000)
        assert result["observations"] == len(ohlcv) - 1

    def test_var_is_negative_in_percent(self, ohlcv):
        """VaR（%）は損失側なので負の値になること"""
        assert _historical_var(ohlcv["close"], 10_000)["daily_var_pct"] < 0

    def test_var_usd_is_positive(self, ohlcv):
        """VaR（USD）は損失額として正の値で返すこと"""
        assert _historical_var(ohlcv["close"], 10_000)["daily_var_usd"] > 0

    def test_var_scales_with_balance(self, ohlcv):
        """口座残高に比例した損失額になること"""
        small = _historical_var(ohlcv["close"], 10_000)["daily_var_usd"]
        large = _historical_var(ohlcv["close"], 100_000)["daily_var_usd"]
        assert large == pytest.approx(small * 10, rel=0.01)

    def test_higher_confidence_raises_the_var(self, ohlcv):
        """信頼水準を上げるほど VaR（損失見積もり）が大きくなること"""
        low = _historical_var(ohlcv["close"], 10_000, confidence=0.90)["daily_var_usd"]
        high = _historical_var(ohlcv["close"], 10_000, confidence=0.99)["daily_var_usd"]
        assert high >= low

    def test_confidence_is_echoed(self, ohlcv):
        """指定した信頼水準を返すこと"""
        assert _historical_var(ohlcv["close"], 10_000, confidence=0.99)["confidence"] == 0.99


class TestStressTest:
    """_stress_test() のテスト"""

    def test_computes_consecutive_losses(self):
        """連敗時の損失額と残高を計算すること"""
        result = _stress_test(10_000, 1.0, consecutive_losses=3)

        assert result["loss_per_trade_usd"] == 100.0
        assert result["total_loss_usd"] == 300.0
        assert result["remaining_balance_usd"] == 9_700.0
        assert result["remaining_pct"] == 97.0

    def test_higher_risk_costs_more(self):
        """リスク%が高いほど損失が大きいこと"""
        low = _stress_test(10_000, 1.0)["total_loss_usd"]
        high = _stress_test(10_000, 3.0)["total_loss_usd"]
        assert high == pytest.approx(low * 3)

    def test_more_losses_cost_more(self):
        """連敗数が増えるほど損失が大きいこと"""
        assert (_stress_test(10_000, 1.0, 5)["total_loss_usd"]
                > _stress_test(10_000, 1.0, 3)["total_loss_usd"])

    def test_interpretation_mentions_the_loss_ratio(self):
        """損失割合を日本語で説明すること"""
        assert "3.0%" in _stress_test(10_000, 1.0, 3)["interpretation"]

    def test_zero_risk_has_no_stress(self):
        """リスク 0% ならストレスシナリオなしと表現すること"""
        assert _stress_test(10_000, 0.0)["interpretation"] == "ストレスシナリオなし"

    def test_zero_balance_does_not_divide_by_zero(self):
        """残高 0 でも 0 除算にならないこと"""
        assert _stress_test(0, 1.0)["remaining_pct"] == 0

    def test_echoes_the_loss_count(self):
        """想定連敗数を返すこと"""
        assert _stress_test(10_000, 1.0, 5)["consecutive_losses"] == 5


class TestScenarioAnalysis:
    """_scenario_analysis() のテスト"""

    def test_bull_is_above_and_bear_below_the_base(self):
        """上振れ > ベース > 下振れ の順になること"""
        result = _scenario_analysis("USDJPY", 150.0, atr=0.9)
        assert result["bear"]["price"] < result["base"]["price"] < result["bull"]["price"]

    def test_base_is_the_current_price(self):
        """ベースシナリオは現在価格であること"""
        assert _scenario_analysis("USDJPY", 150.0, 0.9)["base"]["price"] == 150.0

    def test_wider_atr_widens_the_scenarios(self):
        """ATR が大きいほどシナリオの幅が広がること"""
        narrow = _scenario_analysis("USDJPY", 150.0, 0.5)
        wide = _scenario_analysis("USDJPY", 150.0, 2.0)
        assert wide["bull"]["price"] > narrow["bull"]["price"]

    def test_pip_changes_are_reported(self):
        """pips 単位の変動幅を返すこと"""
        result = _scenario_analysis("USDJPY", 150.0, 0.9)
        assert result["bull"]["change_pips"] > 0
        assert result["bear"]["change_pips"] < 0

    def test_includes_a_horizon_label(self):
        """想定期間のラベルを含めること"""
        assert _scenario_analysis("USDJPY", 150.0, 0.9)["horizon"]


class TestComputeRiskScore:
    """_compute_risk_score() のテスト"""

    def test_clean_conditions_score_high(self):
        """リスク要因が無ければ満点に近いスコアになること"""
        result = _compute_risk_score(dd(0, 0), vol(0.5), 1.0, "low", "trending")

        assert result["score"] == 100
        assert result["level"] == "low"

    def test_score_is_bounded(self):
        """スコアは 0〜100 に収まること"""
        worst = _compute_risk_score(dd(-30, -40), vol(5.0), 10.0, "high", "volatile")
        assert 0 <= worst["score"] <= 100

    def test_deep_drawdown_reduces_the_score(self):
        """ドローダウンが深いほど減点されること"""
        clean = _compute_risk_score(dd(0, 0), vol(0.5), 1.0, "low", "trending")["score"]
        drawn = _compute_risk_score(dd(-10, -20), vol(0.5), 1.0, "low", "trending")["score"]
        assert drawn < clean

    def test_high_volatility_reduces_the_score(self):
        """高ボラは減点されること"""
        calm = _compute_risk_score(dd(0, 0), vol(0.5), 1.0, "low", "trending")["score"]
        wild = _compute_risk_score(dd(0, 0), vol(2.5), 1.0, "low", "trending")["score"]
        assert wild < calm

    def test_excessive_risk_percent_reduces_the_score(self):
        """1 トレードのリスク%が高いほど減点されること"""
        safe = _compute_risk_score(dd(0, 0), vol(0.5), 1.0, "low", "trending")["score"]
        risky = _compute_risk_score(dd(0, 0), vol(0.5), 3.0, "low", "trending")["score"]
        assert risky < safe

    def test_event_risk_reduces_the_score(self):
        """イベントリスクが高いほど減点されること"""
        low = _compute_risk_score(dd(0, 0), vol(0.5), 1.0, "low", "trending")["score"]
        high = _compute_risk_score(dd(0, 0), vol(0.5), 1.0, "high", "trending")["score"]
        assert high < low

    def test_volatile_regime_reduces_the_score(self):
        """高ボラレジームでは減点されること"""
        trending = _compute_risk_score(dd(0, 0), vol(0.5), 1.0, "low", "trending")["score"]
        volatile = _compute_risk_score(dd(0, 0), vol(0.5), 1.0, "low", "volatile")["score"]
        assert volatile < trending

    @pytest.mark.parametrize("args,level", [
        ((dd(0, 0), vol(0.5), 1.0, "low", "trending"), "low"),
        ((dd(-10, -20), vol(1.6), 1.0, "low", "trending"), "medium"),
        ((dd(-10, -20), vol(2.5), 3.0, "high", "volatile"), "high"),
    ])
    def test_level_thresholds(self, args, level):
        """スコアに応じたリスクレベルを返すこと"""
        assert _compute_risk_score(*args)["level"] == level

    def test_label_is_actionable(self):
        """レベルごとに行動指針を示すこと"""
        assert "エントリー可" in _compute_risk_score(dd(0, 0), vol(0.5), 1.0, "low", "trending")["label"]
        assert "慎重" in _compute_risk_score(dd(-30, -40), vol(5.0), 10.0, "high", "volatile")["label"]


class TestTradeReadiness:
    """_trade_readiness() のテスト"""

    def test_any_failure_is_red(self):
        """1 つでも fail があれば赤信号にすること"""
        level, label = _trade_readiness([{"status": "pass"}, {"status": "fail"}])
        assert level == "red"
        assert "非推奨" in label

    def test_two_warnings_are_yellow(self):
        """警告が 2 つ以上なら条件付き（黄信号）にすること"""
        level, label = _trade_readiness([{"status": "warn"}, {"status": "warn"},
                                         {"status": "pass"}])
        assert level == "yellow"
        assert "条件付き" in label

    def test_one_warning_is_also_yellow(self):
        """警告が 1 つでも黄信号にすること（注意付きでエントリー可）"""
        level, _ = _trade_readiness([{"status": "warn"}, {"status": "pass"}])
        assert level == "yellow"

    def test_all_pass_is_green(self):
        """すべて pass なら青信号であること"""
        level, label = _trade_readiness([{"status": "pass"}, {"status": "pass"}])
        assert level == "green"
        assert "条件良好" in label

    def test_failure_beats_warnings(self):
        """fail は warn より優先されること"""
        level, _ = _trade_readiness([{"status": "warn"}, {"status": "warn"}, {"status": "fail"}])
        assert level == "red"


class TestBuildRiskReport:
    """build_risk_report() のテスト"""

    @pytest.fixture
    def stubbed(self, indicators_df):
        """外部依存（市場データ・MTF・イベント）をモックする。"""
        with patch("src.analysis.risk_advanced.get_ohlcv_data",
                   return_value=(indicators_df, "database")), \
             patch("src.analysis.risk_advanced.compute_all_indicators",
                   return_value=indicators_df), \
             patch("src.analysis.risk_advanced.analyze_multi_timeframe",
                   return_value={"alignment": "bullish", "alignment_label": "一致",
                                 "timeframes": {}}), \
             patch("src.analysis.risk_advanced.assess_event_risk",
                   return_value={"level": "low", "label": "低", "alerts": []}), \
             patch("src.analysis.risk_advanced.build_market_analysis",
                   return_value={
                       "regime": {"regime": "trending", "label": "トレンド", "strength": 60},
                       "key_levels": {"current_price": 150.0, "supports": [],
                                      "resistances": [], "nearest_support": None,
                                      "nearest_resistance": None,
                                      "distance_to_support_pips": None,
                                      "distance_to_resistance_pips": None},
                       "momentum": {"score": 10, "bias": "bullish", "label": "上昇"},
                       "correlation": {"pairs": [], "matrix": {}, "days": 60, "observations": 0},
                       "session": {"session": "london", "label": "ロンドン", "note": ""},
                       "event_risk": {"level": "low", "label": "低", "alerts": []},
                       "multi_timeframe": {"alignment": "bullish",
                                           "alignment_label": "一致", "timeframes": {}},
                   }):
            yield

    def test_returns_the_core_sections(self, stubbed):
        """レポートの主要セクションを含むこと"""
        report = build_risk_report("USDJPY")
        for key in ("risk_score", "value_at_risk", "drawdown", "scenarios",
                    "stress_test", "checklist", "trade_readiness"):
            assert key in report

    def test_normalizes_the_symbol(self, stubbed):
        """シンボルを大文字化すること"""
        assert build_risk_report("usdjpy")["symbol"] == "USDJPY"

    def test_readiness_is_a_traffic_light(self, stubbed):
        """エントリー可否を 3 段階で返すこと"""
        assert build_risk_report("USDJPY")["trade_readiness"] in ("green", "yellow", "red")

    def test_checklist_items_have_status_and_detail(self, stubbed):
        """チェックリストの各項目に状態と説明があること"""
        for item in build_risk_report("USDJPY")["checklist"]:
            assert item["status"] in ("pass", "warn", "fail")
            assert item["item"]
            assert item["detail"]

    def test_balance_flows_into_the_calculations(self, stubbed):
        """口座残高が VaR・ストレステストへ反映されること"""
        small = build_risk_report("USDJPY", account_balance=10_000)
        large = build_risk_report("USDJPY", account_balance=100_000)

        assert large["value_at_risk"]["daily_var_usd"] > small["value_at_risk"]["daily_var_usd"]
        assert large["stress_test"]["total_loss_usd"] > small["stress_test"]["total_loss_usd"]


class TestAssessAdvancedRisk:
    """assess_advanced_risk() のテスト"""

    def test_returns_sizing_and_levels(self, indicators_df):
        """ポジションサイズと SL / TP を返すこと"""
        with patch("src.analysis.risk_advanced.get_ohlcv_data",
                   return_value=(indicators_df, "database")), \
             patch("src.analysis.risk_advanced.compute_all_indicators",
                   return_value=indicators_df):
            result = assess_advanced_risk("USDJPY", account_balance=10_000, risk_percent=1.0)

        assert result["position_sizing"]["recommended_lots"] > 0
        assert result["stop_loss"]["price"] > 0
        assert result["take_profit"]["price"] > 0
        assert result["drawdown"]["max_drawdown_pct"] <= 0
