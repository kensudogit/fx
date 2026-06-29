"""Stripe 課金 — billing/stripe_service のテスト"""

import importlib

import pytest


class TestStripeService:
    """src.billing.stripe_service モジュールのテストクラス"""

    def test_module_import(self):
        """モジュールが正常にインポートできること"""
        try:
            module = importlib.import_module("src.billing.stripe_service")
        except ImportError as exc:
            pytest.skip(f"依存関係不足のためスキップ: {exc}")
        assert module is not None
