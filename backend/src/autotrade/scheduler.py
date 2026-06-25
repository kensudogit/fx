"""自動取引バックグラウンドスケジューラ"""

import asyncio
import logging

from src.autotrade.engine import run_cycle
from src.autotrade.models import get_config, list_enabled_tenant_ids
from src.config import settings

logger = logging.getLogger(__name__)

_task: asyncio.Task | None = None
_running = False
_last_run_at: str | None = None
_last_results_count = 0


def scheduler_status() -> dict:
    config = get_config(None)
    return {
        "scheduler_running": _running,
        "global_enabled": settings.autotrade_enabled,
        "last_run_at": _last_run_at,
        "last_results_count": _last_results_count,
        "interval_minutes": config.get("scheduler_interval_minutes", 15),
        "enabled_tenants": len(list_enabled_tenant_ids()),
    }


async def _scheduler_loop():
    global _last_run_at, _last_results_count
    while _running:
        config = get_config(None)
        interval = max(1, int(config.get("scheduler_interval_minutes", settings.autotrade_interval_minutes)))
        try:
            tenant_ids = list_enabled_tenant_ids()
            if not tenant_ids and settings.autotrade_enabled:
                cfg = get_config(None)
                if cfg.get("enabled"):
                    tenant_ids = [None]

            total = 0
            for tid in tenant_ids:
                results = await run_cycle(tid, trigger="scheduler")
                total += len(results)

            from datetime import datetime, timezone

            _last_run_at = datetime.now(timezone.utc).isoformat()
            _last_results_count = total
            if total:
                logger.info("autotrade scheduler: %d results", total)
        except Exception as e:
            logger.exception("autotrade scheduler error: %s", e)

        await asyncio.sleep(interval * 60)


def start_scheduler():
    global _task, _running
    if _running:
        return
    _running = True
    _task = asyncio.create_task(_scheduler_loop())
    logger.info("autotrade scheduler started")


def stop_scheduler():
    global _task, _running
    _running = False
    if _task:
        _task.cancel()
        _task = None
    logger.info("autotrade scheduler stopped")
