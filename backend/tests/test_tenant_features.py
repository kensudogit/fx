"""テナント OANDA 設定・スケジューラのテスト"""

from src.autotrade.models import DEFAULT_CONFIG, merge_config
from src.autotrade.scheduler import _tenant_due
from src.broker.tenant_oanda import resolve_oanda_credentials
from datetime import datetime, timezone, timedelta


def test_merge_config_scheduler_enabled_default():
    cfg = merge_config({})
    assert cfg["scheduler_enabled"] is True


def test_resolve_oanda_paper_mode():
    creds = resolve_oanda_credentials(tenant_id=1, trading_mode="paper")
    assert creds.mode == "paper"
    assert creds.configured is False


def test_tenant_due_respects_scheduler_disabled():
    from unittest.mock import patch

    now = datetime.now(timezone.utc)
    cfg = {**DEFAULT_CONFIG, "enabled": True, "scheduler_enabled": False}
    with patch("src.autotrade.scheduler.get_config", return_value=cfg):
        assert _tenant_due(99, now) is False


def test_tenant_due_after_interval():
    from unittest.mock import patch

    now = datetime.now(timezone.utc)
    cfg = {**DEFAULT_CONFIG, "enabled": True, "scheduler_enabled": True, "scheduler_interval_minutes": 15}
    with patch("src.autotrade.scheduler.get_config", return_value=cfg):
        with patch("src.autotrade.scheduler._tenant_last_run", {42: now - timedelta(minutes=20)}):
            assert _tenant_due(42, now) is True
