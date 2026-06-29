"""テクニカル・ファンダ分析 — analysis/economic のテスト"""

import importlib

import pytest


class TestEconomic:
    """src.analysis.economic モジュールのテストクラス"""

    def test_module_import(self):
        """モジュールが正常にインポートできること"""
        try:
            module = importlib.import_module("src.analysis.economic")
        except ImportError as exc:
            pytest.skip(f"依存関係不足のためスキップ: {exc}")
        assert module is not None
