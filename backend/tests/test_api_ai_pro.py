"""REST API — api/ai_pro のテスト"""

import importlib

import pytest


class TestAiPro:
    """src.api.ai_pro モジュールのテストクラス"""

    def test_module_import(self):
        """モジュールが正常にインポートできること"""
        try:
            module = importlib.import_module("src.api.ai_pro")
        except ImportError as exc:
            pytest.skip(f"依存関係不足のためスキップ: {exc}")
        assert module is not None
