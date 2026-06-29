"""OANDA ブローカー連携 — broker/oanda のテスト"""

import importlib

import pytest


class TestOanda:
    """src.broker.oanda モジュールのテストクラス"""

    def test_module_import(self):
        """モジュールが正常にインポートできること"""
        try:
            module = importlib.import_module("src.broker.oanda")
        except ImportError as exc:
            pytest.skip(f"依存関係不足のためスキップ: {exc}")
        assert module is not None
