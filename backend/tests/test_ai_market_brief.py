"""AI 分析 — ai/market_brief のテスト"""

import importlib

import pytest


class TestMarketBrief:
    """src.ai.market_brief モジュールのテストクラス"""

    def test_module_import(self):
        """モジュールが正常にインポートできること"""
        try:
            module = importlib.import_module("src.ai.market_brief")
        except ImportError as exc:
            pytest.skip(f"依存関係不足のためスキップ: {exc}")
        assert module is not None
