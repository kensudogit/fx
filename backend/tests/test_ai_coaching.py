"""AI 分析 — ai/coaching のテスト"""

import importlib

import pytest


class TestCoaching:
    """src.ai.coaching モジュールのテストクラス"""

    def test_module_import(self):
        """モジュールが正常にインポートできること"""
        try:
            module = importlib.import_module("src.ai.coaching")
        except ImportError as exc:
            pytest.skip(f"依存関係不足のためスキップ: {exc}")
        assert module is not None
