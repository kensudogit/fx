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


class TestBackendResolution:
    """resolve_price_backend() のフォールバックテスト"""

    def test_explicit_sklearn_is_honoured(self):
        """sklearn を明示指定したらそのまま使うこと"""
        from src.ml.deep_learning import resolve_price_backend

        assert resolve_price_backend("sklearn") == "sklearn"

    def test_falls_back_when_framework_is_missing(self):
        """指定したフレームワークが未インストールなら sklearn へ倒すこと"""
        from unittest.mock import patch

        from src.ml.deep_learning import resolve_price_backend

        with patch("src.ml.deep_learning.check_ml_frameworks",
                   return_value={"tensorflow": False, "pytorch": False}):
            assert resolve_price_backend("tensorflow") == "sklearn"
            assert resolve_price_backend("pytorch") == "sklearn"
            assert resolve_price_backend("auto") == "sklearn"

    def test_auto_prefers_tensorflow(self):
        """auto では TensorFlow を最優先すること"""
        from unittest.mock import patch

        from src.ml.deep_learning import resolve_price_backend

        with patch("src.ml.deep_learning.check_ml_frameworks",
                   return_value={"tensorflow": True, "pytorch": True}):
            assert resolve_price_backend("auto") == "tensorflow"

    def test_auto_uses_pytorch_when_tensorflow_is_absent(self):
        """TensorFlow が無ければ PyTorch を選ぶこと"""
        from unittest.mock import patch

        from src.ml.deep_learning import resolve_price_backend

        with patch("src.ml.deep_learning.check_ml_frameworks",
                   return_value={"tensorflow": False, "pytorch": True}):
            assert resolve_price_backend("auto") == "pytorch"

    def test_uses_the_configured_default(self, override_settings):
        """引数省略時は設定値を使うこと"""
        from src.ml.deep_learning import resolve_price_backend

        override_settings(ml_price_backend="sklearn")
        assert resolve_price_backend() == "sklearn"

    def test_is_case_insensitive(self):
        """大文字で指定しても解釈できること"""
        from src.ml.deep_learning import resolve_price_backend

        assert resolve_price_backend("SKLEARN") == "sklearn"


class TestScalingHelpers:
    """スケーリング補助関数のテスト"""

    def sequences(self):
        """(samples, lookback, features) 形状のダミー系列を返す。"""
        rng = np.random.default_rng(0)
        return rng.normal(100, 10, (40, 5, 3))

    def test_scale_sequences_preserves_shape(self):
        """スケーリング後も形状が変わらないこと"""
        from src.ml.deep_learning import scale_sequences

        x = self.sequences()
        scaled, _ = scale_sequences(x)
        assert scaled.shape == x.shape

    def test_scale_sequences_normalizes(self):
        """特徴量ごとに平均 0・分散 1 へ正規化すること"""
        from src.ml.deep_learning import scale_sequences

        scaled, _ = scale_sequences(self.sequences())
        flat = scaled.reshape(-1, scaled.shape[-1])
        assert np.allclose(flat.mean(axis=0), 0, atol=1e-6)
        assert np.allclose(flat.std(axis=0), 1, atol=1e-6)

    def test_scale_sequences_reuses_a_fitted_scaler(self):
        """既存スケーラーを渡した場合は再フィットしないこと（リーク防止）"""
        from src.ml.deep_learning import scale_sequences

        train = self.sequences()
        _, scaler = scale_sequences(train)
        test = train + 50
        scaled, same = scale_sequences(test, scaler)

        assert same is scaler
        # 再フィットしていれば平均 0 になるはずだが、ここではずれる
        assert abs(scaled.reshape(-1, 3).mean()) > 0.1

    def test_scale_targets_and_inverse_roundtrip(self):
        """目的変数のスケーリングと逆変換で元に戻ること"""
        from src.ml.deep_learning import inverse_scale_target, scale_targets

        y = np.array([100.0, 110.0, 120.0, 130.0])
        scaled, scaler = scale_targets(y)

        assert scaled.ndim == 1
        assert inverse_scale_target(float(scaled[0]), scaler) == pytest.approx(100.0)

    def test_scale_single_sequence_adds_the_batch_axis(self):
        """推論用の 1 ウィンドウをバッチ形状へ整えること"""
        from src.ml.deep_learning import scale_sequences, scale_single_sequence

        x = self.sequences()
        _, scaler = scale_sequences(x)
        single = scale_single_sequence(x[-1], scaler)

        assert single.shape == (1, 5, 3)


class TestInsufficientData:
    """データ不足時の共通レスポンスのテスト"""

    def test_reports_status_and_message(self):
        """status と日本語メッセージを返すこと"""
        from src.ml.deep_learning import _insufficient

        result = _insufficient()
        assert result["status"] == "insufficient_data"
        assert "不足" in result["message"]

    def test_short_history_is_rejected(self):
        """学習に足りないデータではデータ不足として返すこと"""
        from src.analysis.technical import compute_all_indicators
        from src.ml.deep_learning import check_ml_frameworks, train_pytorch_price_predictor
        from tests.conftest import make_ohlcv

        if not check_ml_frameworks()["pytorch"]:
            pytest.skip("PyTorch not installed")

        short = compute_all_indicators(make_ohlcv(n=30))
        assert train_pytorch_price_predictor(short, "USDJPY", 30)["status"] == "insufficient_data"
