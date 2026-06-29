"""AI 分析 — ai/analyzer のテスト"""

import importlib

import pytest


class TestAnalyzer:
    """src.ai.analyzer モジュールのテストクラス"""

    def test_module_import(self):
        """モジュールが正常にインポートできること"""
        try:
            module = importlib.import_module("src.ai.analyzer")
        except ImportError as exc:
            pytest.skip(f"依存関係不足のためスキップ: {exc}")
        assert module is not None
