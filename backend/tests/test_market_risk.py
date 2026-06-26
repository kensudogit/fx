"""相場深度・リスクレポートのテスト"""

from src.analysis.market_deep import (
    assess_event_risk,
    build_market_analysis,
    calc_pair_correlation,
    classify_market_regime,
    compute_momentum,
)
from src.analysis.risk_advanced import build_risk_report
from src.analysis.technical import compute_all_indicators
from src.data.market_data import get_ohlcv_data


def test_build_market_analysis_structure():
    result = build_market_analysis("USDJPY", days=120)
    assert result["symbol"] == "USDJPY"
    assert result["regime"]["regime"] in ("trending", "ranging", "volatile")
    assert "supports" in result["key_levels"]
    assert "resistances" in result["key_levels"]
    assert -100 <= result["momentum"]["score"] <= 100
    assert result["multi_timeframe"]["alignment_label"]
    assert len(result["correlation"]["pairs"]) >= 4
    assert result["session"]["label"]
    assert result["event_risk"]["level"] in ("low", "medium", "high")


def test_correlation_matrix_diagonal():
    corr = calc_pair_correlation(days=60)
    for sym in corr["pairs"]:
        assert corr["matrix"][sym][sym] == 1.0


def test_classify_market_regime():
    df, _ = get_ohlcv_data("EURUSD", 120)
    result_df = compute_all_indicators(df)
    regime = classify_market_regime(result_df)
    assert regime["regime"] in ("trending", "ranging", "volatile")
    assert 0 <= regime["strength"] <= 100
    assert regime["trend_bias"] in ("bullish", "bearish", "neutral")


def test_compute_momentum_bounds():
    df, _ = get_ohlcv_data("GBPUSD", 120)
    result_df = compute_all_indicators(df)
    mom = compute_momentum(result_df)
    assert -100 <= mom["score"] <= 100
    assert mom["bias"] in ("bullish", "bearish", "neutral")


def test_event_risk_structure():
    ev = assess_event_risk(48)
    assert ev["level"] in ("low", "medium", "high")
    assert isinstance(ev["alerts"], list)


def test_build_risk_report_structure():
    report = build_risk_report("USDJPY", account_balance=10000, risk_percent=1.0, days=120)
    assert report["symbol"] == "USDJPY"
    assert "value_at_risk" in report
    assert report["value_at_risk"]["daily_var_usd"] >= 0
    assert "scenarios" in report
    assert "stress_test" in report
    assert 0 <= report["risk_score"]["score"] <= 100
    assert len(report["checklist"]) >= 5
    assert report["trade_readiness"] in ("green", "yellow", "red")
    assert report["position_sizing"]["recommended_lots"] >= 0.01
