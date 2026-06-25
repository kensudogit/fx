"""リアルタイム価格 WebSocket"""

from __future__ import annotations

import asyncio
import json
import logging

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect

from src.auth.security import decode_access_token
from src.broker.oanda import fetch_live_prices
from src.data.sample_data import SYMBOL_BASE_PRICES

logger = logging.getLogger(__name__)
router = APIRouter(tags=["Prices"])


def _tenant_from_token(token: str | None) -> int | None:
    if not token:
        return None
    payload = decode_access_token(token)
    if payload and payload.get("tenant_id"):
        return int(payload["tenant_id"])
    return None


@router.websocket("/api/ws/prices")
async def websocket_prices(
    websocket: WebSocket,
    token: str | None = Query(default=None),
):
    await websocket.accept()
    tenant_id = _tenant_from_token(token)
    symbols = list(SYMBOL_BASE_PRICES.keys())
    interval_sec = 3

    try:
        while True:
            try:
                raw = await asyncio.wait_for(websocket.receive_text(), timeout=0.05)
                msg = json.loads(raw)
                if msg.get("symbols"):
                    symbols = [s.upper() for s in msg["symbols"] if s.upper() in SYMBOL_BASE_PRICES]
                if msg.get("interval"):
                    interval_sec = max(1, min(30, int(msg["interval"])))
            except asyncio.TimeoutError:
                pass
            except json.JSONDecodeError:
                pass

            prices = fetch_live_prices(symbols, tenant_id, trading_mode="live")
            await websocket.send_json(
                {
                    "type": "prices",
                    "data": prices,
                    "symbols": symbols,
                }
            )
            await asyncio.sleep(interval_sec)
    except WebSocketDisconnect:
        logger.debug("price websocket disconnected tenant=%s", tenant_id)
    except Exception as e:
        logger.warning("price websocket error: %s", e)
        await websocket.close(code=1011)


@router.get("/api/prices/live")
async def live_prices(symbols: str = "USDJPY,EURUSD"):
    sym_list = [s.strip().upper() for s in symbols.split(",") if s.strip()]
    return {"prices": fetch_live_prices(sym_list, None, trading_mode="live")}
