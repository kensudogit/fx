"""相場環境の深掘り分析 — src.analysis.market_deep のテスト

レジーム判定・S/R 検出・モメンタムスコアなどの純粋計算を中心に検証する。
外部データ取得（相関・イベント）はモックへ差し替える。
"""

from datetime import datetime, timezone
from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest

from src.analysis.market_deep import (
    _atr_series,
    _price_distance_pips,
    assess_event_risk,
    build_market_analysis,
    calc_pair_correlation,
    classify_market_regime,
    compute_momentum,
    find_key_levels,
    fx_session_context,
)
from src.analysis.technical import compute_all_indicators
from tests.conftest import make_ohlcv


def choppy_then(tail: list[float], amplitude: float = 3.0, n_head: int = 60):
    """前半をノイズの大きいレンジ、後半を指定系列にした終値・高値・安値を返す。

    `classify_market_regime` は ATR のパーセンタイルでレジームを判定するため、
    「直近の値動きが過去と比べて落ち着いている」状態を作るには
    前半にボラティリティの高い期間が必要になる。
    """
    head = [100.0 + (amplitude if i % 2 else -amplitude) for i in range(n_head)]
    closes = head + tail
    highs = [c + amplitude for c in head] + [c + 0.02 for c in tail]
    lows = [c - amplitude for c in head] + [c - 0.02 for c in tail]
    return closes, highs, lows


def indicator_frame(closes: list[float], highs=None, lows=None) -> pd.DataFrame:
    """終値列から指標計算済みの DataFrame を組み立てる。"""
    n = len(closes)
    df = pd.DataFrame({
        "open": closes,
        "high": highs if highs is not None else [c * 1.002 for c in closes],
        "low": lows if lows is not None else [c * 0.998 for c in closes],
        "close": closes,
        "volume": [1000.0] * n,
    })
    df.index = pd.date_range(end=pd.Timestamp("2026-01-01"), periods=n, freq="D")
    return compute_all_indicators(df)


class TestAtrSeries:
    """_atr_series() のテスト"""

    def test_returns_a_series_of_same_length(self, ohlcv):
        """入力と同じ長さの系列を返すこと"""
        assert len(_atr_series(ohlcv)) == len(ohlcv)

    def test_warmup_is_nan(self, ohlcv):
        """先頭 period-1 本は NaN であること"""
        assert _atr_series(ohlcv, period=14).iloc[:13].isna().all()

    def test_values_are_non_negative(self, ohlcv):
        """ATR は 0 以上であること"""
        assert (_atr_series(ohlcv).dropna() >= 0).all()


class TestPriceDistancePips:
    """_price_distance_pips() のテスト"""

    def test_jpy_pair_distance(self):
        """JPY ペアは 0.01 を 1 pip として換算すること"""
        assert _price_distance_pips(150.00, 151.50, "USDJPY") == 150.0

    def test_usd_pair_distance(self):
        """その他ペアは 0.0001 を 1 pip として換算すること"""
        assert _price_distance_pips(1.0800, 1.0850, "EURUSD") == 50.0

    def test_distance_is_absolute(self):
        """向きに関係なく絶対値を返すこと"""
        assert _price_distance_pips(151.5, 150.0, "USDJPY") == 150.0

    @pytest.mark.parametrize("a,b", [(None, 150.0), (150.0, None), (None, None)])
    def test_missing_price_returns_none(self, a, b):
        """価格が欠けている場合は None を返すこと"""
        assert _price_distance_pips(a, b, "USDJPY") is None


class TestClassifyMarketRegime:
    """classify_market_regime() のテスト"""

    def test_returns_expected_keys(self, indicators_df):
        """判定結果のキーが揃っていること"""
        assert set(classify_market_regime(indicators_df)) == {
            "regime", "label", "strength", "trend_bias", "trend_label",
            "atr_percentile", "bb_width_pct", "ma_spread_pct", "slope_20d_pct",
        }

    def test_regime_is_one_of_three(self, indicators_df):
        """レジームは 3 分類のいずれかであること"""
        assert classify_market_regime(indicators_df)["regime"] in ("trending", "ranging", "volatile")

    def test_strength_is_bounded(self, indicators_df):
        """強度は 0〜100 に収まること"""
        assert 0 <= classify_market_regime(indicators_df)["strength"] <= 100

    def test_strong_trend_is_detected(self):
        """落ち着いた一方向の値動きは trending と判定されること"""
        closes, highs, lows = choppy_then([100.0 + 0.10 * i for i in range(1, 61)])
        result = classify_market_regime(indicator_frame(closes, highs, lows))

        assert result["regime"] == "trending"
        assert result["trend_bias"] == "bullish"
        assert result["trend_label"] == "上昇トレンド"

    def test_downtrend_is_flagged_bearish(self):
        """一貫した下落は下降トレンドと判定されること"""
        closes = [100.0 * (0.996 ** i) for i in range(120)]
        result = classify_market_regime(indicator_frame(closes))

        assert result["trend_bias"] == "bearish"
        assert "下降" in result["trend_label"]

    def test_flat_market_is_ranging(self):
        """ボラティリティが収縮した相場は ranging と判定されること"""
        closes, highs, lows = choppy_then([100.0] * 60)
        result = classify_market_regime(indicator_frame(closes, highs, lows))

        assert result["regime"] == "ranging"
        assert result["trend_bias"] == "neutral"

    def test_wide_bollinger_bands_trigger_volatile(self):
        """バンド幅が広い相場は volatile と判定されること"""
        rng = np.random.default_rng(3)
        closes = list(100 + np.cumsum(rng.normal(0, 3.0, 120)))
        assert classify_market_regime(indicator_frame(closes))["regime"] == "volatile"

    def test_handles_short_history(self):
        """データが短くても例外を出さないこと"""
        result = classify_market_regime(compute_all_indicators(make_ohlcv(n=10)))
        assert result["slope_20d_pct"] == 0


