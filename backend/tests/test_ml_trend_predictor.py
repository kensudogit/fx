"""トレンド予測 ML — src.ml.trend_predictor のテスト

ルールベース判定は直接、ML パートは実データで学習させて検証する。
MTF 分析とキャッシュはモックへ差し替える。
"""

from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest

from src.analysis.technical import compute_all_indicators
from src.ml.trend_predictor import _build_trend_dataset, _rule_trend, predict_trend
from tests.conftest import make_ohlcv


def latest(**values) -> pd.Series:
    """判定に使う最新行を組み立てる（指定しない指標は NaN）。"""
    base = {"close": np.nan, "sma_20": np.nan, "sma_50": np.nan,
            "rsi": np.nan, "macd": np.nan, "macd_signal": np.nan}
    base.update(values)
    return pd.Series(base)


@pytest.fixture
def mtf_stub():
    """MTF 分析をモックする。"""
    with patch("src.ml.trend_predictor.analyze_multi_timeframe",
               return_value={"alignment": "neutral", "alignment_label": "ミックス"}):
        yield


@pytest.fixture(autouse=True)
def no_cache():
    """キャッシュを無効化する。"""
    with patch("src.ml.trend_predictor.cache_get", return_value=None), \
         patch("src.ml.trend_predictor.cache_put"):
        yield


class TestRuleTrend:
    """_rule_trend() のテスト"""

    def test_all_bullish_signals(self):
        """4 指標すべてが強気なら bullish になること"""
        trend, reasons = _rule_trend(latest(close=110, sma_20=105, sma_50=100,
                                            rsi=65, macd=0.5, macd_signal=0.2))
        assert trend == "bullish"
        assert len(reasons) == 4

    def test_all_bearish_signals(self):
        """4 指標すべてが弱気なら bearish になること"""
        trend, _ = _rule_trend(latest(close=90, sma_20=95, sma_50=100,
                                      rsi=35, macd=0.1, macd_signal=0.4))
        assert trend == "bearish"

    def test_mixed_signals_are_neutral(self):
        """強気・弱気が拮抗すれば neutral になること"""
        trend, _ = _rule_trend(latest(close=110, sma_20=105, sma_50=100,
                                      rsi=35, macd=0.1, macd_signal=0.4))
        assert trend == "neutral"

    def test_requires_a_score_of_two(self):
        """スコア 1 だけでは方向を断定しないこと"""
        trend, _ = _rule_trend(latest(rsi=65))
        assert trend == "neutral"

    def test_missing_indicators_are_skipped(self):
        """指標が欠けていても例外にならないこと"""
        trend, reasons = _rule_trend(latest())
        assert trend == "neutral"
        assert reasons == []

    def test_reasons_are_human_readable(self):
        """判定理由を日本語で説明すること"""
        _, reasons = _rule_trend(latest(sma_20=105, sma_50=100))
        assert any("SMA20" in r for r in reasons)

    @pytest.mark.parametrize("rsi,expected", [(56, "買い圧力"), (44, "売り圧力")])
    def test_rsi_thresholds(self, rsi, expected):
        """RSI 55 / 45 を境に圧力の向きを判定すること"""
        _, reasons = _rule_trend(latest(rsi=rsi))
        assert any(expected in r for r in reasons)

    def test_rsi_in_the_middle_adds_nothing(self):
        """RSI が中立域なら理由に含めないこと"""
        _, reasons = _rule_trend(latest(rsi=50))
        assert reasons == []


class TestBuildTrendDataset:
    """_build_trend_dataset() のテスト"""

    def test_returns_features_and_labels(self, indicators_df):
        """特徴量とラベルを同数返すこと"""
        X, y = _build_trend_dataset(indicators_df)
        assert len(X) == len(y)
        assert len(X) > 0

    def test_labels_are_three_classes(self, indicators_df):
        """ラベルは 3 クラス（上昇 / 下降 / 中立）に収まること"""
        _, y = _build_trend_dataset(indicators_df)
        assert set(np.unique(y)) <= {0, 1, 2}

    def test_short_history_yields_no_samples(self):
        """データが少なければサンプルを作らないこと"""
        X, y = _build_trend_dataset(compute_all_indicators(make_ohlcv(n=20)))
        assert len(X) == 0

    def test_longer_horizon_reduces_samples(self, indicators_df):
        """予測期間を伸ばすとサンプル数が減ること"""
        short, _ = _build_trend_dataset(indicators_df, horizon=5)
        long, _ = _build_trend_dataset(indicators_df, horizon=30)
        assert len(long) < len(short)


