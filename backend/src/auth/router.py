"""認証・課金 API"""

import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy.orm import Session

from src.db.database import get_db
from src.auth.plans import list_plans_public
from src.auth.service import (
    bootstrap_auth,
    create_api_key,
    get_me,
    list_api_keys,
    login_user,
    register_tenant,
    upgrade_plan,
)
from src.config import settings

logger = logging.getLogger(__name__)

router = APIRouter(tags=["SaaS"])


class RegisterBody(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    org_name: str = Field(min_length=2, max_length=120)


class LoginBody(BaseModel):
    email: EmailStr
    password: str


class ApiKeyBody(BaseModel):
    name: str = Field(default="API Key", max_length=80)


class PlanUpgradeBody(BaseModel):
    plan: str = Field(pattern="^(free|pro|enterprise)$")


def _current_user_id(request: Request) -> int:
    tenant = getattr(request.state, "tenant", None)
    if not tenant or not tenant.user_id:
        raise HTTPException(status_code=401, detail="JWT ログインが必要です")
    return tenant.user_id


def _current_tenant_id(request: Request) -> int:
    tenant = getattr(request.state, "tenant", None)
    if not tenant:
        raise HTTPException(status_code=401, detail="認証が必要です")
    return tenant.tenant_id


@router.post("/api/auth/register")
def auth_register(body: RegisterBody, db: Session = Depends(get_db)):
    if not settings.saas_enabled:
        raise HTTPException(status_code=503, detail="SaaS モードが無効です")
    try:
        return register_tenant(db, body.email, body.password, body.org_name)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/api/auth/login")
def auth_login(body: LoginBody, db: Session = Depends(get_db)):
    if not settings.saas_enabled:
        raise HTTPException(status_code=503, detail="SaaS モードが無効です")
    try:
        return login_user(db, body.email, body.password)
    except ValueError as e:
        raise HTTPException(status_code=401, detail=str(e))


@router.get("/api/auth/me")
def auth_me(request: Request, db: Session = Depends(get_db)):
    user_id = _current_user_id(request)
    try:
        return get_me(db, user_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/api/auth/api-keys")
def auth_list_keys(request: Request, db: Session = Depends(get_db)):
    tenant_id = _current_tenant_id(request)
    return {"keys": list_api_keys(db, tenant_id)}


@router.post("/api/auth/api-keys")
def auth_create_key(body: ApiKeyBody, request: Request, db: Session = Depends(get_db)):
    tenant_id = _current_tenant_id(request)
    try:
        return create_api_key(db, tenant_id, body.name)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/api/billing/plans")
def billing_plans():
    return {"plans": list_plans_public(), "saas_enabled": settings.saas_enabled}


@router.post("/api/billing/upgrade")
def billing_upgrade(body: PlanUpgradeBody, request: Request, db: Session = Depends(get_db)):
    """デモ用プラン変更（本番では Stripe Webhook に置き換え）"""
    tenant_id = _current_tenant_id(request)
    tenant = getattr(request.state, "tenant", None)
    if tenant and tenant.role != "owner" and tenant.auth_via == "jwt":
        raise HTTPException(status_code=403, detail="オーナーのみプラン変更できます")
    try:
        updated = upgrade_plan(db, tenant_id, body.plan)
        return {"tenant": updated, "message": "プランを更新しました（デモ）"}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/api/billing/webhook")
async def billing_stripe_webhook(request: Request, db: Session = Depends(get_db)):
    """Stripe Webhook フック（署名検証は本番で実装）"""
    if not settings.stripe_webhook_secret:
        return {"received": True, "note": "STRIPE_WEBHOOK_SECRET 未設定 — ノーオペ"}
    payload = await request.body()
    logger.info("Stripe webhook received (%d bytes)", len(payload))
    return {"received": True}
