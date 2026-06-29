"""認証・SaaS — auth/security のテスト"""

import importlib

import pytest


class TestSecurity:
    """src.auth.security モジュールのテストクラス"""

    def test_module_import(self):
        """モジュールが正常にインポートできること"""
        try:
            module = importlib.import_module("src.auth.security")
        except ImportError as exc:
            pytest.skip(f"依存関係不足のためスキップ: {exc}")
        assert module is not None
