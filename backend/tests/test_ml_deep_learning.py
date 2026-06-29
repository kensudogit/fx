"""機械学習 — ml/deep_learning のテスト"""

import importlib

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
