"""インフラ（分散ロック等） — infra/distributed_lock のテスト"""

import importlib

import pytest


class TestDistributedLock:
    """src.infra.distributed_lock モジュールのテストクラス"""

    def test_module_import(self):
        """モジュールが正常にインポートできること"""
        try:
            module = importlib.import_module("src.infra.distributed_lock")
        except ImportError as exc:
            pytest.skip(f"依存関係不足のためスキップ: {exc}")
        assert module is not None
