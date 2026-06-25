"""OANDA v20 REST API（注文・口座・リアルタイム価格）"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

import httpx
from sqlalchemy import Column, DateTime, Integer, Numeric, String, desc, select

from src.broker.tenant_oanda import OandaCredentials, resolve_oanda_credentials
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
OANDA_TO_SYMBOL = {v: k for k, v in SYMBOL_TO_OANDA.items()}


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


def is_oanda_configured(tenant_id: int | None = None, trading_mode: str = "live") -> bool:
    creds = resolve_oanda_credentials(tenant_id, trading_mode)
    return creds.configured


def _base_url(creds: OandaCredentials) -> str:
    if creds.mode == "live":
        return "https://api-fxtrade.oanda.com/v3"
    return "https://api-fxpractice.oanda.com/v3"


def _headers(creds: OandaCredentials) -> dict:
    return {
        "Authorization": f"Bearer {creds.api_token}",
        "Content-Type": "application/json",
    }


def get_account_summary(tenant_id: int | None = None, trading_mode: str = "live") -> dict:
    creds = resolve_oanda_credentials(tenant_id, trading_mode)
    if not creds.configured:
        return {
            "configured": False,
            "mode": "paper",
            "balance": 10000,
            "currency": "USD",
            "source": creds.source,
            "message": "OANDA 未設定 — ペーパー取引モード（/settings で口座設定）",
        }

    url = f"{_base_url(creds)}/accounts/{creds.account_id}/summary"
    with httpx.Client(timeout=20.0) as client:
        res = client.get(url, headers=_headers(creds))
        res.raise_for_status()
        acct = res.json().get("account", {})
    return {
        "configured": True,
        "mode": creds.mode,
        "source": creds.source,
        "balance": float(acct.get("balance", 0)),
        "currency": acct.get("currency", "USD"),
        "unrealized_pl": float(acct.get("unrealizedPL", 0)),
        "open_trade_count": int(acct.get("openTradeCount", 0)),
    }


def fetch_live_prices(symbols: list[str], tenant_id: int | None = None, trading_mode: str = "live") -> dict[str, dict]:
    """リアルタイム価格取得 — OANDA pricing → DB/Yahoo フォールバック"""
    creds = resolve_oanda_credentials(tenant_id, trading_mode)
    normalized = [s.upper() for s in symbols if s.upper() in SYMBOL_TO_OANDA]
    result: dict[str, dict] = {}

    if creds.configured and normalized:
        instruments = ",".join(SYMBOL_TO_OANDA[s] for s in normalized)
        url = f"{_base_url(creds)}/accounts/{creds.account_id}/pricing"
        try:
            with httpx.Client(timeout=10.0) as client:
                res = client.get(url, headers=_headers(creds), params={"instruments": instruments})
                res.raise_for_status()
                for item in res.json().get("prices", []):
                    sym = OANDA_TO_SYMBOL.get(item.get("instrument", ""))
                    if not sym:
                        continue
                    bids = item.get("bids") or []
                    asks = item.get("asks") or []
                    bid = float(bids[0]["price"]) if bids else None
                    ask = float(asks[0]["price"]) if asks else None
                    mid = round((bid + ask) / 2, 5 if not sym.endswith("JPY") else 3) if bid and ask else None
                    result[sym] = {
                        "symbol": sym,
                        "bid": bid,
                        "ask": ask,
                        "price": mid,
                        "source": "oanda",
                        "time": item.get("time"),
                    }
        except Exception as e:
            logger.warning("OANDA pricing failed: %s", e)

    missing = [s for s in normalized if s not in result]
    if missing:
        from src.data.market_data import get_ohlcv_data

        for sym in missing:
            try:
                df, source = get_ohlcv_data(sym, 5)
                price = float(df["close"].iloc[-1])
                result[sym] = {
                    "symbol": sym,
                    "bid": price,
                    "ask": price,
                    "price": price,
                    "source": source,
                    "time": datetime.now(timezone.utc).isoformat(),
                }
            except Exception as e:
                logger.warning("price fallback %s: %s", sym, e)

    return result


def place_market_order(
    symbol: str,
    side: str,
    units: int,
    tenant_id: int | None = None,
    stop_loss: float | None = None,
    take_profit: float | None = None,
    trading_mode: str | None = None,
) -> dict:
    symbol = symbol.upper()
    side = side.lower()
    if side not in ("buy", "sell"):
        raise ValueError("side must be buy or sell")
    signed_units = abs(units) if side == "buy" else -abs(units)

    mode = trading_mode or "paper"
    creds = resolve_oanda_credentials(tenant_id, mode)
    if not creds.configured:
        return _save_paper_order(symbol, side, abs(units), tenant_id, stop_loss, take_profit)

    instrument = SYMBOL_TO_OANDA.get(symbol)
    if not instrument:
        raise ValueError(f"Unsupported symbol for OANDA: {symbol}")

    order_body: dict[str, Any] = {
        "instrument": instrument,
        "units": str(signed_units),
        "type": "MARKET",
        "timeInForce": "FOK",
        "positionFill": "DEFAULT",
    }
    if stop_loss is not None:
        order_body["stopLossOnFill"] = {"price": str(round(stop_loss, 5))}
    if take_profit is not None:
        order_body["takeProfitOnFill"] = {"price": str(round(take_profit, 5))}

    payload = {"order": order_body}
    url = f"{_base_url(creds)}/accounts/{creds.account_id}/orders"
    with httpx.Client(timeout=20.0) as client:
        res = client.post(url, headers=_headers(creds), json=payload)
        res.raise_for_status()
        body = res.json()

    fill = body.get("orderFillTransaction") or body.get("orderCreateTransaction") or {}
    record = _save_order(
        symbol=symbol,
        side=side,
        units=abs(units),
        status="FILLED" if fill.get("type") == "ORDER_FILL" else "SUBMITTED",
        fill_price=float(fill.get("price", 0)) if fill.get("price") else None,
        broker="oanda",
        external_id=str(fill.get("id", "")),
        tenant_id=tenant_id,
    )
    if stop_loss is not None:
        record["stop_loss"] = stop_loss
    if take_profit is not None:
        record["take_profit"] = take_profit
    record["broker_mode"] = creds.mode
    return record


def close_position(
    symbol: str,
    side: str,
    units: int,
    tenant_id: int | None = None,
    trading_mode: str | None = None,
) -> dict:
    exit_side = "sell" if side == "buy" else "buy"
    return place_market_order(symbol, exit_side, units, tenant_id, trading_mode=trading_mode)


def get_open_positions(tenant_id: int | None = None, trading_mode: str | None = None) -> list[dict]:
    mode = trading_mode or "live"
    creds = resolve_oanda_credentials(tenant_id, mode)
    if not creds.configured:
        from src.autotrade.positions import list_open_positions

        return list_open_positions(tenant_id)

    url = f"{_base_url(creds)}/accounts/{creds.account_id}/openPositions"
    with httpx.Client(timeout=20.0) as client:
        res = client.get(url, headers=_headers(creds))
        res.raise_for_status()
        positions = res.json().get("positions", [])

    result = []
    for p in positions:
        inst = p.get("instrument", "")
        sym = inst.replace("_", "")
        long_u = int(p.get("long", {}).get("units", 0))
        short_u = int(p.get("short", {}).get("units", 0))
        if long_u > 0:
            result.append({"symbol": sym, "side": "buy", "units": long_u})
        if short_u < 0:
            result.append({"symbol": sym, "side": "sell", "units": abs(short_u)})
    return result


def _save_paper_order(
    symbol: str,
    side: str,
    units: int,
    tenant_id: int | None = None,
    stop_loss: float | None = None,
    take_profit: float | None = None,
) -> dict:
    live = fetch_live_prices([symbol], tenant_id, trading_mode="live")
    quote = live.get(symbol.upper())
    if quote and quote.get("price"):
        price = float(quote["price"])
    else:
        from src.data.market_data import get_ohlcv_data

        df, _ = get_ohlcv_data(symbol, 30)
        price = float(df["close"].iloc[-1])

    record = _save_order(
        symbol, side, units, "FILLED", price, "paper", f"paper-{datetime.now().timestamp():.0f}", tenant_id
    )
    if stop_loss is not None:
        record["stop_loss"] = stop_loss
    if take_profit is not None:
        record["take_profit"] = take_profit
    return record


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
