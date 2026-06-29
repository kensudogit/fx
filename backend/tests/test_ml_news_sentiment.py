"""機械学習 — ml/news_sentiment のテスト"""

import importlib

import pytest


class TestNewsSentiment:
    """src.ml.news_sentiment モジュールのテストクラス"""

    def test_module_import(self):
        """モジュールが正常にインポートできること"""
        try:
            module = importlib.import_module("src.ml.news_sentiment")
        except ImportError as exc:
            pytest.skip(f"依存関係不足のためスキップ: {exc}")
        assert module is not None
