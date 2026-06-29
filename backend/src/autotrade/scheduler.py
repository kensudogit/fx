"""
自動売買 — autotrade/scheduler

テナント別の自動取引スケジューラ。
このモジュールは FX トレード支援プラットフォームの一部です。
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from src.autotrade.engine import run_cycle
from src.autotrade.models import get_config, list_scheduler_eligible_tenant_ids
from src.config import settings
from src.infra.distributed_lock import lock_status

logger = logging.getLogger(__name__)

_task: asyncio.Task | None = None
_running = False
_tenant_state: dict[int | None, dict] = {}
_tenant_last_run: dict[int | None, datetime] = {}


def scheduler_status(tenant_id: int | None = None) -> dict:
    cfg = get_config(tenant_id)
    state = _tenant_state.get(tenant_id, {})
    return {
        "global_running": _running,
        "global_enabled": settings.autotrade_enabled,
        "tenant_scheduler_enabled": cfg.get("scheduler_enabled", True),
        "tenant_autotrade_enabled": cfg.get("enabled", False),
        "trading_mode": cfg.get("mode", "paper"),
        "interval_minutes": cfg.get("scheduler_interval_minutes", settings.autotrade_interval_minutes),
        "last_run_at": state.get("last_run_at"),
        "last_results_count": state.get("last_results_count", 0),
        "enabled_tenants": len(list_scheduler_eligible_tenant_ids()),
        "distributed_lock": lock_status(),
    }


def _tenant_due(tenant_id: int | None, now: datetime) -> bool:
    cfg = get_config(tenant_id)
    if not cfg.get("enabled") or not cfg.get("scheduler_enabled", True):
        return False
    interval = max(1, int(cfg.get("scheduler_interval_minutes", settings.autotrade_interval_minutes)))
    last = _tenant_last_run.get(tenant_id)
    if not last:
        return True
    return (now - last).total_seconds() >= interval * 60


async def _scheduler_loop():
    while _running:
        now = datetime.now(timezone.utc)
        try:
            tenant_ids = list_scheduler_eligible_tenant_ids()
            if not tenant_ids and settings.autotrade_enabled:
                cfg = get_config(None)
                if cfg.get("enabled") and cfg.get("scheduler_enabled", True):
                    tenant_ids = [None]

            for tid in tenant_ids:
                if not _tenant_due(tid, now):
                    continue
                results = await run_cycle(tid, trigger="scheduler")
                _tenant_last_run[tid] = now
                _tenant_state[tid] = {
                    "last_run_at": now.isoformat(),
                    "last_results_count": len(results),
                }
        except Exception as e:
            logger.exception("autotrade scheduler error: %s", e)

        await asyncio.sleep(60)


def start_scheduler():
    global _task, _running
    if _running:
        return
    _running = True
    _task = asyncio.create_task(_scheduler_loop())
    logger.info("autotrade scheduler started (per-tenant intervals)")


def stop_scheduler():
    global _task, _running
    _running = False
    if _task:
        _task.cancel()
        _task = None
    logger.info("autotrade scheduler stopped")


def set_tenant_scheduler_enabled(tenant_id: int | None, enabled: bool) -> dict:
    from src.autotrade.models import save_config

    cfg = get_config(tenant_id)
    saved = save_config({**cfg, "scheduler_enabled": enabled}, tenant_id)
    if not enabled:
        _tenant_last_run.pop(tenant_id, None)
    return saved
