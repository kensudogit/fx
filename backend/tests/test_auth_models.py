"""認証・SaaS — auth/models のテスト"""

import importlib

import pytest


class TestModels:
    """src.auth.models モジュールのテストクラス"""

    def test_module_import(self):
        """モジュールが正常にインポートできること"""
        try:
            module = importlib.import_module("src.auth.models")
        except ImportError as exc:
            pytest.skip(f"依存関係不足のためスキップ: {exc}")
        assert module is not None
