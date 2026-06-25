"""認証・テナント登録サービス"""

import re
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.auth.models import Tenant, TenantApiKey, User, count_daily_usage, init_auth_tables
from src.auth.plans import daily_limit, plan_features
from src.auth.security import (
    api_key_prefix,
    create_access_token,
    generate_api_key,
    hash_api_key,
    hash_password,
    verify_password,
)
from src.db.database import SessionLocal


@dataclass
class TenantContext:
    tenant_id: int
    tenant_slug: str
    plan: str
    user_id: int | None = None
    email: str | None = None
    role: str | None = None
    auth_via: str = "jwt"


def _slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return slug[:60] or "workspace"


def register_tenant(db: Session, email: str, password: str, org_name: str) -> dict:
    init_auth_tables()
    email = email.strip().lower()
    existing = db.execute(select(User).where(User.email == email)).scalar_one_or_none()
    if existing:
        raise ValueError("このメールアドレスは既に登録されています")

    base_slug = _slugify(org_name)
    slug = base_slug
    n = 1
    while db.execute(select(Tenant).where(Tenant.slug == slug)).scalar_one_or_none():
        slug = f"{base_slug}-{n}"
        n += 1

    tenant = Tenant(name=org_name.strip(), slug=slug, plan="free")
    db.add(tenant)
    db.flush()

    user = User(
        tenant_id=tenant.id,
        email=email,
        password_hash=hash_password(password),
        role="owner",
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    db.refresh(tenant)

    token = create_access_token(user.id, tenant.id, user.email, user.role)
    return {
        "access_token": token,
        "token_type": "bearer",
        "user": _user_payload(user),
        "tenant": _tenant_payload(tenant),
    }


def login_user(db: Session, email: str, password: str) -> dict:
    init_auth_tables()
    email = email.strip().lower()
    user = db.execute(select(User).where(User.email == email)).scalar_one_or_none()
    if not user or not verify_password(password, user.password_hash):
        raise ValueError("メールアドレスまたはパスワードが正しくありません")

    tenant = db.get(Tenant, user.tenant_id)
    token = create_access_token(user.id, tenant.id, user.email, user.role)
    return {
        "access_token": token,
        "token_type": "bearer",
        "user": _user_payload(user),
        "tenant": _tenant_payload(tenant),
    }


def get_me(db: Session, user_id: int) -> dict:
    user = db.get(User, user_id)
    if not user:
        raise ValueError("User not found")
    tenant = db.get(Tenant, user.tenant_id)
    usage = count_daily_usage(tenant.id)
    limit = daily_limit(tenant.plan)
    return {
        "user": _user_payload(user),
        "tenant": _tenant_payload(tenant),
        "usage": {
            "daily_calls": usage,
            "daily_limit": limit,
            "remaining": max(0, limit - usage),
        },
        "features": plan_features(tenant.plan),
    }


def resolve_api_key(db: Session, raw_key: str) -> TenantContext | None:
    if not raw_key.startswith("fx_"):
        return None
    key_hash = hash_api_key(raw_key)
    row = db.execute(
        select(TenantApiKey, Tenant)
        .join(Tenant, Tenant.id == TenantApiKey.tenant_id)
        .where(TenantApiKey.key_hash == key_hash)
    ).first()
    if not row:
        return None
    api_key_row, tenant = row
    api_key_row.last_used_at = datetime.now(timezone.utc)
    db.commit()
    return TenantContext(
        tenant_id=tenant.id,
        tenant_slug=tenant.slug,
        plan=tenant.plan,
        auth_via="api_key",
    )


def create_api_key(db: Session, tenant_id: int, name: str) -> dict:
    tenant = db.get(Tenant, tenant_id)
    if not tenant:
        raise ValueError("Tenant not found")
    max_keys = plan_features(tenant.plan).get("api_keys", 1)
    count = len(db.execute(select(TenantApiKey).where(TenantApiKey.tenant_id == tenant_id)).scalars().all())
    if count >= max_keys:
        raise ValueError(f"APIキー上限 ({max_keys}) に達しています。プランをアップグレードしてください。")

    raw = generate_api_key()
    row = TenantApiKey(
        tenant_id=tenant_id,
        name=name.strip() or "API Key",
        key_prefix=api_key_prefix(raw),
        key_hash=hash_api_key(raw),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return {
        "id": row.id,
        "name": row.name,
        "key_prefix": row.key_prefix,
        "api_key": raw,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


def list_api_keys(db: Session, tenant_id: int) -> list[dict]:
    rows = db.execute(select(TenantApiKey).where(TenantApiKey.tenant_id == tenant_id)).scalars().all()
    return [
        {
            "id": r.id,
            "name": r.name,
            "key_prefix": r.key_prefix,
            "last_used_at": r.last_used_at.isoformat() if r.last_used_at else None,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in rows
    ]


def upgrade_plan(db: Session, tenant_id: int, plan: str) -> dict:
    if plan not in ("free", "pro", "enterprise"):
        raise ValueError("Invalid plan")
    tenant = db.get(Tenant, tenant_id)
    if not tenant:
        raise ValueError("Tenant not found")
    tenant.plan = plan
    db.commit()
    db.refresh(tenant)
    return _tenant_payload(tenant)


def _user_payload(user: User) -> dict:
    return {"id": user.id, "email": user.email, "role": user.role, "tenant_id": user.tenant_id}


def _tenant_payload(tenant: Tenant) -> dict:
    return {
        "id": tenant.id,
        "name": tenant.name,
        "slug": tenant.slug,
        "plan": tenant.plan,
    }


def bootstrap_auth():
    init_auth_tables()
