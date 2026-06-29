"""マルチシグナル評価 — AI・テクニカル・インテリジェンス・MTF の統合"""

from __future__ import annotations

import asyncio
from typing import Any

from src.ai.signals import generate_ai_signals
from src.analysis.fundamental import get_event_alerts
from src.analysis.market_context import MarketContext
from src.analysis.multi_timeframe import analyze_multi_timeframe
from src.analysis.position_sizing import calculate_position_size, pip_size
from src.analysis.signals import signals_from_row
from src.api.intelligence import build_intelligence
from src.autotrade.models import count_today_trades, last_executed_at
from src.autotrade.positions import has_open_position
from src.broker.oanda import get_account_summary
from src.config import settings
from src.infra.analysis_cache import cache_get, cache_key, cache_put
from src.ml.trend_predictor import predict_trend
from src.ml.volatility_predictor import predict_volatility


SOURCE_WEIGHTS = {
    "ai": 0.35,
    "technical": 0.25,
    "intelligence": 0.20,
    "mtf": 0.10,
    "tradingview": 0.10,
}

ACTION_SCORE = {"buy": 1.0, "sell": -1.0, "hold": 0.0, "alert": 0.0}


def _normalize_action(action: str) -> str:
    action = (action or "hold").lower()
    if any(k in action for k in ("long", "bullish", "buy")):
        return "buy"
    if any(k in action for k in ("short", "bearish", "sell")):
        return "sell"
    return "hold"


async def gather_signal_context(symbol: str, days: int = 200) -> dict[str, Any]:
    """全シグナルソースを並列収集（OHLCV / 指標 / ML の重複計算を排除）"""
    key = cache_key("signal:context", symbol, days=days)
    cached = cache_get(key)
    if cached is not None:
        return cached

    ctx = await asyncio.to_thread(MarketContext.load, symbol, days)
    latest = ctx.result_df.iloc[-1]
    price = ctx.price
    atr = ctx.atr

    mtf = await asyncio.to_thread(analyze_multi_timeframe, symbol)

    trend, volatility = await asyncio.gather(
        asyncio.to_thread(
            predict_trend,
            symbol,
            days,
            result_df=ctx.result_df,
            source=ctx.source,
            mtf=mtf,
        ),
        asyncio.to_thread(
            predict_volatility,
            symbol,
            days,
            result_df=ctx.result_df,
            source=ctx.source,
        ),
    )

    ai, intelligence = await asyncio.gather(
        generate_ai_signals(symbol, days, ctx=ctx, mtf=mtf, trend=trend),
        build_intelligence(symbol, days, trend=trend, volatility=volatility),
    )

    rule_signals = signals_from_row(latest)
    buy_count = sum(1 for s in rule_signals if s["signal"] == "buy")
    sell_count = sum(1 for s in rule_signals if s["signal"] == "sell")
    if buy_count > sell_count:
        tech_action = "buy"
        tech_conf = min(90, 45 + buy_count * 10)
    elif sell_count > buy_count:
        tech_action = "sell"
        tech_conf = min(90, 45 + sell_count * 10)
    else:
        tech_action = "hold"
        tech_conf = 40

    mtf_action = _normalize_action(mtf.get("alignment", "neutral"))
    mtf_conf = 70 if mtf_action in ("buy", "sell") else 45

    intel_score = intelligence.get("composite_score", 0)
    if intel_score > 25:
        intel_action = "buy"
        intel_conf = min(90, 50 + abs(intel_score) * 0.4)
    elif intel_score < -25:
        intel_action = "sell"
        intel_conf = min(90, 50 + abs(intel_score) * 0.4)
    else:
        intel_action = "hold"
        intel_conf = 40

    result = {
        "symbol": symbol.upper(),
        "price": price,
        "source": ctx.source,
        "atr": atr,
        "ai": {"action": ai["action"], "confidence": ai["confidence"]},
        "technical": {"action": tech_action, "confidence": tech_conf, "signals": rule_signals},
        "intelligence": {
            "action": intel_action,
            "confidence": intel_conf,
            "composite_score": intel_score,
            "outlook": intelligence.get("outlook"),
        },
        "mtf": {
            "action": mtf_action,
            "confidence": mtf_conf,
            "alignment": mtf.get("alignment"),
            "alignment_label": mtf.get("alignment_label"),
        },
        "ai_detail": ai,
    }
    cache_put(key, result, ttl_seconds=settings.signal_context_cache_ttl_seconds)
    return result


