"""SaaS テナント・ユーザー・APIキー"""

import logging
from datetime import datetime, timezone

from sqlalchemy import (
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    func,
    select,
)
from sqlalchemy.orm import relationship

from src.db.database import Base, SessionLocal, engine

logger = logging.getLogger(__name__)


class Tenant(Base):
    __tablename__ = "tenants"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(120), nullable=False)
    slug = Column(String(80), nullable=False, unique=True)
    plan = Column(String(20), nullable=False, default="free")
    stripe_customer_id = Column(String(100))
    stripe_subscription_id = Column(String(100))
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))

    users = relationship("User", back_populates="tenant")
    api_keys = relationship("TenantApiKey", back_populates="tenant")


class User(Base):
    __tablename__ = "users"
    __table_args__ = (UniqueConstraint("email", name="uq_users_email"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False)
    email = Column(String(255), nullable=False)
    password_hash = Column(String(255), nullable=False)
    role = Column(String(20), nullable=False, default="owner")
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))

    tenant = relationship("Tenant", back_populates="users")


class TenantApiKey(Base):
    __tablename__ = "tenant_api_keys"

    id = Column(Integer, primary_key=True, autoincrement=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False)
    name = Column(String(80), nullable=False, default="Default")
    key_prefix = Column(String(20), nullable=False)
    key_hash = Column(String(64), nullable=False)
    last_used_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))

    tenant = relationship("Tenant", back_populates="api_keys")


class UsageEvent(Base):
    __tablename__ = "usage_events"

    id = Column(Integer, primary_key=True, autoincrement=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False)
    event_type = Column(String(40), nullable=False, default="api_call")
    path = Column(String(200))
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))


def init_auth_tables():
    try:
        Tenant.__table__.create(engine, checkfirst=True)
        User.__table__.create(engine, checkfirst=True)
        TenantApiKey.__table__.create(engine, checkfirst=True)
        UsageEvent.__table__.create(engine, checkfirst=True)
        from sqlalchemy import text

        with engine.begin() as conn:
            conn.execute(
                text("ALTER TABLE tenants ADD COLUMN IF NOT EXISTS stripe_subscription_id VARCHAR(100)")
            )
    except Exception as e:
        logger.warning("auth tables init: %s", e)


def count_daily_usage(tenant_id: int) -> int:
    db = SessionLocal()
    try:
        start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        q = select(func.count()).select_from(UsageEvent).where(
            UsageEvent.tenant_id == tenant_id,
            UsageEvent.created_at >= start,
        )
        return int(db.execute(q).scalar() or 0)
    finally:
        db.close()


def record_usage(tenant_id: int, path: str, event_type: str = "api_call") -> None:
    db = SessionLocal()
    try:
        db.add(UsageEvent(tenant_id=tenant_id, event_type=event_type, path=path[:200]))
        db.commit()
    except Exception:
        db.rollback()
    finally:
        db.close()
