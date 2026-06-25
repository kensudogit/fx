"""自動取引設定・実行ログの永続化"""

import json
import logging
from datetime import datetime, timezone

from sqlalchemy import Boolean, Column, DateTime, Integer, Numeric, String, Text, desc, select

from src.db.database import Base, SessionLocal, engine

logger = logging.getLogger(__name__)

DEFAULT_CONFIG = {
    "enabled": False,
    "symbols": ["USDJPY"],
    "mode": "paper",
    "strategy_preset": "balanced",
    "min_confidence": 65,
    "risk_percent": 1.0,
    "account_balance": 10000,
    "sources": ["ai", "technical", "intelligence", "mtf"],
    "require_mtf_alignment": True,
    "event_blackout_hours": 4,
    "max_daily_trades": 3,
    "cooldown_minutes": 60,
    "auto_execute_tradingview": True,
    "auto_exit_on_reverse": True,
    "use_stop_loss": True,
    "use_take_profit": True,
    "risk_reward": 2.0,
    "max_lots": 1.0,
    "min_lots": 0.01,
    "min_units": 1000,
    "scheduler_interval_minutes": 15,
    "scheduler_enabled": True,
    "allow_add_to_position": False,
}

_memory_configs: dict[int, dict] = {}
_memory_runs: list[dict] = []


class AutoTradeConfig(Base):
    __tablename__ = "autotrade_configs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    tenant_id = Column(Integer, nullable=True, unique=True)
    config_json = Column(Text, nullable=False)
    updated_at = Column(DateTime(timezone=True), nullable=False)


class AutoTradeRun(Base):
    __tablename__ = "autotrade_runs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    tenant_id = Column(Integer, nullable=True)
    symbol = Column(String(10), nullable=False)
    action = Column(String(10), nullable=False)
    decision = Column(String(20), nullable=False)
    confidence = Column(Numeric(5, 2))
    units = Column(Integer)
    fill_price = Column(Numeric(18, 6))
    order_id = Column(Integer)
    trigger = Column(String(30), default="scheduler")
    reason = Column(Text)
    signal_snapshot = Column(Text)
    created_at = Column(DateTime(timezone=True), nullable=False)


def _ensure_tables():
    try:
        AutoTradeConfig.__table__.create(engine, checkfirst=True)
        AutoTradeRun.__table__.create(engine, checkfirst=True)
    except Exception as e:
        logger.warning("autotrade tables: %s", e)


def merge_config(raw: dict | None) -> dict:
    merged = {**DEFAULT_CONFIG, **(raw or {})}
    if not merged.get("symbols"):
        merged["symbols"] = ["USDJPY"]
    return merged


def get_config(tenant_id: int | None = None) -> dict:
    _ensure_tables()
    db = SessionLocal()
    try:
        if tenant_id is not None:
            row = db.execute(
                select(AutoTradeConfig).where(AutoTradeConfig.tenant_id == tenant_id)
            ).scalar_one_or_none()
            if row:
                return merge_config(json.loads(row.config_json))
    except Exception as e:
        logger.warning("get_config: %s", e)
    finally:
        db.close()
    if tenant_id is not None and tenant_id in _memory_configs:
        return merge_config(_memory_configs[tenant_id])
    return merge_config(None)


def save_config(config: dict, tenant_id: int | None = None) -> dict:
    _ensure_tables()
    merged = merge_config(config)
    payload = json.dumps(merged, ensure_ascii=False)
    now = datetime.now(timezone.utc)

    db = SessionLocal()
    try:
        row = None
        if tenant_id is not None:
            row = db.execute(
                select(AutoTradeConfig).where(AutoTradeConfig.tenant_id == tenant_id)
            ).scalar_one_or_none()
        if row:
            row.config_json = payload
            row.updated_at = now
        else:
            db.add(AutoTradeConfig(tenant_id=tenant_id, config_json=payload, updated_at=now))
        db.commit()
    except Exception as e:
        logger.warning("save_config: %s", e)
        db.rollback()
        if tenant_id is not None:
            _memory_configs[tenant_id] = merged
    finally:
        db.close()
    return merged


