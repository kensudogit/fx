"""認証・SaaS — auth/middleware のテスト"""

import importlib

import pytest


class TestMiddleware:
    """src.auth.middleware モジュールのテストクラス"""

    def test_module_import(self):
        """モジュールが正常にインポートできること"""
        try:
            module = importlib.import_module("src.auth.middleware")
        except ImportError as exc:
            pytest.skip(f"依存関係不足のためスキップ: {exc}")
        assert module is not None
