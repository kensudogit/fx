"""自動取引 REST API"""

from pydantic import BaseModel, Field

from fastapi import APIRouter, HTTPException, Query, Request

from src.autotrade.analytics import build_performance
from src.autotrade.autoselect import autoselect
from src.autotrade.engine import evaluate_symbol, run_cycle
from src.autotrade.models import DEFAULT_CONFIG, get_config, list_runs, save_config
from src.autotrade.positions import list_open_positions
from src.autotrade.presets import apply_preset, list_presets
from src.autotrade.scheduler import scheduler_status, set_tenant_scheduler_enabled, start_scheduler, stop_scheduler
from src.autotrade.simulation import simulate_strategy
from src.auth.context import get_tenant_id
from src.data.sample_data import SYMBOL_BASE_PRICES

router = APIRouter(tags=["Auto Trade"])


class AutoTradeConfigBody(BaseModel):
    enabled: bool | None = None
    symbols: list[str] | None = None
    mode: str | None = Field(default=None, pattern="^(paper|live)$")
    strategy_preset: str | None = None
    min_confidence: int | None = Field(default=None, ge=30, le=95)
    risk_percent: float | None = Field(default=None, ge=0.1, le=10)
    account_balance: float | None = Field(default=None, ge=100)
    sources: list[str] | None = None
    require_mtf_alignment: bool | None = None
    event_blackout_hours: int | None = Field(default=None, ge=0, le=48)
    max_daily_trades: int | None = Field(default=None, ge=1, le=20)
    cooldown_minutes: int | None = Field(default=None, ge=0, le=1440)
    auto_execute_tradingview: bool | None = None
    auto_exit_on_reverse: bool | None = None
    use_stop_loss: bool | None = None
    use_take_profit: bool | None = None
    risk_reward: float | None = Field(default=None, ge=0.5, le=5)
    max_lots: float | None = Field(default=None, ge=0.01, le=100)
    min_lots: float | None = Field(default=None, ge=0.01, le=10)
    min_units: int | None = Field(default=None, ge=1000, le=1_000_000)
    scheduler_interval_minutes: int | None = Field(default=None, ge=1, le=1440)
    scheduler_enabled: bool | None = None
    allow_add_to_position: bool | None = None


class AutoSelectBody(BaseModel):
    capital: str = Field(default="medium", pattern="^(small|medium|large)$")
    horizon: str = Field(default="medium", pattern="^(short|medium|long)$")
    risk_appetite: str = Field(default="medium", pattern="^(low|medium|high)$")
    style: str = Field(default="auto", pattern="^(auto|range|trend)$")
    preferred_symbols: list[str] | None = None
    apply: bool = False


class ApplyPresetBody(BaseModel):
    preset_id: str


def _validate_symbol(symbol: str) -> str:
    symbol = symbol.upper()
    if symbol not in SYMBOL_BASE_PRICES:
        raise HTTPException(status_code=404, detail=f"Symbol {symbol} not found")
    return symbol


def _tenant(request: Request) -> int | None:
    tenant = getattr(request.state, "tenant", None)
    return tenant.tenant_id if tenant else get_tenant_id()


@router.get("/api/autotrade/presets")
async def autotrade_presets():
    return {"presets": list_presets()}


@router.post("/api/autotrade/presets/apply")
async def autotrade_apply_preset(body: ApplyPresetBody, request: Request):
    tid = _tenant(request)
    try:
        merged = apply_preset(body.preset_id, get_config(tid))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    saved = save_config(merged, tid)
    return {"config": saved, "preset_id": body.preset_id}


@router.post("/api/autotrade/autoselect")
async def autotrade_autoselect(body: AutoSelectBody, request: Request):
    tid = _tenant(request)
    result = autoselect(
        body.capital, body.horizon, body.risk_appetite, body.style, body.preferred_symbols
    )
    if body.apply:
        result["config"] = save_config(result["config"], tid)
    return result


@router.get("/api/autotrade/simulate/{symbol}")
async def autotrade_simulate(
    symbol: str,
    days: int = Query(default=365, ge=90, le=500),
    account_balance: float = Query(default=10000, ge=100),
    preset_id: str = Query(default="balanced"),
    risk_percent: float = Query(default=1.0, ge=0.1, le=10),
):
    sym = _validate_symbol(symbol)
    return simulate_strategy(sym, days, account_balance, preset_id, risk_percent)


@router.get("/api/autotrade/performance")
async def autotrade_performance(request: Request, limit: int = Query(default=100, le=200)):
    tid = _tenant(request)
    return build_performance(tid, limit)


@router.get("/api/autotrade/positions")
async def autotrade_positions(request: Request, symbol: str | None = None):
    tid = _tenant(request)
    if symbol:
        _validate_symbol(symbol)
    return {"positions": list_open_positions(tid, symbol)}


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
    status = scheduler_status(tid)
    recent = list_runs(5, tid)
    performance = build_performance(tid, 50)
    return {
        "config": cfg,
        "scheduler": status,
        "recent_runs": recent,
        "performance": performance,
        "open_positions": list_open_positions(tid),
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
async def autotrade_scheduler_start(request: Request):
    tid = _tenant(request)
    set_tenant_scheduler_enabled(tid, True)
    start_scheduler()
    return {"ok": True, "scheduler": scheduler_status(tid)}


@router.post("/api/autotrade/scheduler/stop")
async def autotrade_scheduler_stop(request: Request):
    tid = _tenant(request)
    set_tenant_scheduler_enabled(tid, False)
    return {"ok": True, "scheduler": scheduler_status(tid)}
