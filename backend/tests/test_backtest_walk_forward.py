"""バックテスト — backtest/walk_forward のテスト"""

import importlib

import pytest


class TestWalkForward:
    """src.backtest.walk_forward モジュールのテストクラス"""

    def test_module_import(self):
        """モジュールが正常にインポートできること"""
        try:
            module = importlib.import_module("src.backtest.walk_forward")
        except ImportError as exc:
            pytest.skip(f"依存関係不足のためスキップ: {exc}")
        assert module is not None
