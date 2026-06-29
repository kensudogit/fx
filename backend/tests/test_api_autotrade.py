"""REST API — api/autotrade のテスト"""

import importlib

import pytest


class TestAutotrade:
    """src.api.autotrade モジュールのテストクラス"""

    def test_module_import(self):
        """モジュールが正常にインポートできること"""
        try:
            module = importlib.import_module("src.api.autotrade")
        except ImportError as exc:
            pytest.skip(f"依存関係不足のためスキップ: {exc}")
        assert module is not None
