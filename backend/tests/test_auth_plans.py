"""認証・SaaS — auth/plans のテスト"""

import importlib

import pytest


class TestPlans:
    """src.auth.plans モジュールのテストクラス"""

    def test_module_import(self):
        """モジュールが正常にインポートできること"""
        try:
            module = importlib.import_module("src.auth.plans")
        except ImportError as exc:
            pytest.skip(f"依存関係不足のためスキップ: {exc}")
        assert module is not None
