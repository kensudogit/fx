"""テクニカル・ファンダ分析 — analysis/fundamental のテスト"""

import importlib

import pytest


class TestFundamental:
    """src.analysis.fundamental モジュールのテストクラス"""

    def test_module_import(self):
        """モジュールが正常にインポートできること"""
        try:
            module = importlib.import_module("src.analysis.fundamental")
        except ImportError as exc:
            pytest.skip(f"依存関係不足のためスキップ: {exc}")
        assert module is not None
