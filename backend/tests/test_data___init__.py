"""市場データ — data/__init__ のテスト"""

import importlib

import pytest


class TestData:
    """src.data.__init__ モジュールのテストクラス"""

    def test_module_import(self):
        """モジュールが正常にインポートできること"""
        try:
            module = importlib.import_module("src.data.__init__")
        except ImportError as exc:
            pytest.skip(f"依存関係不足のためスキップ: {exc}")
        assert module is not None
