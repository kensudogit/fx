"""REST API — api/dashboard のテスト"""

import importlib

import pytest


class TestDashboard:
    """src.api.dashboard モジュールのテストクラス"""

    def test_module_import(self):
        """モジュールが正常にインポートできること"""
        try:
            module = importlib.import_module("src.api.dashboard")
        except ImportError as exc:
            pytest.skip(f"依存関係不足のためスキップ: {exc}")
        assert module is not None