class TestFindKeyLevels:
    """find_key_levels() のテスト"""

    def test_returns_expected_keys(self, indicators_df):
        """S/R 情報のキーが揃っていること"""
        assert set(find_key_levels(indicators_df, "USDJPY")) == {
            "current_price", "supports", "resistances", "nearest_support",
            "nearest_resistance", "distance_to_support_pips", "distance_to_resistance_pips",
        }

    def test_supports_are_sorted_ascending(self, indicators_df):
        """サポートは昇順で返すこと"""
        supports = find_key_levels(indicators_df, "USDJPY")["supports"]
        assert supports == sorted(supports)

    def test_limits_levels_to_four(self, indicators_df):
        """水準は最大 4 つまでに絞ること"""
        levels = find_key_levels(indicators_df, "USDJPY")
        assert len(levels["supports"]) <= 4
        assert len(levels["resistances"]) <= 4

    def test_nearest_support_is_below_price(self, indicators_df):
        """最寄サポートは現在値以下であること"""
        levels = find_key_levels(indicators_df, "USDJPY")
        if levels["nearest_support"] is not None:
            assert levels["nearest_support"] <= levels["current_price"]

    def test_nearest_resistance_is_above_price(self, indicators_df):
        """最寄レジスタンスは現在値以上であること"""
        levels = find_key_levels(indicators_df, "USDJPY")
        if levels["nearest_resistance"] is not None:
            assert levels["nearest_resistance"] >= levels["current_price"]

    def test_detects_an_obvious_swing_high(self):
        """明確なスイングハイをレジスタンスとして検出すること"""
        closes = [100.0] * 70
        highs = [100.2] * 70
        highs[30] = 110.0  # 単独のピーク
        frame = indicator_frame(closes, highs=highs, lows=[99.8] * 70)
        assert 110.0 in find_key_levels(frame, "USDJPY")["resistances"]

    def test_flat_market_finds_no_distinct_levels(self):
        """完全に平坦な相場では距離が 0 になること"""
        frame = indicator_frame([100.0] * 70, highs=[100.0] * 70, lows=[100.0] * 70)
        levels = find_key_levels(frame, "USDJPY")
        assert levels["current_price"] == 100.0

    def test_lookback_limits_the_window(self, indicators_df):
        """lookback を変えると検出結果も変わりうること"""
        short = find_key_levels(indicators_df, "USDJPY", lookback=20)
        assert short["current_price"] == find_key_levels(indicators_df, "USDJPY")["current_price"]


class TestComputeMomentum:
    """compute_momentum() のテスト"""

    def test_returns_expected_keys(self, indicators_df):
        """モメンタム情報のキーが揃っていること"""
        assert set(compute_momentum(indicators_df)) == {
            "score", "bias", "label", "rsi", "macd_histogram", "roc_5d_pct", "roc_20d_pct",
        }

    def test_score_is_bounded(self, indicators_df):
        """スコアは -100〜100 に収まること"""
        assert -100 <= compute_momentum(indicators_df)["score"] <= 100

    def test_uptrend_scores_bullish(self):
        """上昇局面では強気バイアスになること"""
        closes = [100.0 * (1.005 ** i) for i in range(120)]
        result = compute_momentum(indicator_frame(closes))

        assert result["bias"] == "bullish"
        assert result["score"] > 30
        assert result["label"] == "強い上昇モメンタム"

    def test_downtrend_scores_bearish(self):
        """下落局面では弱気バイアスになること"""
        closes = [100.0 * (0.995 ** i) for i in range(120)]
        result = compute_momentum(indicator_frame(closes))

        assert result["bias"] == "bearish"
        assert result["score"] < -30

    def test_flat_market_is_neutral(self):
        """まったく動かない相場では中立になること"""
        closes = [100.0] * 120
        result = compute_momentum(indicator_frame(closes, [100.0] * 120, [100.0] * 120))

        assert result["bias"] == "neutral"
        assert result["label"] == "中立"

    def test_missing_indicators_use_neutral_defaults(self):
        """指標が未計算でも中立値で処理を続けること"""
        result = compute_momentum(compute_all_indicators(make_ohlcv(n=5)))
        assert result["rsi"] == 50.0
        assert result["roc_20d_pct"] == 0.0


