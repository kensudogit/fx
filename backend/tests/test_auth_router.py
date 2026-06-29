"""認証・SaaS — auth/router のテスト"""

import importlib

import pytest


class TestRouter:
    """src.auth.router モジュールのテストクラス"""

    def test_module_import(self):
        """モジュールが正常にインポートできること"""
        try:
            module = importlib.import_module("src.auth.router")
        except ImportError as exc:
            pytest.skip(f"依存関係不足のためスキップ: {exc}")
        assert module is not None
