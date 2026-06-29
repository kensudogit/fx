"""AI 売買シグナル生成（テクニカル + ML + OpenAI 統合）"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from src.ai.analyzer import make_trading_decision
from src.ai.client import resolve_openai_api_key
from src.analysis.multi_timeframe import analyze_multi_timeframe
from src.analysis.signals import signals_from_row
from src.ml.trend_predictor import predict_trend

if TYPE_CHECKING:
    from src.analysis.market_context import MarketContext


async def generate_ai_signals(
    symbol: str,
    days: int = 200,
    *,
    ctx: MarketContext | None = None,
    mtf: dict | None = None,
    trend: dict | None = None,
) -> dict:
    if ctx is None:
        from src.analysis.market_context import MarketContext

        ctx = await asyncio.to_thread(MarketContext.load, symbol, days)

    latest = ctx.result_df.iloc[-1]
    price = float(latest["close"])
    rule_signals = signals_from_row(latest)

    if mtf is None:
        mtf = await asyncio.to_thread(analyze_multi_timeframe, symbol)
    if trend is None:
        trend = await asyncio.to_thread(
            predict_trend,
            symbol,
            days,
            result_df=ctx.result_df,
            source=ctx.source,
            mtf=mtf,
        )

    buy = sum(1 for s in rule_signals if s["signal"] == "buy")
    sell = sum(1 for s in rule_signals if s["signal"] == "sell")

    votes: list[str] = []
    if buy > sell:
        votes.append("bullish")
    elif sell > buy:
        votes.append("bearish")
    else:
        votes.append("neutral")
    votes.append(trend["trend"])
    if mtf.get("alignment") in ("bullish", "bearish", "neutral"):
        votes.append(mtf["alignment"])

    bull = votes.count("bullish")
    bear = votes.count("bearish")
    if bull > bear:
        composite_action = "buy"
        confidence = min(95, 50 + bull * 15)
    elif bear > bull:
        composite_action = "sell"
        confidence = min(95, 50 + bear * 15)
    else:
        composite_action = "hold"
        confidence = 40

    ai_decision = None
    if resolve_openai_api_key():
        try:
            ai_decision = await make_trading_decision(symbol, days)
            if ai_decision.get("action") in ("buy", "sell", "hold"):
                if ai_decision["action"] == composite_action or composite_action == "hold":
                    confidence = max(confidence, int(ai_decision.get("confidence", 0) * 100))
                composite_action = ai_decision["action"]
        except Exception:
            pass

    return {
        "symbol": symbol.upper(),
        "source": ctx.source,
        "price": round(price, 4),
        "action": composite_action,
        "confidence": confidence,
        "rule_signals": rule_signals,
        "multi_timeframe": mtf,
        "trend_ml": {
            "trend": trend["trend"],
            "label": trend["trend_label"],
            "confidence": trend["confidence"],
        },
        "ai_decision": ai_decision,
        "summary": _signal_summary(composite_action, confidence, rule_signals, trend, mtf),
    }


def _signal_summary(action, confidence, rules, trend, mtf) -> str:
    action_ja = {"buy": "買い", "sell": "売り", "hold": "様子見"}.get(action, action)
    buy = sum(1 for s in rules if s["signal"] == "buy")
    sell = sum(1 for s in rules if s["signal"] == "sell")
    return (
        f"総合シグナル: {action_ja}（信頼度 {confidence}%）。"
        f"テクニカル {buy}買い/{sell}売り、"
        f"トレンド予測 {trend['trend_label']}、"
        f"MTF {mtf.get('alignment_label', '—')}。"
    )
