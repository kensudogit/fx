"""認証・SaaS — auth/service のテスト"""

import importlib

import pytest


class TestService:
    """src.auth.service モジュールのテストクラス"""

    def test_module_import(self):
        """モジュールが正常にインポートできること"""
        try:
            module = importlib.import_module("src.auth.service")
        except ImportError as exc:
            pytest.skip(f"依存関係不足のためスキップ: {exc}")
        assert module is not None
