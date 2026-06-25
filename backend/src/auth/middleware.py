"""SaaS 認証ミドルウェア"""

import logging

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from src.auth.models import record_usage
from src.auth.plans import PREMIUM_PATH_EXACT, PREMIUM_PATH_PREFIXES, daily_limit, plan_features
from src.auth.security import decode_access_token
from src.auth.service import TenantContext, resolve_api_key
from src.config import settings
from src.db.database import SessionLocal

logger = logging.getLogger(__name__)

PUBLIC_API_PATHS = {
    "/api/auth/register",
    "/api/auth/login",
    "/api/billing/plans",
    "/api/billing/webhook",
    "/api/ai/status",
}

PUBLIC_API_PREFIXES = (
    "/api/symbols",
)


def _is_public_api(path: str, method: str) -> bool:
    if path in PUBLIC_API_PATHS:
        return True
    if path.startswith("/api/symbols"):
        return True
    if path == "/api/tradingview/webhook" and method == "POST":
        return True
    return False


def _requires_premium(path: str, method: str) -> bool:
    if path == "/api/ai/status":
        return False
    if (method, path) in PREMIUM_PATH_EXACT:
        return True
    return any(path.startswith(p) for p in PREMIUM_PATH_PREFIXES)


def _resolve_tenant(request: Request) -> TenantContext | None:
    auth = request.headers.get("Authorization", "")
    if auth.lower().startswith("bearer "):
        token = auth[7:].strip()
        payload = decode_access_token(token)
        if payload:
            return TenantContext(
                tenant_id=int(payload["tenant_id"]),
                tenant_slug="",
                plan="free",
                user_id=int(payload["sub"]),
                email=payload.get("email"),
                role=payload.get("role"),
                auth_via="jwt",
            )

    api_key = request.headers.get("X-API-Key", "").strip()
    if api_key:
        db = SessionLocal()
        try:
            ctx = resolve_api_key(db, api_key)
            return ctx
        finally:
            db.close()

    return None


class SaaSAuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if not settings.saas_enabled:
            return await call_next(request)

        path = request.url.path
        method = request.method

        if not path.startswith("/api/"):
            return await call_next(request)

        if _is_public_api(path, method):
            return await call_next(request)

        ctx = _resolve_tenant(request)
        if not ctx:
            return JSONResponse(status_code=401, content={"detail": "認証が必要です。ログインまたは API キーを設定してください。"})

        db = SessionLocal()
        try:
            from src.auth.models import Tenant

            tenant = db.get(Tenant, ctx.tenant_id)
            if not tenant:
                return JSONResponse(status_code=401, content={"detail": "テナントが見つかりません"})
            ctx.plan = tenant.plan
            ctx.tenant_slug = tenant.slug
        finally:
            db.close()

        from src.auth.models import count_daily_usage

        used = count_daily_usage(ctx.tenant_id)
        limit = daily_limit(ctx.plan)
        if used >= limit:
            return JSONResponse(
                status_code=429,
                content={
                    "detail": (
                        f"1日のAPI利用上限 ({limit}) に達しました。"
                        f"{' Pro プラン（2,000 回/日）へのアップグレードをご検討ください。' if ctx.plan == 'free' else ' 明日以降に再試行するか、プランをアップグレードしてください。'}"
                    ),
                    "usage": used,
                    "limit": limit,
                    "plan": ctx.plan,
                },
            )

        if _requires_premium(path, method):
            feats = plan_features(ctx.plan)
            if path.startswith("/api/pro/") and not feats.get("ai_pro"):
                return JSONResponse(status_code=403, content={"detail": "AI Pro 機能は Pro プラン以上で利用できます"})
            if path.startswith("/api/ai/") and not feats.get("ai"):
                return JSONResponse(status_code=403, content={"detail": "AI分析は Pro プラン以上で利用できます"})
            if path.startswith("/api/analysis/intelligence/") and not feats.get("analysis_intelligence"):
                return JSONResponse(status_code=403, content={"detail": "統合インテリジェンス分析は Pro プラン以上で利用できます"})
            if path == "/api/oanda/orders" and method == "POST" and not feats.get("oanda_orders"):
                return JSONResponse(status_code=403, content={"detail": "OANDA 注文は Pro プラン以上で利用できます"})
            if path.startswith("/api/autotrade/") and not feats.get("autotrade"):
                return JSONResponse(status_code=403, content={"detail": "自動取引は Pro プラン以上で利用できます"})

        request.state.tenant = ctx
        from src.auth.context import set_tenant_context

        set_tenant_context(ctx)
        response = await call_next(request)

        if response.status_code < 400:
            record_usage(ctx.tenant_id, path)

        return response
