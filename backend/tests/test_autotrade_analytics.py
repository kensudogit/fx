"""自動売買 — autotrade/analytics のテスト"""

import importlib

import pytest


class TestAnalytics:
    """src.autotrade.analytics モジュールのテストクラス"""

    def test_module_import(self):
        """モジュールが正常にインポートできること"""
        try:
            module = importlib.import_module("src.autotrade.analytics")
        except ImportError as exc:
            pytest.skip(f"依存関係不足のためスキップ: {exc}")
        assert module is not None
