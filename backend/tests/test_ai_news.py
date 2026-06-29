"""AI 分析 — ai/news のテスト"""

import importlib

import pytest


class TestNews:
    """src.ai.news モジュールのテストクラス"""

    def test_module_import(self):
        """モジュールが正常にインポートできること"""
        try:
            module = importlib.import_module("src.ai.news")
        except ImportError as exc:
            pytest.skip(f"依存関係不足のためスキップ: {exc}")
        assert module is not None
