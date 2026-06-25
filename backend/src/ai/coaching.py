"""売買履歴ベースの AI コーチング"""

import asyncio
from collections import Counter

from src.ai.client import chat_json, resolve_openai_api_key
from src.broker.oanda import list_orders


def _order_stats(orders: list[dict]) -> dict:
    if not orders:
        return {"total": 0, "message": "取引履歴がありません"}
    by_side = Counter(o["side"] for o in orders)
    by_symbol = Counter(o["symbol"] for o in orders)
    filled = [o for o in orders if o.get("status") == "FILLED"]
    return {
        "total": len(orders),
        "filled": len(filled),
        "buy_count": by_side.get("buy", 0),
        "sell_count": by_side.get("sell", 0),
        "symbols_traded": dict(by_symbol),
        "recent": orders[:10],
    }


async def generate_coaching(symbol: str, tenant_id: int | None = None, limit: int = 30) -> dict:
    orders = list_orders(limit, tenant_id)
    symbol_orders = [o for o in orders if o["symbol"] == symbol.upper()]
    stats = _order_stats(symbol_orders or orders)

    result = {
        "symbol": symbol.upper(),
        "trade_stats": stats,
        "coaching": None,
    }

    if not resolve_openai_api_key():
        result["coaching"] = _rule_coaching(stats)
        return result

    history_text = "\n".join(
        f"- {o.get('created_at', '')[:10]} {o['symbol']} {o['side']} "
        f"{o['units']}units @ {o.get('fill_price', '—')} ({o['status']})"
        for o in stats.get("recent", [])
    ) or "（履歴なし）"

    try:
        ai = await asyncio.to_thread(
            chat_json,
            """FXトレードコーチとして、売買履歴から改善点を指導。JSONのみ:
{
  "overall_assessment": "総合評価（日本語）",
  "strengths": ["強み1"],
  "weaknesses": ["改善点1"],
  "behavioral_patterns": ["パターン1"],
  "recommendations": ["具体的アドバイス1", "アドバイス2"],
  "next_focus": "次に集中すべきこと（1文）",
  "risk_discipline_score": 0-100
}""",
            f"通貨ペア: {symbol}\n統計: {stats}\n\n直近取引:\n{history_text}",
        )
        result["coaching"] = ai
    except Exception as e:
        result["coaching"] = _rule_coaching(stats)
        result["coaching_error"] = str(e)

    return result


def _rule_coaching(stats: dict) -> dict:
    if stats.get("total", 0) == 0:
        return {
            "overall_assessment": "まだ取引履歴がありません。ペーパー取引で記録を蓄積しましょう。",
            "recommendations": ["小ロットでエントリーし、損切りルールを先に決める"],
            "next_focus": "最初の10トレードは利益よりルール遵守を優先",
            "risk_discipline_score": 50,
        }
    buy = stats.get("buy_count", 0)
    sell = stats.get("sell_count", 0)
    bias = "買い偏重" if buy > sell * 1.5 else ("売り偏重" if sell > buy * 1.5 else "バランス型")
    return {
        "overall_assessment": f"取引{stats['total']}件。{bias}の傾向があります。",
        "recommendations": [
            "1トレードのリスクを口座の1-2%に制限",
            "エントリー前に必ず損切り価格を設定",
            "同方向への連続エントリーを避ける",
        ],
        "next_focus": "勝率よりリスクリワード比の改善",
        "risk_discipline_score": 60,
    }
