"""認証・課金 API"""

import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy.orm import Session

from src.auth.models import Tenant
from src.auth.plans import list_plans_public
from src.auth.service import (
    create_api_key,
    get_me,
    list_api_keys,
    login_user,
    register_tenant,
    upgrade_plan,
)
from src.billing.stripe_service import create_checkout_session, handle_stripe_webhook, stripe_configured
from src.config import settings
from src.db.database import get_db

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


class CheckoutBody(BaseModel):
    plan: str = Field(pattern="^(pro|enterprise)$")
    success_url: str | None = None
    cancel_url: str | None = None


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


def _require_owner(request: Request) -> None:
    tenant = getattr(request.state, "tenant", None)
    if tenant and tenant.role != "owner" and tenant.auth_via == "jwt":
        raise HTTPException(status_code=403, detail="オーナーのみ操作できます")


@router.post("/api/auth/register")
def auth_register(body: RegisterBody, db: Session = Depends(get_db)):
    if not settings.saas_enabled:
        raise HTTPException(status_code=503, detail="SaaS モードが無効です")
    try:
        return register_tenant(db, body.email, body.password, body.org_name)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.exception("Registration failed: %s", e)
        db.rollback()
        detail = "登録に失敗しました。データベースの初期化を確認してください。"
        err = str(e).lower()
        if "does not exist" in err or "undefinedtable" in err or "relation" in err:
            detail = "認証テーブルが未作成です。アプリを再起動してから再試行してください。"
        elif "no module named" in err:
            detail = "サーバー依存関係が不足しています。再デプロイが必要です。"
        raise HTTPException(status_code=500, detail=detail)


@router.post("/api/auth/login")
def auth_login(body: LoginBody, db: Session = Depends(get_db)):
    if not settings.saas_enabled:
        raise HTTPException(status_code=503, detail="SaaS モードが無効です")
    try:
        return login_user(db, body.email, body.password)
    except ValueError as e:
        raise HTTPException(status_code=401, detail=str(e))
    except Exception as e:
        logger.exception("Login failed: %s", e)
        db.rollback()
        raise HTTPException(status_code=500, detail="ログイン処理に失敗しました")


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
    return {
        "plans": list_plans_public(),
        "saas_enabled": settings.saas_enabled,
        "stripe_enabled": stripe_configured(),
    }


@router.post("/api/billing/checkout")
def billing_checkout(body: CheckoutBody, request: Request, db: Session = Depends(get_db)):
    _require_owner(request)
    tenant_id = _current_tenant_id(request)
    tenant = db.get(Tenant, tenant_id)
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")

    base = settings.app_public_url.rstrip("/")
    success = body.success_url or f"{base}/settings?checkout=success"
    cancel = body.cancel_url or f"{base}/settings?checkout=cancel"
    tenant_ctx = getattr(request.state, "tenant", None)
    email = tenant_ctx.email if tenant_ctx else None

    try:
        url = create_checkout_session(db, tenant, body.plan, success, cancel, email)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"checkout_url": url}


@router.post("/api/billing/upgrade")
def billing_upgrade(body: PlanUpgradeBody, request: Request, db: Session = Depends(get_db)):
    """Stripe 未設定時のデモ用プラン変更（free へのダウングレードは常に可）"""
    _require_owner(request)
    if stripe_configured() and body.plan in ("pro", "enterprise"):
        raise HTTPException(
            status_code=400,
            detail="有料プランは Stripe Checkout を使用してください",
        )
    tenant_id = _current_tenant_id(request)
    try:
        updated = upgrade_plan(db, tenant_id, body.plan)
        return {"tenant": updated, "message": "プランを更新しました"}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/api/billing/webhook")
async def billing_stripe_webhook(request: Request, db: Session = Depends(get_db)):
    payload = await request.body()
    sig = request.headers.get("Stripe-Signature")
    if not settings.stripe_webhook_secret:
        return {"received": True, "note": "STRIPE_WEBHOOK_SECRET 未設定 — ノーオペ"}
    try:
        result = handle_stripe_webhook(payload, sig, db)
        return {"received": True, **result}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.exception("Stripe webhook error: %s", e)
        raise HTTPException(status_code=400, detail="Webhook processing failed")
