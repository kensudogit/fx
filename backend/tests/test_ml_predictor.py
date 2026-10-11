"""価格予測 ML — src.ml.predictor のテスト

sklearn による学習は実行時間が短いため実際に走らせ、
ディープラーニングのバックエンド選択とキャッシュはモックで検証する。
"""

from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest

from src.analysis.technical import compute_all_indicators
from src.ml.predictor import (
    predict_price,
    prepare_features,
    train_price_predictor,
    train_price_predictor_sklearn,
)
from tests.conftest import make_ohlcv

FEATURE_COLUMNS = ["sma_20", "sma_50", "rsi", "macd", "macd_signal",
                   "stoch_k", "stoch_d", "bb_upper", "bb_lower"]


class TestPrepareFeatures:
    """prepare_features() のテスト"""

    def test_returns_matrix_and_targets(self, indicators_df):
        """特徴量行列と目的変数を返すこと"""
        X, y = prepare_features(indicators_df)
        assert len(X) == len(y)
        assert len(X) > 0

    def test_feature_dimension_is_columns_times_lookback(self, indicators_df):
        """特徴量の次元は 指標数 × ルックバック であること"""
        X, _ = prepare_features(indicators_df, lookback=5)
        assert X.shape[1] == len(FEATURE_COLUMNS) * 5

    def test_lookback_changes_the_dimension(self, indicators_df):
        """ルックバックを変えると次元も変わること"""
        X3, _ = prepare_features(indicators_df, lookback=3)
        X7, _ = prepare_features(indicators_df, lookback=7)
        assert X3.shape[1] < X7.shape[1]

    def test_targets_are_close_prices(self, indicators_df):
        """目的変数は終値であること"""
        _, y = prepare_features(indicators_df)
        valid_closes = set(indicators_df["close"].round(6))
        assert all(round(v, 6) in valid_closes for v in y[:5])

    def test_insufficient_rows_return_empty(self):
        """データが少なければ空配列を返すこと"""
        X, y = prepare_features(compute_all_indicators(make_ohlcv(n=12)))
        assert len(X) == 0
        assert len(y) == 0

    def test_missing_indicator_columns_return_empty(self):
        """指標列が無ければ空配列を返すこと"""
        raw = make_ohlcv(n=100)
        X, y = prepare_features(raw)
        assert len(X) == 0

    def test_no_nan_in_features(self, indicators_df):
        """特徴量に NaN が混入しないこと"""
        X, _ = prepare_features(indicators_df)
        assert not np.isnan(X).any()


class TestTrainPricePredictorSklearn:
    """train_price_predictor_sklearn() のテスト"""

    def test_trains_and_predicts(self, indicators_df):
        """学習して予測値を返すこと"""
        result = train_price_predictor_sklearn(indicators_df)

        assert result["status"] == "success"
        assert isinstance(result["prediction"], float)
        assert result["model"] == "RandomForestRegressor"
        assert result["backend"] == "sklearn"

    def test_reports_current_price(self, indicators_df):
        """現在価格を併せて返すこと（比較用）"""
        result = train_price_predictor_sklearn(indicators_df)
        assert result["current_price"] == round(float(indicators_df["close"].iloc[-1]), 4)

    def test_prediction_is_in_a_plausible_range(self, indicators_df):
        """予測値が直近価格からかけ離れないこと"""
        result = train_price_predictor_sklearn(indicators_df)
        current = result["current_price"]
        assert current * 0.8 < result["prediction"] < current * 1.2

    def test_reports_r2_scores(self, indicators_df):
        """学習・テストの決定係数を返すこと"""
        result = train_price_predictor_sklearn(indicators_df)
        assert result["train_r2"] is not None
        assert result["test_r2"] is not None

    def test_insufficient_data_is_reported(self):
        """データ不足なら status で明示すること（例外にしない）"""
        result = train_price_predictor_sklearn(compute_all_indicators(make_ohlcv(n=20)))

        assert result["status"] == "insufficient_data"
        assert "不足" in result["message"]

    def test_is_deterministic(self, indicators_df):
        """乱数シード固定のため結果が再現すること"""
        first = train_price_predictor_sklearn(indicators_df)
        second = train_price_predictor_sklearn(indicators_df)
        assert first["prediction"] == second["prediction"]

    def test_without_symbol_skips_the_model_cache(self, indicators_df):
        """シンボル未指定ならモデルキャッシュを使わないこと"""
        with patch("src.ml.predictor.load_or_train") as load_or_train:
            train_price_predictor_sklearn(indicators_df, symbol="")
        load_or_train.assert_not_called()

    def test_with_symbol_uses_the_model_cache(self, indicators_df):
        """シンボル指定時はモデルキャッシュを経由すること"""
        with patch("src.ml.predictor.load_or_train",
                   side_effect=lambda path, train: train()) as load_or_train:
            train_price_predictor_sklearn(indicators_df, symbol="USDJPY")
        load_or_train.assert_called_once()

    def test_reports_cached_inference(self, indicators_df):
        """ディスクから読み込んだ場合は inference=cached と報告すること"""
        real = train_price_predictor_sklearn(indicators_df)
        bundle = {"model": None, "scaler": None, "loaded_from_disk": True}

        class FakeModel:
            def predict(self, X):
                return [real["prediction"]]

        class FakeScaler:
            def transform(self, X):
                return X

        bundle["model"] = FakeModel()
        bundle["scaler"] = FakeScaler()
        with patch("src.ml.predictor.load_or_train", return_value=bundle):
            result = train_price_predictor_sklearn(indicators_df, symbol="USDJPY")

        assert result["inference"] == "cached"


