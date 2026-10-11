"""ボラティリティ予測 ML — src.ml.volatility_predictor のテスト"""

from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest

from src.analysis.technical import compute_all_indicators
from src.ml.volatility_predictor import (
    _atr_series,
    _ewma_forecast,
    _vol_regime,
    predict_volatility,
)
from tests.conftest import make_ohlcv


@pytest.fixture(autouse=True)
def no_cache():
    """キャッシュを無効化して毎回計算させる。"""
    with patch("src.ml.volatility_predictor.cache_get", return_value=None), \
         patch("src.ml.volatility_predictor.cache_put"):
        yield


class TestAtrSeries:
    """_atr_series() のテスト"""

    def test_same_length_as_input(self, ohlcv):
        """入力と同じ長さの系列を返すこと"""
        assert len(_atr_series(ohlcv)) == len(ohlcv)

    def test_values_are_non_negative(self, ohlcv):
        """ATR は 0 以上であること"""
        assert (_atr_series(ohlcv).dropna() >= 0).all()

    def test_warmup_is_nan(self, ohlcv):
        """先頭 period-1 本は NaN であること"""
        assert _atr_series(ohlcv, period=14).iloc[:13].isna().all()


class TestEwmaForecast:
    """_ewma_forecast() のテスト"""

    def test_constant_series_returns_the_constant(self):
        """定数系列なら同じ値を返すこと"""
        assert _ewma_forecast(pd.Series([2.0] * 30)) == pytest.approx(2.0)

    def test_empty_series_returns_zero(self):
        """空の系列では 0 を返すこと（例外にしない）"""
        assert _ewma_forecast(pd.Series([], dtype=float)) == 0.0

    def test_all_nan_series_returns_zero(self):
        """全て NaN でも 0 を返すこと"""
        assert _ewma_forecast(pd.Series([np.nan] * 10)) == 0.0

    def test_weights_recent_values_more(self):
        """直近の値により強く反応すること"""
        rising = pd.Series([1.0] * 20 + [5.0] * 5)
        assert _ewma_forecast(rising) > rising.iloc[:20].mean()

    def test_returns_a_plain_float(self):
        """numpy 型ではなく float を返すこと"""
        assert type(_ewma_forecast(pd.Series([1.0, 2.0, 3.0]))) is float


class TestVolRegime:
    """_vol_regime() のテスト"""

    @pytest.mark.parametrize("atr_pct,regime", [
        (0.0, "low"), (0.49, "low"),
        (0.5, "medium"), (1.19, "medium"),
        (1.2, "high"), (5.0, "high"),
    ])
    def test_thresholds(self, atr_pct, regime):
        """ATR% に応じたレジームを返すこと"""
        assert _vol_regime(atr_pct)[0] == regime

    def test_labels_are_japanese(self):
        """日本語のラベルを添えること"""
        for atr_pct in (0.2, 0.8, 2.0):
            assert _vol_regime(atr_pct)[1]

    def test_label_matches_the_regime(self):
        """ラベルとレジームの対応が取れていること"""
        assert "低ボラ" in _vol_regime(0.2)[1]
        assert "高ボラ" in _vol_regime(2.0)[1]


class TestPredictVolatility:
    """predict_volatility() のテスト"""

    def test_returns_expected_sections(self, indicators_df):
        """結果セクションが揃っていること"""
        result = predict_volatility("USDJPY", result_df=indicators_df, source="database")
        assert set(result) >= {
            "symbol", "source", "current_price", "forecast_days", "current", "forecast", "ml",
        }

    def test_normalizes_the_symbol(self, indicators_df):
        """シンボルを大文字化すること"""
        assert predict_volatility("usdjpy", result_df=indicators_df)["symbol"] == "USDJPY"

    def test_forecast_has_regime_and_trend(self, indicators_df):
        """予測にレジームとトレンドを含めること"""
        forecast = predict_volatility("USDJPY", result_df=indicators_df)["forecast"]

        assert forecast["regime"] in ("low", "medium", "high")
        assert forecast["vol_trend"] in ("expanding", "contracting", "stable")
        assert forecast["regime_label"]
        assert forecast["vol_trend_label"]

    def test_forecast_values_are_non_negative(self, indicators_df):
        """予測 ATR と ATR% が 0 以上であること"""
        forecast = predict_volatility("USDJPY", result_df=indicators_df)["forecast"]
        assert forecast["atr"] >= 0
        assert forecast["atr_percent"] >= 0

    def test_current_section_matches_volatility_stats(self, indicators_df):
        """現在値セクションがボラ統計と一致すること"""
        from src.analysis.volatility import calc_volatility_stats

        result = predict_volatility("USDJPY", result_df=indicators_df)
        assert result["current"] == calc_volatility_stats(indicators_df)

    def test_ml_status_is_reported(self, indicators_df):
        """ML の利用状況（成功 / EWMA フォールバック）を返すこと"""
        ml = predict_volatility("USDJPY", result_df=indicators_df)["ml"]
        assert ml["status"] in ("success", "ewma_fallback")

    def test_falls_back_to_ewma_for_short_history(self):
        """データが少なければ EWMA にフォールバックすること"""
        short = compute_all_indicators(make_ohlcv(n=50))
        ml = predict_volatility("USDJPY", result_df=short)["ml"]

        assert ml["status"] == "ewma_fallback"
        assert ml["model"] == "EWMA"

    def test_forecast_days_is_echoed(self, indicators_df):
        """指定した予測日数を返すこと"""
        result = predict_volatility("USDJPY", result_df=indicators_df, forecast_days=10)
        assert result["forecast_days"] == 10

    def test_shared_dataframe_skips_the_cache(self, indicators_df):
        """外部 DataFrame 指定時はキャッシュを参照しないこと"""
        with patch("src.ml.volatility_predictor.cache_get") as cache_get:
            predict_volatility("USDJPY", result_df=indicators_df)
        cache_get.assert_not_called()

    def test_shared_dataframe_defaults_the_source(self, indicators_df):
        """ソース未指定なら shared と記録すること"""
        assert predict_volatility("USDJPY", result_df=indicators_df)["source"] == "shared"

    def test_fetches_data_when_not_provided(self, ohlcv):
        """DataFrame 未指定なら市場データを取得すること"""
        with patch("src.ml.volatility_predictor.get_ohlcv_data",
                   return_value=(ohlcv, "database")) as get_data:
            result = predict_volatility("USDJPY")

        get_data.assert_called_once()
        assert result["source"] == "database"

    def test_uses_the_cached_result(self):
        """キャッシュヒット時は再計算しないこと"""
        cached = {"symbol": "USDJPY"}
        with patch("src.ml.volatility_predictor.cache_get", return_value=cached), \
             patch("src.ml.volatility_predictor.get_ohlcv_data") as get_data:
            assert predict_volatility("USDJPY") is cached
        get_data.assert_not_called()

    def test_change_vs_current_is_reported(self, indicators_df):
        """現在ボラとの変化率を返すこと"""
        forecast = predict_volatility("USDJPY", result_df=indicators_df)["forecast"]
        assert isinstance(forecast["change_vs_current_pct"], float)
