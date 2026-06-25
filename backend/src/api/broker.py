"""ブローカー設定 API"""

from pydantic import BaseModel, Field

from fastapi import APIRouter, HTTPException, Request

from src.auth.context import get_tenant_id
from src.broker.oanda import get_account_summary
from src.broker.tenant_oanda import get_tenant_oanda_settings, save_tenant_oanda_settings

router = APIRouter(tags=["Broker"])


class OandaSettingsBody(BaseModel):
    api_token: str | None = None
    account_id: str | None = None
    environment: str | None = Field(default=None, pattern="^(practice|live)$")
    clear_token: bool = False


def _tenant(request: Request) -> int:
    tenant = getattr(request.state, "tenant", None)
    if tenant:
        return tenant.tenant_id
    tid = get_tenant_id()
    if tid is None:
        raise HTTPException(status_code=401, detail="認証が必要です")
    return tid


@router.get("/api/broker/oanda/settings")
async def get_oanda_settings(request: Request):
    tid = _tenant(request)
    settings_row = get_tenant_oanda_settings(tid)
    summary = get_account_summary(tid, "live")
    return {
        "settings": settings_row,
        "account_summary": summary,
    }


@router.put("/api/broker/oanda/settings")
async def update_oanda_settings(body: OandaSettingsBody, request: Request):
    tid = _tenant(request)
    try:
        saved = save_tenant_oanda_settings(
            tid,
            api_token=body.api_token,
            account_id=body.account_id,
            environment=body.environment,
            clear_token=body.clear_token,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"settings": saved}
