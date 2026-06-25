"""自動取引オーケストレータ — 評価・実行・ログ"""

from __future__ import annotations

import logging
from typing import Any

from src.autotrade.evaluator import (
    check_risk_guards,
    compute_order_size,
    fuse_signals,
    gather_signal_context,
)
from src.autotrade.models import get_config, save_run
from src.autotrade.positions import check_exits, open_position
from src.broker.oanda import fetch_live_prices, place_market_order

logger = logging.getLogger(__name__)


async def evaluate_symbol(
    symbol: str,
    tenant_id: int | None = None,
    tv_signal: dict | None = None,
    dry_run: bool = True,
) -> dict:
    """シグナル評価（dry_run=True なら注文しない）"""
    config = get_config(tenant_id)
    if not config.get("enabled") and not dry_run:
        return _result(symbol, "disabled", "hold", 0, "自動取引が無効です", {}, tenant_id)

    context = await gather_signal_context(symbol)
    fused = fuse_signals(context, config, tv_signal)
    passed, guard_reason = check_risk_guards(symbol, config, tenant_id, fused, dry_run)

    order_plan = None
    if fused["action"] in ("buy", "sell") and passed:
        order_plan = compute_order_size(symbol, config, context, fused["action"], tenant_id)

    snapshot = {
        "fused": {k: v for k, v in fused.items() if k != "context"},
        "breakdown": fused.get("breakdown"),
        "guard_reason": guard_reason,
        "order_plan": order_plan,
        "price": context["price"],
    }

    if fused["action"] == "hold":
        return _result(symbol, "skipped", "hold", fused["confidence"], "hold シグナル", snapshot, tenant_id)

    if not passed:
        return _result(symbol, "blocked", fused["action"], fused["confidence"], guard_reason, snapshot, tenant_id)

    if dry_run:
        return _result(
            symbol,
            "ready",
            fused["action"],
            fused["confidence"],
            f"実行可能 — {guard_reason}",
            snapshot,
            tenant_id,
            order_plan=order_plan,
        )

    return await execute_order(symbol, fused, order_plan, snapshot, tenant_id, trigger="manual")


async def execute_order(
    symbol: str,
    fused: dict,
    order_plan: dict | None,
    snapshot: dict,
    tenant_id: int | None,
    trigger: str = "scheduler",
) -> dict:
    """成行注文を実行してログ保存"""
    action = fused["action"]
    if action not in ("buy", "sell"):
        return _result(symbol, "skipped", action, fused["confidence"], "hold", snapshot, tenant_id)

    if not order_plan:
        order_plan = compute_order_size(symbol, get_config(tenant_id), fused["context"], action, tenant_id)

    trading_mode = get_config(tenant_id).get("mode", "paper")
    try:
        order = place_market_order(
            symbol,
            action,
            order_plan["units"],
            tenant_id,
            stop_loss=order_plan.get("stop_loss"),
            take_profit=order_plan.get("take_profit"),
            trading_mode=trading_mode,
        )
    except Exception as e:
        logger.exception("autotrade order failed: %s", e)
        rec = _result(
            symbol, "failed", action, fused["confidence"], str(e), snapshot, tenant_id, trigger=trigger
        )
        save_run(rec, tenant_id)
        return rec

    fill_price = order.get("fill_price") or order_plan.get("entry_price")
    open_position(
        tenant_id,
        symbol,
        action,
        order_plan["units"],
        float(fill_price) if fill_price else 0,
        order_plan.get("stop_loss"),
        order_plan.get("take_profit"),
        order.get("id"),
    )

    rec = _result(
        symbol,
        "executed",
        action,
        fused["confidence"],
        f"{action.upper()} {order_plan['units']} units @ {order.get('fill_price')}",
        snapshot,
        tenant_id,
        trigger=trigger,
        units=order_plan["units"],
        fill_price=order.get("fill_price"),
        order_id=order.get("id"),
    )
    save_run(rec, tenant_id)
    return rec


async def run_cycle(tenant_id: int | None = None, trigger: str = "scheduler") -> list[dict]:
    """設定された全シンボルで1サイクル実行"""
    config = get_config(tenant_id)
    if not config.get("enabled"):
        return []

    trading_mode = config.get("mode", "paper")
    results = []
    for symbol in config.get("symbols", ["USDJPY"]):
        try:
            live = fetch_live_prices([symbol], tenant_id, trading_mode)
            live_price = live.get(symbol.upper(), {}).get("price")
            context = await gather_signal_context(symbol)
            price = float(live_price) if live_price else context["price"]
            fused = fuse_signals(context, config)

            for ex in check_exits(
                symbol, price, tenant_id,
                reverse_action=fused["action"],
                auto_exit_on_reverse=config.get("auto_exit_on_reverse", True),
                trading_mode=trading_mode,
            ):
                rec = _result(
                    symbol, "executed", "close", fused["confidence"],
                    f"決済 ({ex.get('close_reason', 'exit')}) @ {price}",
                    {"exit": ex, "price": price}, tenant_id, trigger=trigger,
                )
                save_run(rec, tenant_id)
                results.append(rec)

            passed, guard_reason = check_risk_guards(symbol, config, tenant_id, fused)

            snapshot = {
                "fused": {k: v for k, v in fused.items() if k != "context"},
                "breakdown": fused.get("breakdown"),
                "guard_reason": guard_reason,
                "price": context["price"],
            }

            if fused["action"] == "hold" or not passed:
                rec = _result(
                    symbol,
                    "skipped" if fused["action"] == "hold" else "blocked",
                    fused["action"],
                    fused["confidence"],
                    guard_reason,
                    snapshot,
                    tenant_id,
                    trigger=trigger,
                )
                save_run(rec, tenant_id)
                results.append(rec)
                continue

            order_plan = compute_order_size(symbol, config, context, fused["action"], tenant_id)
            snapshot["order_plan"] = order_plan
            rec = await execute_order(symbol, fused, order_plan, snapshot, tenant_id, trigger=trigger)
            results.append(rec)
        except Exception as e:
            logger.exception("autotrade cycle %s: %s", symbol, e)
            results.append(
                _result(symbol, "failed", "hold", 0, str(e), {}, tenant_id, trigger=trigger)
            )
    return results


async def process_tradingview_signal(signal: dict, tenant_id: int | None = None) -> dict | None:
    """TradingView Webhook 受信時の自動実行"""
    config = get_config(tenant_id)
    if not config.get("enabled") or not config.get("auto_execute_tradingview"):
        return None

    symbol = signal.get("symbol", "").upper()
    if symbol and symbol not in [s.upper() for s in config.get("symbols", [])]:
        return None

    return await evaluate_symbol(symbol, tenant_id, tv_signal=signal, dry_run=False)


def _result(
    symbol: str,
    decision: str,
    action: str,
    confidence: int | float,
    reason: str,
    snapshot: dict,
    tenant_id: int | None,
    trigger: str = "evaluate",
    units: int | None = None,
    fill_price: float | None = None,
    order_id: int | None = None,
    order_plan: dict | None = None,
) -> dict:
    if order_plan and "order_plan" not in snapshot:
        snapshot["order_plan"] = order_plan
    return {
        "symbol": symbol.upper(),
        "decision": decision,
        "action": action,
        "confidence": confidence,
        "reason": reason,
        "trigger": trigger,
        "units": units,
        "fill_price": fill_price,
        "order_id": order_id,
        "signal_snapshot": snapshot,
        "tenant_id": tenant_id,
    }
