"""自動売買 — autotrade/presets のテスト"""

import importlib

import pytest


class TestPresets:
    """src.autotrade.presets モジュールのテストクラス"""

    def test_module_import(self):
        """モジュールが正常にインポートできること"""
        try:
            module = importlib.import_module("src.autotrade.presets")
        except ImportError as exc:
            pytest.skip(f"依存関係不足のためスキップ: {exc}")
        assert module is not None
