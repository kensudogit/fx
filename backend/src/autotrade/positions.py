"""ポジション管理 — SL/TP 監視・逆シグナル決済"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import Column, DateTime, Integer, Numeric, String, desc, select

from src.autotrade.pnl import calc_realized_pnl_usd
from src.broker.oanda import close_position as oanda_close, get_open_positions, place_market_order
from src.db.database import Base, SessionLocal, engine

logger = logging.getLogger(__name__)

_memory_positions: list[dict] = []


class AutoTradePosition(Base):
    __tablename__ = "autotrade_positions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    tenant_id = Column(Integer, nullable=True)
    symbol = Column(String(10), nullable=False)
    side = Column(String(10), nullable=False)
    units = Column(Integer, nullable=False)
    entry_price = Column(Numeric(18, 6), nullable=False)
    stop_loss = Column(Numeric(18, 6))
    take_profit = Column(Numeric(18, 6))
    status = Column(String(20), default="OPEN")
    order_id = Column(Integer)
    opened_at = Column(DateTime(timezone=True), nullable=False)
    closed_at = Column(DateTime(timezone=True))
    close_price = Column(Numeric(18, 6))
    close_reason = Column(String(50))


def _ensure_table():
    try:
        AutoTradePosition.__table__.create(engine, checkfirst=True)
    except Exception as e:
        logger.warning("autotrade_positions table: %s", e)


def open_position(
    tenant_id: int | None,
    symbol: str,
    side: str,
    units: int,
    entry_price: float,
    stop_loss: float | None,
    take_profit: float | None,
    order_id: int | None = None,
) -> dict:
    _ensure_table()
    now = datetime.now(timezone.utc)
    record = {
        "symbol": symbol.upper(),
        "side": side,
        "units": units,
        "entry_price": entry_price,
        "stop_loss": stop_loss,
        "take_profit": take_profit,
        "status": "OPEN",
        "order_id": order_id,
        "opened_at": now.isoformat(),
    }
    db = SessionLocal()
    try:
        row = AutoTradePosition(
            tenant_id=tenant_id,
            symbol=symbol.upper(),
            side=side,
            units=units,
            entry_price=entry_price,
            stop_loss=stop_loss,
            take_profit=take_profit,
            status="OPEN",
            order_id=order_id,
            opened_at=now,
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        record["id"] = row.id
    except Exception as e:
        logger.warning("open_position: %s", e)
        db.rollback()
        record["id"] = len(_memory_positions) + 1
        _memory_positions.append(record)
    finally:
        db.close()
    return record


def list_open_positions(tenant_id: int | None = None, symbol: str | None = None) -> list[dict]:
    _ensure_table()
    db = SessionLocal()
    try:
        q = select(AutoTradePosition).where(AutoTradePosition.status == "OPEN").order_by(desc(AutoTradePosition.opened_at))
        if tenant_id is not None:
            q = q.where(AutoTradePosition.tenant_id == tenant_id)
        if symbol:
            q = q.where(AutoTradePosition.symbol == symbol.upper())
        rows = db.execute(q).scalars().all()
        if rows:
            return [_pos_dict(r) for r in rows]
    except Exception as e:
        logger.warning("list_open_positions: %s", e)
    finally:
        db.close()
    items = [p for p in _memory_positions if p.get("status") == "OPEN"]
    if tenant_id is not None:
        items = [p for p in items if p.get("tenant_id") == tenant_id]
    if symbol:
        items = [p for p in items if p.get("symbol") == symbol.upper()]
    return items


def _pos_dict(r: AutoTradePosition, include_close: bool = False) -> dict:
    d = {
        "id": r.id,
        "symbol": r.symbol,
        "side": r.side,
        "units": r.units,
        "entry_price": float(r.entry_price),
        "stop_loss": float(r.stop_loss) if r.stop_loss else None,
        "take_profit": float(r.take_profit) if r.take_profit else None,
        "status": r.status,
        "order_id": r.order_id,
        "opened_at": r.opened_at.isoformat() if r.opened_at else None,
    }
    if include_close or r.status == "CLOSED":
        d["closed_at"] = r.closed_at.isoformat() if r.closed_at else None
        d["close_price"] = float(r.close_price) if r.close_price else None
        d["close_reason"] = r.close_reason
        if d.get("close_price"):
            d["realized_pnl_usd"] = calc_realized_pnl_usd(
                r.symbol, r.side, r.units, float(r.entry_price), float(r.close_price)
            )
    return d


def list_closed_positions(
    tenant_id: int | None = None,
    days: int = 90,
    limit: int = 200,
) -> list[dict]:
    _ensure_table()
    since = datetime.now(timezone.utc) - timedelta(days=days)
    db = SessionLocal()
    try:
        q = (
            select(AutoTradePosition)
            .where(AutoTradePosition.status == "CLOSED")
            .where(AutoTradePosition.closed_at >= since)
            .order_by(desc(AutoTradePosition.closed_at))
            .limit(limit)
        )
        if tenant_id is not None:
            q = q.where(AutoTradePosition.tenant_id == tenant_id)
        rows = db.execute(q).scalars().all()
        return [_pos_dict(r, include_close=True) for r in rows]
    except Exception as e:
        logger.warning("list_closed_positions: %s", e)
        return []
    finally:
        db.close()


def close_position_record(
    position_id: int,
    close_price: float,
    reason: str,
    tenant_id: int | None = None,
) -> dict | None:
    _ensure_table()
    db = SessionLocal()
    try:
        row = db.get(AutoTradePosition, position_id)
        if not row or row.status != "OPEN":
            return None
        if tenant_id is not None and row.tenant_id != tenant_id:
            return None
        row.status = "CLOSED"
        row.closed_at = datetime.now(timezone.utc)
        row.close_price = close_price
        row.close_reason = reason
        db.commit()
        return _pos_dict(row, include_close=True)
    except Exception as e:
        logger.warning("close_position_record: %s", e)
        db.rollback()
        return None
    finally:
        db.close()


def check_exits(
    symbol: str,
    current_price: float,
    tenant_id: int | None,
    reverse_action: str | None = None,
    auto_exit_on_reverse: bool = True,
    trading_mode: str = "paper",
) -> list[dict]:
    """SL/TP 到達または逆シグナルで決済"""
    positions = list_open_positions(tenant_id, symbol)
    if not positions:
        return []

    closed = []
    for pos in positions:
        reason = None
        side = pos["side"]

        if pos.get("stop_loss"):
            if side == "buy" and current_price <= pos["stop_loss"]:
                reason = "stop_loss"
            elif side == "sell" and current_price >= pos["stop_loss"]:
                reason = "stop_loss"

        if not reason and pos.get("take_profit"):
            if side == "buy" and current_price >= pos["take_profit"]:
                reason = "take_profit"
            elif side == "sell" and current_price <= pos["take_profit"]:
                reason = "take_profit"

        if not reason and auto_exit_on_reverse and reverse_action in ("buy", "sell"):
            if (side == "buy" and reverse_action == "sell") or (side == "sell" and reverse_action == "buy"):
                reason = "reverse_signal"

        if not reason:
            continue

        exit_side = "sell" if side == "buy" else "buy"
        try:
            oanda_close(symbol, side, pos["units"], tenant_id, trading_mode=trading_mode)
        except Exception:
            place_market_order(symbol, exit_side, pos["units"], tenant_id, trading_mode=trading_mode)

        rec = close_position_record(pos["id"], current_price, reason, tenant_id)
        if rec:
            rec["close_reason"] = reason
            closed.append(rec)
    return closed


def has_open_position(tenant_id: int | None, symbol: str) -> bool:
    return len(list_open_positions(tenant_id, symbol)) > 0
