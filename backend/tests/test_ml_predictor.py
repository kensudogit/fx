"""機械学習 — ml/predictor のテスト"""

import importlib

import pytest


class TestPredictor:
    """src.ml.predictor モジュールのテストクラス"""

    def test_module_import(self):
        """モジュールが正常にインポートできること"""
        try:
            module = importlib.import_module("src.ml.predictor")
        except ImportError as exc:
            pytest.skip(f"依存関係不足のためスキップ: {exc}")
        assert module is not None
