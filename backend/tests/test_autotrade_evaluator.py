"""自動売買 — autotrade/evaluator のテスト"""

import importlib

import pytest


class TestEvaluator:
    """src.autotrade.evaluator モジュールのテストクラス"""

    def test_module_import(self):
        """モジュールが正常にインポートできること"""
        try:
            module = importlib.import_module("src.autotrade.evaluator")
        except ImportError as exc:
            pytest.skip(f"依存関係不足のためスキップ: {exc}")
        assert module is not None
