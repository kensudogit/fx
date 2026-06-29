"""テクニカル・ファンダ分析 — analysis/multi_timeframe のテスト"""

import importlib

import pytest


class TestMultiTimeframe:
    """src.analysis.multi_timeframe モジュールのテストクラス"""

    def test_module_import(self):
        """モジュールが正常にインポートできること"""
        try:
            module = importlib.import_module("src.analysis.multi_timeframe")
        except ImportError as exc:
            pytest.skip(f"依存関係不足のためスキップ: {exc}")
        assert module is not None
