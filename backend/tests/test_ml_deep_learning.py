"""機械学習 — ml/deep_learning のテスト"""

import importlib

import numpy as np
import pandas as pd
import pytest


class TestDeepLearning:
    """src.ml.deep_learning モジュールのテストクラス"""

    def test_module_import(self):
        """モジュールが正常にインポートできること"""
        try:
            module = importlib.import_module("src.ml.deep_learning")
        except ImportError as exc:
            pytest.skip(f"依存関係不足のためスキップ: {exc}")
        assert module is not None

    def test_check_ml_frameworks(self):
        from src.ml.deep_learning import check_ml_frameworks

        frameworks = check_ml_frameworks()
        assert "tensorflow" in frameworks
        assert "pytorch" in frameworks

    def test_resolve_price_backend_auto(self):
        from src.ml.deep_learning import check_ml_frameworks, resolve_price_backend

        backend = resolve_price_backend("auto")
        frameworks = check_ml_frameworks()
        if frameworks["tensorflow"]:
            assert backend == "tensorflow"
        elif frameworks["pytorch"]:
            assert backend == "pytorch"
        else:
            assert backend == "sklearn"

    def test_prepare_sequences(self):
        from src.ml.deep_learning import prepare_sequences

        n = 80
        df = pd.DataFrame(
            {
                "close": np.linspace(100, 110, n),
                "sma_20": np.linspace(99, 109, n),
                "sma_50": np.linspace(98, 108, n),
                "rsi": np.full(n, 50.0),
                "macd": np.zeros(n),
                "macd_signal": np.zeros(n),
                "stoch_k": np.full(n, 50.0),
                "stoch_d": np.full(n, 50.0),
            }
        )
        x, y = prepare_sequences(df, lookback=10)
        assert x.shape[0] == len(y)
        assert x.shape[1:] == (10, 8)
        assert y.ndim == 1

    def test_create_lstm_model(self):
        from src.ml.deep_learning import check_ml_frameworks, create_lstm_model

        if not check_ml_frameworks()["tensorflow"]:
            pytest.skip("TensorFlow not installed")
        model = create_lstm_model((10, 4), units=16)
        assert model is not None
        assert model.count_params() > 0

    def test_create_pytorch_lstm(self):
        from src.ml.deep_learning import check_ml_frameworks, create_pytorch_lstm

        if not check_ml_frameworks()["pytorch"]:
            pytest.skip("PyTorch not installed")
        model = create_pytorch_lstm(4, hidden_size=16, num_layers=1)
        assert model is not None

    def test_tensorflow_price_predictor(self):
        from src.analysis.technical import compute_all_indicators
        from src.data.market_data import get_ohlcv_data
        from src.ml.deep_learning import check_ml_frameworks, train_tensorflow_price_predictor

        if not check_ml_frameworks()["tensorflow"]:
            pytest.skip("TensorFlow not installed")

        df, _ = get_ohlcv_data("USDJPY", 200)
        result_df = compute_all_indicators(df)
        result = train_tensorflow_price_predictor(result_df, "USDJPY", 200)
        assert result["status"] == "success"
        assert result["backend"] == "tensorflow"
        assert "prediction" in result

    def test_pytorch_price_predictor(self):
        from src.analysis.technical import compute_all_indicators
        from src.data.market_data import get_ohlcv_data
        from src.ml.deep_learning import check_ml_frameworks, train_pytorch_price_predictor

        if not check_ml_frameworks()["pytorch"]:
            pytest.skip("PyTorch not installed")

        df, _ = get_ohlcv_data("EURUSD", 200)
        result_df = compute_all_indicators(df)
        result = train_pytorch_price_predictor(result_df, "EURUSD", 200)
        assert result["status"] == "success"
        assert result["backend"] == "pytorch"
        assert "prediction" in result
