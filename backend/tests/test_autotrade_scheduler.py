"""自動売買スケジューラ — src.autotrade.scheduler のテスト

設定取得・分散ロックはモックへ差し替え、
実行タイミング判定と起動・停止のライフサイクルを検証する。
"""

import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

import src.autotrade.scheduler as scheduler
from src.autotrade.models import DEFAULT_CONFIG
from src.autotrade.scheduler import (
    _tenant_due,
    scheduler_status,
    set_tenant_scheduler_enabled,
    start_scheduler,
    stop_scheduler,
)


@pytest.fixture(autouse=True)
def reset_scheduler_state():
    """モジュールのグローバル状態を初期化する。"""
    scheduler._running = False
    scheduler._task = None
    scheduler._tenant_last_run = {}
    scheduler._tenant_state = {}
    yield
    scheduler._running = False
    scheduler._task = None
    scheduler._tenant_last_run = {}
    scheduler._tenant_state = {}


def config(**overrides) -> dict:
    """自動売買設定を組み立てる。"""
    return {**DEFAULT_CONFIG, "enabled": True, "scheduler_enabled": True, **overrides}


class TestTenantDue:
    """_tenant_due() のテスト"""

    def test_disabled_autotrade_is_never_due(self):
        """自動取引が無効なら実行しないこと"""
        with patch("src.autotrade.scheduler.get_config", return_value=config(enabled=False)):
            assert _tenant_due(1, datetime.now(timezone.utc)) is False

    def test_disabled_scheduler_is_never_due(self):
        """スケジューラが無効なら実行しないこと"""
        with patch("src.autotrade.scheduler.get_config",
                   return_value=config(scheduler_enabled=False)):
            assert _tenant_due(1, datetime.now(timezone.utc)) is False

    def test_first_run_is_immediate(self):
        """一度も実行していなければ即座に対象になること"""
        with patch("src.autotrade.scheduler.get_config", return_value=config()):
            assert _tenant_due(1, datetime.now(timezone.utc)) is True

    def test_not_due_before_the_interval(self):
        """実行間隔を満たすまでは対象外であること"""
        now = datetime.now(timezone.utc)
        scheduler._tenant_last_run[1] = now - timedelta(minutes=5)
        with patch("src.autotrade.scheduler.get_config",
                   return_value=config(scheduler_interval_minutes=15)):
            assert _tenant_due(1, now) is False

    def test_due_after_the_interval(self):
        """実行間隔を超えたら対象になること"""
        now = datetime.now(timezone.utc)
        scheduler._tenant_last_run[1] = now - timedelta(minutes=20)
        with patch("src.autotrade.scheduler.get_config",
                   return_value=config(scheduler_interval_minutes=15)):
            assert _tenant_due(1, now) is True

    def test_interval_boundary_is_inclusive(self):
        """ちょうど間隔が経過した時点で対象になること"""
        now = datetime.now(timezone.utc)
        scheduler._tenant_last_run[1] = now - timedelta(minutes=15)
        with patch("src.autotrade.scheduler.get_config",
                   return_value=config(scheduler_interval_minutes=15)):
            assert _tenant_due(1, now) is True

    def test_interval_is_at_least_one_minute(self):
        """間隔 0 を指定しても 1 分未満にはならないこと（暴走防止）"""
        now = datetime.now(timezone.utc)
        scheduler._tenant_last_run[1] = now - timedelta(seconds=10)
        with patch("src.autotrade.scheduler.get_config",
                   return_value=config(scheduler_interval_minutes=0)):
            assert _tenant_due(1, now) is False

    def test_tenants_are_tracked_independently(self):
        """テナントごとに実行時刻を管理すること"""
        now = datetime.now(timezone.utc)
        scheduler._tenant_last_run[1] = now
        with patch("src.autotrade.scheduler.get_config",
                   return_value=config(scheduler_interval_minutes=15)):
            assert _tenant_due(1, now) is False
            assert _tenant_due(2, now) is True


