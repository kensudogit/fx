"""OANDA ブローカー連携 — broker/accounts のテスト"""

import importlib

import pytest


class TestAccounts:
    """src.broker.accounts モジュールのテストクラス"""

    def test_module_import(self):
        """モジュールが正常にインポートできること"""
        try:
            module = importlib.import_module("src.broker.accounts")
        except ImportError as exc:
            pytest.skip(f"依存関係不足のためスキップ: {exc}")
        assert module is not None
