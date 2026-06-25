"""OANDA v20 REST API（注文・口座）"""

import logging
from datetime import datetime, timezone
from typing import Any

import httpx
from sqlalchemy import Column, DateTime, Integer, Numeric, String, desc, select

from src.config import settings
from src.db.database import Base, SessionLocal, engine

logger = logging.getLogger(__name__)

_memory_orders: list[dict] = []

SYMBOL_TO_OANDA = {
    "USDJPY": "USD_JPY",
    "EURUSD": "EUR_USD",
    "GBPUSD": "GBP_USD",
    "AUDUSD": "AUD_USD",
}


class BrokerOrder(Base):
    __tablename__ = "broker_orders"

    id = Column(Integer, primary_key=True, autoincrement=True)
    tenant_id = Column(Integer, nullable=True)
    symbol = Column(String(10), nullable=False)
    side = Column(String(10), nullable=False)
    units = Column(Integer, nullable=False)
    order_type = Column(String(20), default="MARKET")
    status = Column(String(20), default="PENDING")
    fill_price = Column(Numeric(18, 6))
    broker = Column(String(20), default="paper")
    external_id = Column(String(100))
    created_at = Column(DateTime(timezone=True), nullable=False)


def _ensure_table():
    try:
        BrokerOrder.__table__.create(engine, checkfirst=True)
    except Exception as e:
        logger.warning("broker_orders table: %s", e)


def is_oanda_configured() -> bool:
    return bool(settings.oanda_api_token and settings.oanda_account_id)


def _base_url() -> str:
    if settings.oanda_environment == "live":
        return "https://api-fxtrade.oanda.com/v3"
    return "https://api-fxpractice.oanda.com/v3"


def _headers() -> dict:
    return {
        "Authorization": f"Bearer {settings.oanda_api_token}",
        "Content-Type": "application/json",
    }


def get_account_summary() -> dict:
    if not is_oanda_configured():
        return {
            "configured": False,
            "mode": "paper",
            "balance": 10000,
            "currency": "USD",
            "message": "OANDA_API_TOKEN / OANDA_ACCOUNT_ID 未設定 — ペーパー取引モード",
        }

    url = f"{_base_url()}/accounts/{settings.oanda_account_id}/summary"
    with httpx.Client(timeout=20.0) as client:
        res = client.get(url, headers=_headers())
        res.raise_for_status()
        acct = res.json().get("account", {})
    return {
        "configured": True,
        "mode": settings.oanda_environment,
        "balance": float(acct.get("balance", 0)),
        "currency": acct.get("currency", "USD"),
        "unrealized_pl": float(acct.get("unrealizedPL", 0)),
        "open_trade_count": int(acct.get("openTradeCount", 0)),
    }


def place_market_order(symbol: str, side: str, units: int, tenant_id: int | None = None) -> dict:
    symbol = symbol.upper()
    side = side.lower()
    if side not in ("buy", "sell"):
        raise ValueError("side must be buy or sell")
    signed_units = abs(units) if side == "buy" else -abs(units)

    if not is_oanda_configured():
        return _save_paper_order(symbol, side, abs(units), tenant_id)

    instrument = SYMBOL_TO_OANDA.get(symbol)
    if not instrument:
        raise ValueError(f"Unsupported symbol for OANDA: {symbol}")

    payload = {
        "order": {
            "instrument": instrument,
            "units": str(signed_units),
            "type": "MARKET",
            "timeInForce": "FOK",
            "positionFill": "DEFAULT",
        }
    }
    url = f"{_base_url()}/accounts/{settings.oanda_account_id}/orders"
    with httpx.Client(timeout=20.0) as client:
        res = client.post(url, headers=_headers(), json=payload)
        res.raise_for_status()
        body = res.json()

    fill = body.get("orderFillTransaction") or body.get("orderCreateTransaction") or {}
    return _save_order(
        symbol=symbol,
        side=side,
        units=abs(units),
        status="FILLED" if fill.get("type") == "ORDER_FILL" else "SUBMITTED",
        fill_price=float(fill.get("price", 0)) if fill.get("price") else None,
        broker="oanda",
        external_id=str(fill.get("id", "")),
        tenant_id=tenant_id,
    )


def _save_paper_order(symbol: str, side: str, units: int, tenant_id: int | None = None) -> dict:
    from src.data.market_data import get_ohlcv_data

    df, _ = get_ohlcv_data(symbol, 30)
    price = float(df["close"].iloc[-1])
    return _save_order(symbol, side, units, "FILLED", price, "paper", f"paper-{datetime.now().timestamp():.0f}", tenant_id)


def _save_order(
    symbol: str,
    side: str,
    units: int,
    status: str,
    fill_price: float | None,
    broker: str,
    external_id: str,
    tenant_id: int | None = None,
) -> dict:
    _ensure_table()
    record = {
        "symbol": symbol,
        "side": side,
        "units": units,
        "order_type": "MARKET",
        "status": status,
        "fill_price": fill_price,
        "broker": broker,
        "external_id": external_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    db = SessionLocal()
    try:
        row = BrokerOrder(
            symbol=symbol,
            side=side,
            units=units,
            status=status,
            fill_price=fill_price,
            broker=broker,
            external_id=external_id,
            tenant_id=tenant_id,
            created_at=datetime.now(timezone.utc),
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        record["id"] = row.id
    except Exception as e:
        logger.warning("order save: %s", e)
        db.rollback()
        _memory_orders.insert(0, record)
        record["id"] = len(_memory_orders)
    finally:
        db.close()
    return record


def list_orders(limit: int = 20, tenant_id: int | None = None) -> list[dict]:
    _ensure_table()
    db = SessionLocal()
    try:
        q = select(BrokerOrder).order_by(desc(BrokerOrder.created_at)).limit(limit)
        if tenant_id is not None:
            q = q.where(BrokerOrder.tenant_id == tenant_id)
        rows = db.execute(q).scalars().all()
        if rows:
            return [
                {
                    "id": r.id,
                    "symbol": r.symbol,
                    "side": r.side,
                    "units": r.units,
                    "status": r.status,
                    "fill_price": float(r.fill_price) if r.fill_price else None,
                    "broker": r.broker,
                    "external_id": r.external_id,
                    "created_at": r.created_at.isoformat() if r.created_at else None,
                }
                for r in rows
            ]
    except Exception as e:
        logger.warning("list_orders: %s", e)
    finally:
        db.close()
    return _memory_orders[:limit]