class TestCalcPairCorrelation:
    """calc_pair_correlation() のテスト"""

    def test_matrix_is_symmetric_with_unit_diagonal(self, ohlcv):
        """相関行列は対角が 1、かつ対称であること"""
        with patch("src.analysis.market_deep.get_ohlcv_data", return_value=(ohlcv, "database")):
            result = calc_pair_correlation(days=60)

        pairs = result["pairs"]
        for a in pairs:
            assert result["matrix"][a][a] == pytest.approx(1.0)
            for b in pairs:
                assert result["matrix"][a][b] == pytest.approx(result["matrix"][b][a], abs=1e-6)

    def test_reports_observation_count(self, ohlcv):
        """観測数を返すこと"""
        with patch("src.analysis.market_deep.get_ohlcv_data", return_value=(ohlcv, "database")):
            assert calc_pair_correlation()["observations"] > 0

    def test_falls_back_when_data_is_insufficient(self):
        """データ不足時は単位行列相当にフォールバックすること"""
        tiny = make_ohlcv(n=3)
        with patch("src.analysis.market_deep.get_ohlcv_data", return_value=(tiny, "sample")):
            result = calc_pair_correlation()

        assert result["observations"] == 0
        for a in result["pairs"]:
            assert result["matrix"][a][a] == 1.0

    def test_echoes_the_requested_period(self, ohlcv):
        """指定した日数をそのまま返すこと"""
        with patch("src.analysis.market_deep.get_ohlcv_data", return_value=(ohlcv, "database")):
            assert calc_pair_correlation(days=90)["days"] == 90


class TestFxSessionContext:
    """fx_session_context() のテスト"""

    @pytest.mark.parametrize("hour,session", [
        (0, "asia"), (6, "asia"),
        (7, "london"), (12, "london"),
        (13, "overlap"), (20, "overlap"),
        (21, "new_york"), (23, "new_york"),
    ])
    def test_session_boundaries(self, hour, session):
        """UTC 時刻に応じたセッションを返すこと"""
        fixed = datetime(2026, 1, 1, hour, tzinfo=timezone.utc)
        with patch("src.analysis.market_deep.datetime") as dt:
            dt.now.return_value = fixed
            assert fx_session_context()["session"] == session

    def test_includes_label_and_note(self):
        """表示用のラベルと注意書きを含むこと"""
        result = fx_session_context()
        assert result["label"]
        assert result["note"]


class TestAssessEventRisk:
    """assess_event_risk() のテスト"""

    @pytest.mark.parametrize("count,level", [(0, "low"), (1, "medium"), (2, "high"), (5, "high")])
    def test_level_depends_on_alert_count(self, count, level):
        """高影響イベント数に応じてリスクレベルを判定すること"""
        alerts = [{"title": f"event {i}"} for i in range(count)]
        with patch("src.analysis.market_deep.get_event_alerts", return_value=alerts):
            assert assess_event_risk()["level"] == level

    def test_passes_through_the_window(self):
        """指定した時間幅をそのまま伝えること"""
        with patch("src.analysis.market_deep.get_event_alerts", return_value=[]) as get_alerts:
            result = assess_event_risk(within_hours=72)

        assert result["within_hours"] == 72
        get_alerts.assert_called_once_with(72)

    def test_includes_the_alerts(self):
        """アラート本体も返すこと"""
        alerts = [{"title": "FOMC"}]
        with patch("src.analysis.market_deep.get_event_alerts", return_value=alerts):
            assert assess_event_risk()["alerts"] == alerts


class TestBuildMarketAnalysis:
    """build_market_analysis() のテスト"""

    @pytest.fixture
    def stubbed(self, ohlcv):
        """外部依存（MTF・相関・イベント）をモックする。"""
        with patch("src.analysis.market_deep.get_ohlcv_data", return_value=(ohlcv, "database")), \
             patch("src.analysis.market_deep.analyze_multi_timeframe",
                   return_value={"alignment": "bullish"}), \
             patch("src.analysis.market_deep.get_event_alerts", return_value=[]):
            yield

    def test_aggregates_all_components(self, stubbed):
        """全分析コンポーネントを含むこと"""
        result = build_market_analysis("usdjpy")
        for key in ("regime", "key_levels", "momentum", "multi_timeframe",
                    "correlation", "session", "event_risk"):
            assert key in result

    def test_normalizes_symbol_and_reports_source(self, stubbed):
        """シンボルを大文字化し、データソースと日数を返すこと"""
        result = build_market_analysis("usdjpy", days=90)

        assert result["symbol"] == "USDJPY"
        assert result["source"] == "database"
        assert result["days"] == 90
