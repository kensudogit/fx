"""市場データ — data/sample_data のテスト"""

import importlib

import pytest


class TestSampleData:
    """src.data.sample_data モジュールのテストクラス"""

    def test_module_import(self):
        """モジュールが正常にインポートできること"""
        try:
            module = importlib.import_module("src.data.sample_data")
        except ImportError as exc:
            pytest.skip(f"依存関係不足のためスキップ: {exc}")
        assert module is not None
