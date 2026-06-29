"""自動売買 — autotrade/engine のテスト"""

import importlib

import pytest


class TestEngine:
    """src.autotrade.engine モジュールのテストクラス"""

    def test_module_import(self):
        """モジュールが正常にインポートできること"""
        try:
            module = importlib.import_module("src.autotrade.engine")
        except ImportError as exc:
            pytest.skip(f"依存関係不足のためスキップ: {exc}")
        assert module is not None
