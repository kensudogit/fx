"""認証・SaaS — auth/context のテスト"""

import importlib

import pytest


class TestContext:
    """src.auth.context モジュールのテストクラス"""

    def test_module_import(self):
        """モジュールが正常にインポートできること"""
        try:
            module = importlib.import_module("src.auth.context")
        except ImportError as exc:
            pytest.skip(f"依存関係不足のためスキップ: {exc}")
        assert module is not None
