"""自動取引 REST API"""

from pydantic import BaseModel, Field

from fastapi import APIRouter, HTTPException, Query, Request

from src.autotrade.engine import evaluate_symbol, run_cycle
from src.autotrade.models import DEFAULT_CONFIG, get_config, list_runs, save_config
from src.autotrade.scheduler import scheduler_status, start_scheduler, stop_scheduler
from src.auth.context import get_tenant_id
from src.data.sample_data import SYMBOL_BASE_PRICES

router = APIRouter(tags=["Auto Trade"])


class AutoTradeConfigBody(BaseModel):
    enabled: bool | None = None
    symbols: list[str] | None = None
    mode: str | None = Field(default=None, pattern="^(paper|live)$")
    min_confidence: int | None = Field(default=None, ge=30, le=95)
    risk_percent: float | None = Field(default=None, ge=0.1, le=10)
    account_balance: float | None = Field(default=None, ge=100)
    sources: list[str] | None = None
    require_mtf_alignment: bool | None = None
    event_blackout_hours: int | None = Field(default=None, ge=0, le=48)
    max_daily_trades: int | None = Field(default=None, ge=1, le=20)
    cooldown_minutes: int | None = Field(default=None, ge=0, le=1440)
    auto_execute_tradingview: bool | None = None
    max_lots: float | None = Field(default=None, ge=0.01, le=100)
    min_lots: float | None = Field(default=None, ge=0.01, le=10)
    scheduler_interval_minutes: int | None = Field(default=None, ge=1, le=1440)


def _validate_symbol(symbol: str) -> str:
    symbol = symbol.upper()
    if symbol not in SYMBOL_BASE_PRICES:
        raise HTTPException(status_code=404, detail=f"Symbol {symbol} not found")
    return symbol


def _tenant(request: Request) -> int | None:
    tenant = getattr(request.state, "tenant", None)
    return tenant.tenant_id if tenant else get_tenant_id()


@router.get("/api/autotrade/config")
async def autotrade_get_config(request: Request):
    tid = _tenant(request)
    cfg = get_config(tid)
    return {"config": cfg, "defaults": DEFAULT_CONFIG}


@router.put("/api/autotrade/config")
async def autotrade_update_config(body: AutoTradeConfigBody, request: Request):
    tid = _tenant(request)
    current = get_config(tid)
    updates = body.model_dump(exclude_none=True)
    if updates.get("symbols"):
        for s in updates["symbols"]:
            _validate_symbol(s)
    merged = save_config({**current, **updates}, tid)
    return {"config": merged}


@router.get("/api/autotrade/status")
async def autotrade_status(request: Request):
    tid = _tenant(request)
    cfg = get_config(tid)
    status = scheduler_status()
    recent = list_runs(5, tid)
    return {
        "config": cfg,
        "scheduler": status,
        "recent_runs": recent,
    }


@router.get("/api/autotrade/runs")
async def autotrade_runs(
    request: Request,
    symbol: str | None = None,
    limit: int = Query(default=30, le=100),
):
    tid = _tenant(request)
    if symbol:
        _validate_symbol(symbol)
    return {"runs": list_runs(limit, tid, symbol)}


@router.post("/api/autotrade/evaluate/{symbol}")
async def autotrade_evaluate(symbol: str, request: Request):
    sym = _validate_symbol(symbol)
    tid = _tenant(request)
    result = await evaluate_symbol(sym, tid, dry_run=True)
    return result


@router.post("/api/autotrade/run/{symbol}")
async def autotrade_run_symbol(symbol: str, request: Request):
    sym = _validate_symbol(symbol)
    tid = _tenant(request)
    cfg = get_config(tid)
    if not cfg.get("enabled"):
        raise HTTPException(status_code=400, detail="自動取引が無効です。設定で有効化してください。")
    result = await evaluate_symbol(sym, tid, dry_run=False)
    return result


@router.post("/api/autotrade/run")
async def autotrade_run_all(request: Request):
    tid = _tenant(request)
    cfg = get_config(tid)
    if not cfg.get("enabled"):
        raise HTTPException(status_code=400, detail="自動取引が無効です。設定で有効化してください。")
    results = await run_cycle(tid, trigger="manual")
    return {"results": results, "count": len(results)}


@router.post("/api/autotrade/scheduler/start")
async def autotrade_scheduler_start():
    start_scheduler()
    return {"ok": True, "scheduler": scheduler_status()}


@router.post("/api/autotrade/scheduler/stop")
async def autotrade_scheduler_stop():
    stop_scheduler()
    return {"ok": True, "scheduler": scheduler_status()}