def save_run(record: dict, tenant_id: int | None = None) -> dict:
    _ensure_tables()
    now = datetime.now(timezone.utc)
    db = SessionLocal()
    try:
        row = AutoTradeRun(
            tenant_id=tenant_id,
            symbol=record["symbol"],
            action=record.get("action", "hold"),
            decision=record.get("decision", "skipped"),
            confidence=record.get("confidence"),
            units=record.get("units"),
            fill_price=record.get("fill_price"),
            order_id=record.get("order_id"),
            trigger=record.get("trigger", "manual"),
            reason=record.get("reason", ""),
            signal_snapshot=json.dumps(record.get("signal_snapshot", {}), ensure_ascii=False),
            created_at=now,
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        record["id"] = row.id
        record["created_at"] = now.isoformat()
    except Exception as e:
        logger.warning("save_run: %s", e)
        db.rollback()
        record["id"] = len(_memory_runs) + 1
        record["created_at"] = now.isoformat()
        _memory_runs.insert(0, record)
    finally:
        db.close()
    return record


def list_runs(limit: int = 30, tenant_id: int | None = None, symbol: str | None = None) -> list[dict]:
    _ensure_tables()
    db = SessionLocal()
    try:
        q = select(AutoTradeRun).order_by(desc(AutoTradeRun.created_at)).limit(limit)
        if tenant_id is not None:
            q = q.where(AutoTradeRun.tenant_id == tenant_id)
        if symbol:
            q = q.where(AutoTradeRun.symbol == symbol.upper())
        rows = db.execute(q).scalars().all()
        if rows:
            return [
                {
                    "id": r.id,
                    "symbol": r.symbol,
                    "action": r.action,
                    "decision": r.decision,
                    "confidence": float(r.confidence) if r.confidence is not None else None,
                    "units": r.units,
                    "fill_price": float(r.fill_price) if r.fill_price else None,
                    "order_id": r.order_id,
                    "trigger": r.trigger,
                    "reason": r.reason,
                    "signal_snapshot": json.loads(r.signal_snapshot) if r.signal_snapshot else {},
                    "created_at": r.created_at.isoformat() if r.created_at else None,
                }
                for r in rows
            ]
    except Exception as e:
        logger.warning("list_runs: %s", e)
    finally:
        db.close()
    items = _memory_runs
    if tenant_id is not None:
        items = [r for r in items if r.get("tenant_id") == tenant_id]
    if symbol:
        items = [r for r in items if r.get("symbol") == symbol.upper()]
    return items[:limit]


def count_today_trades(tenant_id: int | None, symbol: str | None = None) -> int:
    _ensure_tables()
    today = datetime.now(timezone.utc).date()
    db = SessionLocal()
    try:
        q = select(AutoTradeRun).where(AutoTradeRun.decision == "executed")
        if tenant_id is not None:
            q = q.where(AutoTradeRun.tenant_id == tenant_id)
        if symbol:
            q = q.where(AutoTradeRun.symbol == symbol.upper())
        rows = db.execute(q).scalars().all()
        return sum(1 for r in rows if r.created_at and r.created_at.date() == today)
    except Exception as e:
        logger.warning("count_today_trades: %s", e)
        return 0
    finally:
        db.close()


def last_executed_at(tenant_id: int | None, symbol: str) -> datetime | None:
    _ensure_tables()
    db = SessionLocal()
    try:
        q = (
            select(AutoTradeRun)
            .where(AutoTradeRun.decision == "executed", AutoTradeRun.symbol == symbol.upper())
            .order_by(desc(AutoTradeRun.created_at))
            .limit(1)
        )
        if tenant_id is not None:
            q = q.where(AutoTradeRun.tenant_id == tenant_id)
        row = db.execute(q).scalar_one_or_none()
        return row.created_at if row else None
    except Exception as e:
        logger.warning("last_executed_at: %s", e)
        return None
    finally:
        db.close()


def list_enabled_tenant_ids() -> list[int | None]:
    """enabled なテナント一覧（tenant_id=None は非SaaS）"""
    return _list_tenant_ids_by_flag("enabled")


def list_scheduler_eligible_tenant_ids() -> list[int | None]:
    """enabled かつ scheduler_enabled なテナント一覧"""
    return _list_tenant_ids_by_flag("enabled", also_require="scheduler_enabled")


def _list_tenant_ids_by_flag(flag: str, also_require: str | None = None) -> list[int | None]:
    _ensure_tables()
    ids: list[int | None] = []
    db = SessionLocal()
    try:
        rows = db.execute(select(AutoTradeConfig)).scalars().all()
        for row in rows:
            cfg = merge_config(json.loads(row.config_json))
            if not cfg.get(flag):
                continue
            if also_require and not cfg.get(also_require, True):
                continue
            ids.append(row.tenant_id)
    except Exception as e:
        logger.warning("_list_tenant_ids_by_flag: %s", e)
    finally:
        db.close()
    for tid, cfg in _memory_configs.items():
        if not cfg.get(flag):
            continue
        if also_require and not cfg.get(also_require, True):
            continue
        if tid not in ids:
            ids.append(tid)
    return ids