class TestPredictTrend:
    """predict_trend() のテスト"""

    def test_returns_expected_keys(self, indicators_df, mtf_stub):
        """予測結果のキーが揃っていること"""
        result = predict_trend("USDJPY", result_df=indicators_df, source="database")
        assert set(result) == {
            "symbol", "source", "current_price", "trend", "trend_label",
            "confidence", "horizon_days", "rule_based", "ml", "multi_timeframe",
        }

    def test_normalizes_the_symbol(self, indicators_df, mtf_stub):
        """シンボルを大文字化すること"""
        assert predict_trend("usdjpy", result_df=indicators_df)["symbol"] == "USDJPY"

    def test_trend_is_one_of_three(self, indicators_df, mtf_stub):
        """総合トレンドは 3 分類のいずれかであること"""
        result = predict_trend("USDJPY", result_df=indicators_df)
        assert result["trend"] in ("bullish", "bearish", "neutral")

    def test_includes_rule_based_reasons(self, indicators_df, mtf_stub):
        """ルールベースの判定理由を含めること"""
        result = predict_trend("USDJPY", result_df=indicators_df)
        assert "trend" in result["rule_based"]
        assert isinstance(result["rule_based"]["reasons"], list)

    def test_ml_section_reports_status(self, indicators_df, mtf_stub):
        """ML パートの状態を返すこと"""
        ml = predict_trend("USDJPY", result_df=indicators_df)["ml"]
        assert ml["status"] in ("success", "insufficient_data")

    def test_ml_is_skipped_for_short_history(self, mtf_stub):
        """データ不足なら ML をスキップして状態を明示すること"""
        short = compute_all_indicators(make_ohlcv(n=60))
        result = predict_trend("USDJPY", result_df=short)

        assert result["ml"]["status"] == "insufficient_data"
        assert result["confidence"] == 50.0

    def test_shared_dataframe_skips_the_cache(self, indicators_df, mtf_stub):
        """外部から DataFrame を渡した場合はキャッシュを参照しないこと"""
        with patch("src.ml.trend_predictor.cache_get") as cache_get:
            predict_trend("USDJPY", result_df=indicators_df)
        cache_get.assert_not_called()

    def test_shared_dataframe_defaults_the_source(self, indicators_df, mtf_stub):
        """ソース未指定なら shared と記録すること"""
        assert predict_trend("USDJPY", result_df=indicators_df)["source"] == "shared"

    def test_fetches_data_when_not_provided(self, ohlcv, mtf_stub):
        """DataFrame 未指定なら市場データを取得すること"""
        with patch("src.ml.trend_predictor.get_ohlcv_data",
                   return_value=(ohlcv, "database")) as get_data:
            result = predict_trend("USDJPY")

        get_data.assert_called_once()
        assert result["source"] == "database"

    def test_uses_the_cached_result(self, mtf_stub):
        """キャッシュヒット時は再計算しないこと"""
        cached = {"symbol": "USDJPY", "trend": "bullish"}
        with patch("src.ml.trend_predictor.cache_get", return_value=cached), \
             patch("src.ml.trend_predictor.get_ohlcv_data") as get_data:
            assert predict_trend("USDJPY") is cached
        get_data.assert_not_called()

    def test_accepts_an_injected_mtf_result(self, indicators_df):
        """MTF 結果を渡せば再計算しないこと（バッチ処理での重複防止）"""
        mtf = {"alignment": "bullish", "alignment_label": "日足・4H 一致"}
        with patch("src.ml.trend_predictor.analyze_multi_timeframe") as analyze:
            result = predict_trend("USDJPY", result_df=indicators_df, mtf=mtf)

        analyze.assert_not_called()
        assert result["multi_timeframe"]["alignment"] == "bullish"

    def test_majority_vote_needs_two_agreeing_sources(self, indicators_df):
        """3 者のうち 2 者以上が一致して初めて方向を確定すること"""
        mtf = {"alignment": "bullish", "alignment_label": "上昇"}
        with patch("src.ml.trend_predictor._rule_trend", return_value=("bullish", [])):
            result = predict_trend("USDJPY", result_df=indicators_df, mtf=mtf)

        assert result["trend"] == "bullish"
        assert result["trend_label"] == "上昇トレンド"

    def test_single_dissenting_source_is_not_enough(self, indicators_df):
        """1 者だけが方向を示しても中立のままにすること

        ML がデータ不足でスキップされた場合、ML 票はルールベースの判定を
        引き継ぐ。そこでルールベースを中立にし、MTF だけが下降を示す状況
        （bearish 1 票 < 必要な 2 票）を作って検証する。
        """
        mtf = {"alignment": "bearish", "alignment_label": "下降"}
        with patch("src.ml.trend_predictor._rule_trend", return_value=("neutral", [])), \
             patch("src.ml.trend_predictor._build_trend_dataset",
                   return_value=(np.array([]), np.array([]))):
            result = predict_trend("USDJPY", result_df=indicators_df, mtf=mtf)

        assert result["trend"] == "neutral"
        assert "レンジ" in result["trend_label"]

    def test_two_bearish_sources_decide_the_trend(self, indicators_df):
        """2 者が下降で一致すれば bearish になること"""
        mtf = {"alignment": "bearish", "alignment_label": "下降"}
        with patch("src.ml.trend_predictor._rule_trend", return_value=("bearish", [])), \
             patch("src.ml.trend_predictor._build_trend_dataset",
                   return_value=(np.array([]), np.array([]))):
            result = predict_trend("USDJPY", result_df=indicators_df, mtf=mtf)

        assert result["trend"] == "bearish"
        assert result["trend_label"] == "下降トレンド"

    def test_horizon_is_echoed(self, indicators_df, mtf_stub):
        """指定した予測期間を返すこと"""
        assert predict_trend("USDJPY", result_df=indicators_df,
                             horizon=10)["horizon_days"] == 10
