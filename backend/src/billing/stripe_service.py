"""Stripe 課金 — Checkout / Webhook"""

from __future__ import annotations

import logging

import stripe
from sqlalchemy.orm import Session

from src.auth.models import Tenant
from src.config import settings

logger = logging.getLogger(__name__)

PLAN_PRICE_ENV = {
    "pro": "stripe_price_pro",
    "enterprise": "stripe_price_enterprise",
}


def stripe_configured() -> bool:
    return bool(settings.stripe_secret_key)


def _price_id_for_plan(plan: str) -> str | None:
    attr = PLAN_PRICE_ENV.get(plan)
    if not attr:
        return None
    return getattr(settings, attr, "") or None


def create_checkout_session(
    db: Session,
    tenant: Tenant,
    plan: str,
    success_url: str,
    cancel_url: str,
    customer_email: str | None = None,
) -> str:
    if plan not in ("pro", "enterprise"):
        raise ValueError("Checkout は pro / enterprise プランのみ対応")
    if not stripe_configured():
        raise ValueError("STRIPE_SECRET_KEY が未設定です")

    price_id = _price_id_for_plan(plan)
    if not price_id:
        raise ValueError(f"Stripe Price ID が未設定です（STRIPE_PRICE_{plan.upper()}）")

    stripe.api_key = settings.stripe_secret_key
    params: dict = {
        "mode": "subscription",
        "line_items": [{"price": price_id, "quantity": 1}],
        "success_url": success_url,
        "cancel_url": cancel_url,
        "metadata": {"tenant_id": str(tenant.id), "plan": plan},
        "subscription_data": {"metadata": {"tenant_id": str(tenant.id), "plan": plan}},
    }
    if tenant.stripe_customer_id:
        params["customer"] = tenant.stripe_customer_id
    elif customer_email:
        params["customer_email"] = customer_email

    session = stripe.checkout.Session.create(**params)
    if not session.url:
        raise ValueError("Checkout URL の生成に失敗しました")
    return session.url


def handle_stripe_webhook(payload: bytes, sig_header: str | None, db: Session) -> dict:
    if not settings.stripe_webhook_secret:
        raise ValueError("STRIPE_WEBHOOK_SECRET が未設定です")
    if not settings.stripe_secret_key:
        raise ValueError("STRIPE_SECRET_KEY が未設定です")

    stripe.api_key = settings.stripe_secret_key
    event = stripe.Webhook.construct_event(payload, sig_header or "", settings.stripe_webhook_secret)

    event_type = event["type"]
    data = event["data"]["object"]

    if event_type == "checkout.session.completed":
        return _on_checkout_completed(db, data)
    if event_type in ("customer.subscription.updated", "customer.subscription.created"):
        return _on_subscription_updated(db, data)
    if event_type == "customer.subscription.deleted":
        return _on_subscription_deleted(db, data)

    return {"handled": False, "type": event_type}


def _on_checkout_completed(db: Session, session: dict) -> dict:
    tenant_id = int(session.get("metadata", {}).get("tenant_id", 0))
    plan = session.get("metadata", {}).get("plan", "pro")
    tenant = db.get(Tenant, tenant_id)
    if not tenant:
        logger.warning("checkout completed for unknown tenant %s", tenant_id)
        return {"handled": False, "reason": "tenant_not_found"}

    tenant.plan = plan
    if session.get("customer"):
        tenant.stripe_customer_id = session["customer"]
    sub_id = session.get("subscription")
    if sub_id:
        tenant.stripe_subscription_id = sub_id
    db.commit()
    logger.info("Stripe checkout completed tenant=%s plan=%s", tenant_id, plan)
    return {"handled": True, "tenant_id": tenant_id, "plan": plan}


def _on_subscription_updated(db: Session, sub: dict) -> dict:
    tenant_id = int(sub.get("metadata", {}).get("tenant_id", 0))
    plan = sub.get("metadata", {}).get("plan")
    tenant = db.get(Tenant, tenant_id)
    if not tenant:
        return {"handled": False, "reason": "tenant_not_found"}

    status = sub.get("status", "")
    if status in ("active", "trialing") and plan:
        tenant.plan = plan
        tenant.stripe_subscription_id = sub.get("id")
        if sub.get("customer"):
            tenant.stripe_customer_id = sub["customer"]
        db.commit()
        return {"handled": True, "tenant_id": tenant_id, "plan": plan}

    if status in ("canceled", "unpaid", "past_due"):
        tenant.plan = "free"
        db.commit()
        return {"handled": True, "tenant_id": tenant_id, "plan": "free"}

    return {"handled": False, "status": status}


def _on_subscription_deleted(db: Session, sub: dict) -> dict:
    tenant_id = int(sub.get("metadata", {}).get("tenant_id", 0))
    tenant = db.get(Tenant, tenant_id)
    if not tenant:
        return {"handled": False, "reason": "tenant_not_found"}
    tenant.plan = "free"
    tenant.stripe_subscription_id = None
    db.commit()
    logger.info("Stripe subscription deleted tenant=%s -> free", tenant_id)
    return {"handled": True, "tenant_id": tenant_id, "plan": "free"}


def create_portal_session(tenant: Tenant, return_url: str) -> str:
    if not stripe_configured():
        raise ValueError("STRIPE_SECRET_KEY が未設定です")
    if not tenant.stripe_customer_id:
        raise ValueError("Stripe 顧客 ID がありません。先に有料プランを申し込んでください")

    stripe.api_key = settings.stripe_secret_key
    session = stripe.billing_portal.Session.create(
        customer=tenant.stripe_customer_id,
        return_url=return_url,
    )
    if not session.url:
        raise ValueError("ポータル URL の生成に失敗しました")
    return session.url


def billing_status(tenant: Tenant) -> dict:
    from src.auth.plans import PLANS, daily_limit

    plan = tenant.plan if tenant.plan in PLANS else "free"
    info = PLANS[plan]
    return {
        "plan": plan,
        "plan_name": info["name"],
        "price_monthly_usd": info["price_monthly_usd"],
        "daily_api_limit": daily_limit(plan),
        "stripe_customer_id": tenant.stripe_customer_id,
        "stripe_subscription_id": tenant.stripe_subscription_id,
        "has_active_subscription": bool(tenant.stripe_subscription_id),
        "stripe_enabled": stripe_configured(),
    }
