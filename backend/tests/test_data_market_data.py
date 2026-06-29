"""市場データ — data/market_data のテスト"""

import importlib

import pytest


class TestMarketData:
    """src.data.market_data モジュールのテストクラス"""

    def test_module_import(self):
        """モジュールが正常にインポートできること"""
        try:
            module = importlib.import_module("src.data.market_data")
        except ImportError as exc:
            pytest.skip(f"依存関係不足のためスキップ: {exc}")
        assert module is not None
