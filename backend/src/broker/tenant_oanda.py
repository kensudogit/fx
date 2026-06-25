"""テナント別 OANDA 口座設定"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, select

from src.config import settings
from src.db.database import Base, SessionLocal, engine

logger = logging.getLogger(__name__)


class TenantOandaSettings(Base):
    __tablename__ = "tenant_oanda_settings"

    tenant_id = Column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"), primary_key=True)
    api_token = Column(String(500))
    account_id = Column(String(50))
    environment = Column(String(20), default="practice")
    updated_at = Column(DateTime(timezone=True), nullable=False)


@dataclass
class OandaCredentials:
    configured: bool
    mode: str
    api_token: str | None
    account_id: str | None
    source: str


def _ensure_table():
    try:
        TenantOandaSettings.__table__.create(engine, checkfirst=True)
    except Exception as e:
        logger.warning("tenant_oanda_settings table: %s", e)


def _mask_token(token: str | None) -> str | None:
    if not token:
        return None
    if len(token) <= 8:
        return "****"
    return f"{token[:4]}...{token[-4:]}"


def get_tenant_oanda_settings(tenant_id: int) -> dict | None:
    _ensure_table()
    db = SessionLocal()
    try:
        row = db.get(TenantOandaSettings, tenant_id)
        if not row:
            return None
        return {
            "tenant_id": tenant_id,
            "account_id": row.account_id,
            "environment": row.environment or "practice",
            "api_token_set": bool(row.api_token),
            "api_token_masked": _mask_token(row.api_token),
            "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        }
    finally:
        db.close()


def save_tenant_oanda_settings(
    tenant_id: int,
    *,
    api_token: str | None = None,
    account_id: str | None = None,
    environment: str | None = None,
    clear_token: bool = False,
) -> dict:
    _ensure_table()
    now = datetime.now(timezone.utc)
    env = (environment or "practice").lower()
    if env not in ("practice", "live"):
        raise ValueError("environment must be practice or live")

    db = SessionLocal()
    try:
        row = db.get(TenantOandaSettings, tenant_id)
        if not row:
            row = TenantOandaSettings(tenant_id=tenant_id, updated_at=now)
            db.add(row)

        if account_id is not None:
            row.account_id = account_id.strip() or None
        if environment is not None:
            row.environment = env
        if clear_token:
            row.api_token = None
        elif api_token is not None and api_token.strip():
            row.api_token = api_token.strip()

        row.updated_at = now
        db.commit()
        return get_tenant_oanda_settings(tenant_id) or {}
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def resolve_oanda_credentials(tenant_id: int | None, trading_mode: str = "paper") -> OandaCredentials:
    """trading_mode=paper なら常にペーパー。live/practice はテナント設定 → グローバル env の順。"""
    mode = (trading_mode or "paper").lower()
    if mode == "paper":
        return OandaCredentials(
            configured=False,
            mode="paper",
            api_token=None,
            account_id=None,
            source="paper",
        )

    _ensure_table()
    if tenant_id is not None:
        db = SessionLocal()
        try:
            row = db.get(TenantOandaSettings, tenant_id)
            if row and row.api_token and row.account_id:
                env = row.environment or "practice"
                if mode == "live" and env != "live":
                    env = "practice"
                return OandaCredentials(
                    configured=True,
                    mode=env,
                    api_token=row.api_token,
                    account_id=row.account_id,
                    source="tenant",
                )
        finally:
            db.close()

    if settings.oanda_api_token and settings.oanda_account_id:
        env = settings.oanda_environment
        if mode == "live" and env != "live":
            env = "practice"
        return OandaCredentials(
            configured=True,
            mode=env,
            api_token=settings.oanda_api_token,
            account_id=settings.oanda_account_id,
            source="global",
        )

    return OandaCredentials(
        configured=False,
        mode="paper",
        api_token=None,
        account_id=None,
        source="paper",
    )
