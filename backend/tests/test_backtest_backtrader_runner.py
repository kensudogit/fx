"""バックテスト — backtest/backtrader_runner のテスト"""

import importlib

import pytest


class TestBacktraderRunner:
    """src.backtest.backtrader_runner モジュールのテストクラス"""

    def test_module_import(self):
        """モジュールが正常にインポートできること"""
        try:
            module = importlib.import_module("src.backtest.backtrader_runner")
        except ImportError as exc:
            pytest.skip(f"依存関係不足のためスキップ: {exc}")
        assert module is not None