def fuse_signals(context: dict, config: dict, tv_signal: dict | None = None) -> dict:
    """加重スコアリングで最終アクションを決定"""
    sources = config.get("sources") or list(SOURCE_WEIGHTS.keys())
    votes: list[tuple[str, float, str]] = []

    mapping = {
        "ai": context["ai"],
        "technical": context["technical"],
        "intelligence": context["intelligence"],
        "mtf": context["mtf"],
    }
    for name in sources:
        if name not in mapping:
            continue
        src = mapping[name]
        action = _normalize_action(src["action"])
        conf = float(src.get("confidence", 50)) / 100
        weight = SOURCE_WEIGHTS.get(name, 0.1)
        votes.append((action, conf * weight, name))

    if tv_signal and config.get("auto_execute_tradingview"):
        tv_action = _normalize_action(tv_signal.get("action", "hold"))
        if tv_action in ("buy", "sell"):
            votes.append((tv_action, 0.85 * SOURCE_WEIGHTS["tradingview"], "tradingview"))

    score = 0.0
    total_weight = 0.0
    breakdown: list[dict] = []
    for action, weighted, name in votes:
        score += ACTION_SCORE.get(action, 0) * weighted
        total_weight += weighted
        breakdown.append({"source": name, "action": action, "weight": round(weighted, 3)})

    if total_weight > 0:
        normalized = score / total_weight
    else:
        normalized = 0.0

    if normalized > 0.25:
        final_action = "buy"
    elif normalized < -0.25:
        final_action = "sell"
    else:
        final_action = "hold"

    confidence = min(95, max(30, int(abs(normalized) * 100 + total_weight * 40)))

    return {
        "action": final_action,
        "confidence": confidence,
        "score": round(normalized, 4),
        "breakdown": breakdown,
        "context": context,
    }


def check_risk_guards(
    symbol: str,
    config: dict,
    tenant_id: int | None,
    fused: dict,
    dry_run: bool = False,
) -> tuple[bool, str]:
    """リスクガード — イベント・クールダウン・日次上限・信頼度"""
    if fused["action"] == "hold":
        return False, "シグナルが hold — エントリー条件未達"

    min_conf = config.get("min_confidence", 65)
    if fused["confidence"] < min_conf:
        return False, f"信頼度 {fused['confidence']}% < 最低 {min_conf}%"

    if config.get("require_mtf_alignment"):
        mtf_action = fused["context"]["mtf"]["action"]
        if mtf_action != "hold" and mtf_action != fused["action"]:
            return False, f"MTF ({mtf_action}) とシグナル ({fused['action']}) が不一致"

    blackout = config.get("event_blackout_hours", 4)
    if blackout > 0:
        alerts = get_event_alerts(blackout)
        if alerts:
            titles = ", ".join(a["title"] for a in alerts[:2])
            return False, f"高影響イベント前後 ({titles}) — ブラックアウト中"

    max_daily = config.get("max_daily_trades", 3)
    today_count = count_today_trades(tenant_id, symbol)
    if today_count >= max_daily:
        return False, f"本日の取引上限 ({max_daily}) に到達"

    cooldown = config.get("cooldown_minutes", 60)
    last = last_executed_at(tenant_id, symbol)
    if last and cooldown > 0:
        from datetime import datetime, timezone

        elapsed = (datetime.now(timezone.utc) - last).total_seconds() / 60
        if elapsed < cooldown:
            return False, f"クールダウン中（残り {int(cooldown - elapsed)} 分）"

    if not config.get("allow_add_to_position", False) and has_open_position(tenant_id, symbol):
        return False, "同一通貨にオープンポジションあり — 決済後に再エントリー"

    return True, "リスクチェック通過"


def compute_order_size(symbol: str, config: dict, context: dict, side: str, tenant_id: int | None = None) -> dict:
    """ATR ベースのポジションサイズ + SL/TP 価格"""
    trading_mode = config.get("mode", "paper")
    acct = get_account_summary(tenant_id, trading_mode)
    balance = float(config.get("account_balance") or acct.get("balance") or 10000)
    risk_pct = float(config.get("risk_percent", 1.0))
    price = context["price"]
    atr = context.get("atr")

    sizing = calculate_position_size(symbol, price, balance, risk_pct, atr=atr)
    lots = sizing["recommended_lots"]
    lots = max(float(config.get("min_lots", 0.01)), min(lots, float(config.get("max_lots", 1.0))))
    min_units = int(config.get("min_units", 1000))
    units = max(min_units, int(lots * 100_000))

    stop_pips = sizing.get("stop_pips", 30)
    pip = pip_size(symbol)
    rr = float(config.get("risk_reward", 2.0))
    stop_dist = stop_pips * pip
    tp_dist = stop_dist * rr

    if side == "buy":
        stop_loss = round(price - stop_dist, 5 if not symbol.endswith("JPY") else 3) if config.get("use_stop_loss", True) else None
        take_profit = round(price + tp_dist, 5 if not symbol.endswith("JPY") else 3) if config.get("use_take_profit", True) else None
    else:
        stop_loss = round(price + stop_dist, 5 if not symbol.endswith("JPY") else 3) if config.get("use_stop_loss", True) else None
        take_profit = round(price - tp_dist, 5 if not symbol.endswith("JPY") else 3) if config.get("use_take_profit", True) else None

    return {
        "units": units,
        "lots": lots,
        "sizing": sizing,
        "account_balance": balance,
        "side": side,
        "entry_price": price,
        "stop_loss": stop_loss,
        "take_profit": take_profit,
        "stop_pips": stop_pips,
        "risk_reward": rr,
    }