class TestTrainPricePredictorDispatch:
    """train_price_predictor() のバックエンド選択テスト"""

    def test_dispatches_to_sklearn(self, indicators_df):
        """sklearn バックエンドでは sklearn 実装を呼ぶこと"""
        with patch("src.ml.deep_learning.resolve_price_backend", return_value="sklearn"):
            assert train_price_predictor(indicators_df)["backend"] == "sklearn"

    def test_dispatches_to_tensorflow(self, indicators_df):
        """tensorflow バックエンドでは TF 実装へ委譲すること"""
        with patch("src.ml.deep_learning.resolve_price_backend", return_value="tensorflow"), \
             patch("src.ml.deep_learning.train_tensorflow_price_predictor",
                   return_value={"backend": "tensorflow"}) as train:
            assert train_price_predictor(indicators_df, "USDJPY", 200)["backend"] == "tensorflow"
        train.assert_called_once()

    def test_dispatches_to_pytorch(self, indicators_df):
        """pytorch バックエンドでは PyTorch 実装へ委譲すること"""
        with patch("src.ml.deep_learning.resolve_price_backend", return_value="pytorch"), \
             patch("src.ml.deep_learning.train_pytorch_price_predictor",
                   return_value={"backend": "pytorch"}) as train:
            assert train_price_predictor(indicators_df, "USDJPY", 200)["backend"] == "pytorch"
        train.assert_called_once()


class TestPredictPrice:
    """predict_price() のテスト"""

    def test_returns_cached_result(self):
        """キャッシュヒット時は再計算しないこと"""
        cached = {"symbol": "USDJPY", "status": "success"}
        with patch("src.ml.deep_learning.resolve_price_backend", return_value="sklearn"), \
             patch("src.ml.predictor.cache_get", return_value=cached), \
             patch("src.ml.predictor.MarketContext") as ctx:
            assert predict_price("USDJPY") is cached
        ctx.load.assert_not_called()

    def test_computes_and_caches(self, indicators_df):
        """未キャッシュなら計算してキャッシュへ保存すること"""
        from src.analysis.market_context import MarketContext

        context = MarketContext("USDJPY", 200, "database", indicators_df)
        with patch("src.ml.deep_learning.resolve_price_backend", return_value="sklearn"), \
             patch("src.ml.predictor.cache_get", return_value=None), \
             patch("src.ml.predictor.cache_put") as cache_put, \
             patch("src.ml.predictor.MarketContext.load", return_value=context):
            result = predict_price("usdjpy")

        assert result["symbol"] == "USDJPY"
        assert result["source"] == "database"
        cache_put.assert_called_once()

    def test_cache_key_includes_the_backend(self, indicators_df):
        """キャッシュキーにバックエンド名を含めること（切り替え時の混線防止）"""
        from src.analysis.market_context import MarketContext

        context = MarketContext("USDJPY", 200, "database", indicators_df)
        with patch("src.ml.deep_learning.resolve_price_backend", return_value="sklearn"), \
             patch("src.ml.predictor.cache_get", return_value=None) as cache_get, \
             patch("src.ml.predictor.cache_put"), \
             patch("src.ml.predictor.MarketContext.load", return_value=context):
            predict_price("USDJPY", days=90)

        assert "backend=sklearn" in cache_get.call_args[0][0]
        assert "days=90" in cache_get.call_args[0][0]
