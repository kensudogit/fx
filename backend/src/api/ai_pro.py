"""AI Pro 統合 API"""

from pydantic import BaseModel, Field

from fastapi import APIRouter, HTTPException, Query, Request

from src.ai.chat import chat, list_sessions
from src.ai.coaching import generate_coaching
from src.ai.market_brief import build_market_brief
from src.ai.signals import generate_ai_signals
from src.analysis.risk_advanced import assess_advanced_risk
from src.auth.context import get_tenant_id
from src.backtest.backtrader_runner import run_backtrader_backtest
from src.backtest.walk_forward import run_walk_forward
from src.broker.accounts import build_portfolio_overview, create_account, list_accounts
from src.analysis.signals import backtest_signals
from src.analysis.technical import compute_all_indicators
from src.data.market_data import get_ohlcv_data
from src.data.sample_data import SYMBOL_BASE_PRICES

router = APIRouter(tags=["AI Pro"])


def _validate_symbol(symbol: str) -> str:
    symbol = symbol.upper()
    if symbol not in SYMBOL_BASE_PRICES:
        raise HTTPException(status_code=404, detail=f"Symbol {symbol} not found")
    return symbol


class ChatBody(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    symbol: str = "USDJPY"
    session_id: int | None = None


class AccountBody(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    broker: str = "paper"
    balance: float = Field(default=10000, ge=0)
    is_default: bool = False


def _tenant_user(request: Request) -> tuple[int | None, int | None]:
    tenant = getattr(request.state, "tenant", None)
    if not tenant:
        return get_tenant_id(), None
    return tenant.tenant_id, tenant.user_id


@router.get("/api/pro/signals/{symbol}")
async def pro_signals(symbol: str, days: int = Query(default=200, ge=60, le=500)):
    symbol = _validate_symbol(symbol)
    return await generate_ai_signals(symbol, days)


@router.get("/api/pro/market-brief/{symbol}")
async def pro_market_brief(symbol: str):
    symbol = _validate_symbol(symbol)
    return await build_market_brief(symbol)


@router.get("/api/pro/coaching/{symbol}")
async def pro_coaching(symbol: str, request: Request):
    symbol = _validate_symbol(symbol)
    tenant_id, _ = _tenant_user(request)
    return await generate_coaching(symbol, tenant_id)


@router.get("/api/pro/backtest/{symbol}")
async def pro_backtest(symbol: str, days: int = Query(default=200, ge=90, le=500)):
    sym = _validate_symbol(symbol)
    df, source = get_ohlcv_data(sym, days)
    result_df = compute_all_indicators(df)
    simple = backtest_signals(result_df)
    bt = run_backtrader_backtest(sym, days)
    wf = run_walk_forward(sym, max(days, 300))
    return {"symbol": sym, "source": source, "simple": simple, "backtrader": bt, "walk_forward": wf}


@router.get("/api/pro/walk-forward/{symbol}")
async def pro_walk_forward(symbol: str, days: int = Query(default=365, ge=180, le=500)):
    return run_walk_forward(_validate_symbol(symbol), days)


@router.get("/api/pro/risk/{symbol}")
async def pro_risk(
    symbol: str,
    account_balance: float = Query(default=10000, ge=100),
    risk_percent: float = Query(default=1.0, ge=0.1, le=10),
    days: int = Query(default=200, ge=60, le=500),
):
    return assess_advanced_risk(_validate_symbol(symbol), account_balance, risk_percent, days)


@router.get("/api/pro/portfolio")
async def pro_portfolio(request: Request):
    tenant_id, _ = _tenant_user(request)
    return build_portfolio_overview(tenant_id)


@router.get("/api/pro/accounts")
async def pro_accounts(request: Request):
    tenant_id, _ = _tenant_user(request)
    return {"accounts": list_accounts(tenant_id)}


@router.post("/api/pro/accounts")
async def pro_create_account(body: AccountBody, request: Request):
    tenant_id, _ = _tenant_user(request)
    return create_account(tenant_id, body.name, body.broker, body.balance, body.is_default)


@router.post("/api/pro/chat")
async def pro_chat(body: ChatBody, request: Request):
    symbol = _validate_symbol(body.symbol)
    tenant_id, user_id = _tenant_user(request)
    return await chat(body.message, symbol, body.session_id, tenant_id, user_id)


@router.get("/api/pro/chat/sessions")
async def pro_chat_sessions(request: Request):
    tenant_id, _ = _tenant_user(request)
    return {"sessions": list_sessions(tenant_id)}


@router.get("/api/pro/hub/{symbol}")
async def pro_hub(symbol: str, request: Request, days: int = Query(default=200)):
    sym = _validate_symbol(symbol)
    tenant_id, _ = _tenant_user(request)
    signals = await generate_ai_signals(sym, days)
    brief = await build_market_brief(sym)
    risk = assess_advanced_risk(sym)
    portfolio = build_portfolio_overview(tenant_id)
    return {
        "symbol": sym,
        "signals": signals,
        "market_brief": brief,
        "risk": risk,
        "portfolio": portfolio,
    }
