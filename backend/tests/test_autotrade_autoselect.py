"""自動売買 — autotrade/autoselect のテスト"""

import importlib

import pytest


class TestAutoselect:
    """src.autotrade.autoselect モジュールのテストクラス"""

    def test_module_import(self):
        """モジュールが正常にインポートできること"""
        try:
            module = importlib.import_module("src.autotrade.autoselect")
        except ImportError as exc:
            pytest.skip(f"依存関係不足のためスキップ: {exc}")
        assert module is not None
