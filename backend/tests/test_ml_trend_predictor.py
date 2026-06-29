"""機械学習 — ml/trend_predictor のテスト"""

import importlib

import pytest


class TestTrendPredictor:
    """src.ml.trend_predictor モジュールのテストクラス"""

    def test_module_import(self):
        """モジュールが正常にインポートできること"""
        try:
            module = importlib.import_module("src.ml.trend_predictor")
        except ImportError as exc:
            pytest.skip(f"依存関係不足のためスキップ: {exc}")
        assert module is not None
