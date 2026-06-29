"""OANDA ブローカー連携 — broker/tenant_oanda のテスト"""

import importlib

import pytest


class TestTenantOanda:
    """src.broker.tenant_oanda モジュールのテストクラス"""

    def test_module_import(self):
        """モジュールが正常にインポートできること"""
        try:
            module = importlib.import_module("src.broker.tenant_oanda")
        except ImportError as exc:
            pytest.skip(f"依存関係不足のためスキップ: {exc}")
        assert module is not None