class TestSchedulerStatus:
    """scheduler_status() のテスト"""

    def _status(self, cfg=None, tenants=(1, 2)):
        with patch("src.autotrade.scheduler.get_config", return_value=cfg or config()), \
             patch("src.autotrade.scheduler.list_scheduler_eligible_tenant_ids",
                   return_value=list(tenants)), \
             patch("src.autotrade.scheduler.lock_status",
                   return_value={"backend": "in_process", "redis_url_configured": False}):
            return scheduler_status(tenant_id=1)

    def test_returns_expected_keys(self):
        """状態のキーが揃っていること"""
        assert set(self._status()) == {
            "global_running", "global_enabled", "tenant_scheduler_enabled",
            "tenant_autotrade_enabled", "trading_mode", "interval_minutes",
            "last_run_at", "last_results_count", "enabled_tenants", "distributed_lock",
        }

    def test_reports_the_running_flag(self):
        """稼働状態を反映すること"""
        assert self._status()["global_running"] is False
        scheduler._running = True
        assert self._status()["global_running"] is True

    def test_reports_tenant_settings(self):
        """テナント設定（有効状態・モード・間隔）を返すこと"""
        status = self._status(config(mode="live", scheduler_interval_minutes=30))
        assert status["tenant_autotrade_enabled"] is True
        assert status["trading_mode"] == "live"
        assert status["interval_minutes"] == 30

    def test_counts_eligible_tenants(self):
        """対象テナント数を返すこと"""
        assert self._status(tenants=(1, 2, 3))["enabled_tenants"] == 3

    def test_includes_lock_backend(self):
        """分散ロックの状態を含めること（多重実行防止の確認用）"""
        assert self._status()["distributed_lock"]["backend"] == "in_process"

    def test_reports_last_run_state(self):
        """最終実行の情報を返すこと"""
        scheduler._tenant_state[1] = {"last_run_at": "2026-01-01T00:00:00+00:00",
                                      "last_results_count": 3}
        status = self._status()

        assert status["last_run_at"] == "2026-01-01T00:00:00+00:00"
        assert status["last_results_count"] == 3

    def test_defaults_when_never_run(self):
        """未実行なら last_run_at は None・件数 0 であること"""
        status = self._status()
        assert status["last_run_at"] is None
        assert status["last_results_count"] == 0


class TestStartStopScheduler:
    """start_scheduler() / stop_scheduler() のテスト"""

    def test_start_sets_running_and_creates_a_task(self):
        """起動でフラグを立ててバックグラウンドタスクを作ること"""
        async def main():
            start_scheduler()
            running, task = scheduler._running, scheduler._task
            stop_scheduler()
            return running, task

        running, task = asyncio.run(main())
        assert running is True
        assert task is not None

    def test_start_is_idempotent(self):
        """既に稼働中なら二重起動しないこと"""
        async def main():
            start_scheduler()
            first = scheduler._task
            start_scheduler()
            second = scheduler._task
            stop_scheduler()
            return first, second

        first, second = asyncio.run(main())
        assert first is second

    def test_stop_clears_the_state(self):
        """停止でフラグとタスクを片付けること"""
        async def main():
            start_scheduler()
            stop_scheduler()

        asyncio.run(main())
        assert scheduler._running is False
        assert scheduler._task is None

    def test_stop_without_start_is_safe(self):
        """起動していなくても停止で例外にならないこと"""
        stop_scheduler()
        assert scheduler._running is False


class TestSetTenantSchedulerEnabled:
    """set_tenant_scheduler_enabled() のテスト"""

    def test_enables_the_scheduler(self):
        """有効化を設定へ保存すること"""
        with patch("src.autotrade.scheduler.get_config", return_value=config()), \
             patch("src.autotrade.models.save_config",
                   side_effect=lambda cfg, tid: cfg) as save:
            result = set_tenant_scheduler_enabled(1, True)

        assert result["scheduler_enabled"] is True
        assert save.call_args[0][1] == 1

    def test_disabling_resets_the_last_run(self):
        """無効化したら最終実行時刻をリセットすること（再開時に即実行できる）"""
        scheduler._tenant_last_run[1] = datetime.now(timezone.utc)
        with patch("src.autotrade.scheduler.get_config", return_value=config()), \
             patch("src.autotrade.models.save_config", side_effect=lambda cfg, tid: cfg):
            set_tenant_scheduler_enabled(1, False)

        assert 1 not in scheduler._tenant_last_run

    def test_enabling_keeps_the_last_run(self):
        """有効化では最終実行時刻を保持すること"""
        stamp = datetime.now(timezone.utc)
        scheduler._tenant_last_run[1] = stamp
        with patch("src.autotrade.scheduler.get_config", return_value=config()), \
             patch("src.autotrade.models.save_config", side_effect=lambda cfg, tid: cfg):
            set_tenant_scheduler_enabled(1, True)

        assert scheduler._tenant_last_run[1] == stamp

    def test_preserves_other_settings(self):
        """他の設定項目を壊さないこと"""
        with patch("src.autotrade.scheduler.get_config",
                   return_value=config(mode="live", min_confidence=80)), \
             patch("src.autotrade.models.save_config", side_effect=lambda cfg, tid: cfg):
            result = set_tenant_scheduler_enabled(1, False)

        assert result["mode"] == "live"
        assert result["min_confidence"] == 80
