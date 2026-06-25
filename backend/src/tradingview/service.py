"""TradingView Webhook シグナル受信・保存"""

import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import Column, DateTime, Integer, Numeric, String, desc, select
from sqlalchemy.orm import Session

from src.db.database import Base, SessionLocal, engine

logger = logging.getLogger(__name__)

# メモリフォールバック（DB 未作成時）
_memory_signals: list[dict] = []
_MAX_MEMORY = 100


class TradingViewSignal(Base):
    __tablename__ = "tradingview_signals"

    id = Column(Integer, primary_key=True, autoincrement=True)
    tenant_id = Column(Integer, nullable=True)
    symbol = Column(String(10), nullable=False)
    action = Column(String(10), nullable=False)
    price = Column(Numeric(18, 6))
    strategy = Column(String(100))
    message = Column(String(500))
    source = Column(String(30), default="tradingview")
    received_at = Column(DateTime(timezone=True), nullable=False)


def _ensure_table():
    try:
        TradingViewSignal.__table__.create(engine, checkfirst=True)
    except Exception as e:
        logger.warning("tradingview_signals table: %s", e)


def save_signal(payload: dict[str, Any], tenant_id: int | None = None) -> dict:
    _ensure_table()
    symbol = str(payload.get("symbol", payload.get("ticker", "UNKNOWN"))).upper()
    symbol = symbol.replace("OANDA:", "").replace("FX:", "").split(":")[-1][:10]
    action = str(payload.get("action", payload.get("side", "alert"))).lower()
    price = payload.get("price") or payload.get("close")
    strategy = str(payload.get("strategy", payload.get("strategy_name", "TradingView")))[:100]
    message = str(payload.get("message", payload.get("comment", "")))[:500]

    record = {
        "symbol": symbol,
        "action": action,
        "price": float(price) if price is not None else None,
        "strategy": strategy,
        "message": message,
        "source": "tradingview",
        "tenant_id": tenant_id,
        "received_at": datetime.now(timezone.utc).isoformat(),
    }

    db: Session = SessionLocal()
    try:
        row = TradingViewSignal(
            tenant_id=tenant_id,
            symbol=record["symbol"],
            action=record["action"],
            price=record["price"],
            strategy=record["strategy"],
            message=record["message"],
            received_at=datetime.now(timezone.utc),
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        record["id"] = row.id
    except Exception as e:
        logger.warning("DB save failed, using memory: %s", e)
        db.rollback()
        _memory_signals.insert(0, record)
        del _memory_signals[_MAX_MEMORY:]
        record["id"] = len(_memory_signals)
    finally:
        db.close()

    return record


def list_signals(symbol: str | None = None, limit: int = 20, tenant_id: int | None = None) -> list[dict]:
    _ensure_table()
    db: Session = SessionLocal()
    try:
        q = select(TradingViewSignal).order_by(desc(TradingViewSignal.received_at)).limit(limit)
        if symbol:
            q = q.where(TradingViewSignal.symbol == symbol.upper())
        if tenant_id is not None:
            q = q.where(TradingViewSignal.tenant_id == tenant_id)
        rows = db.execute(q).scalars().all()
        if rows:
            return [
                {
                    "id": r.id,
                    "symbol": r.symbol,
                    "action": r.action,
                    "price": float(r.price) if r.price is not None else None,
                    "strategy": r.strategy,
                    "message": r.message,
                    "source": r.source,
                    "received_at": r.received_at.isoformat() if r.received_at else None,
                }
                for r in rows
            ]
    except Exception as e:
        logger.warning("list_signals DB: %s", e)
    finally:
        db.close()

    items = _memory_signals
    if symbol:
        items = [s for s in items if s["symbol"] == symbol.upper()]
    return items[:limit]
