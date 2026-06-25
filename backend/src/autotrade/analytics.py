"""運用パフォーマンス分析"""

from src.autotrade.models import list_runs
from src.broker.oanda import list_orders


def build_performance(tenant_id: int | None = None, limit: int = 100) -> dict:
    runs = list_runs(limit, tenant_id)
    orders = list_orders(limit, tenant_id)

    executed = [r for r in runs if r.get("decision") == "executed"]
    blocked = [r for r in runs if r.get("decision") == "blocked"]
    skipped = [r for r in runs if r.get("decision") == "skipped"]

    buy_count = sum(1 for r in executed if r.get("action") == "buy")
    sell_count = sum(1 for r in executed if r.get("action") == "sell")

    confidences = [r["confidence"] for r in executed if r.get("confidence") is not None]
    avg_conf = round(sum(confidences) / len(confidences), 1) if confidences else 0

    block_reasons: dict[str, int] = {}
    for r in blocked:
        reason = (r.get("reason") or "unknown")[:40]
        block_reasons[reason] = block_reasons.get(reason, 0) + 1

    top_blocks = sorted(block_reasons.items(), key=lambda x: -x[1])[:5]

    return {
        "summary": {
            "total_runs": len(runs),
            "executed": len(executed),
            "blocked": len(blocked),
            "skipped": len(skipped),
            "execution_rate_pct": round(len(executed) / max(len(runs), 1) * 100, 1),
            "avg_confidence": avg_conf,
            "buy_trades": buy_count,
            "sell_trades": sell_count,
        },
        "broker_orders": len(orders),
        "top_block_reasons": [{"reason": r, "count": c} for r, c in top_blocks],
        "recent_executed": executed[:10],
        "maintenance_hint": _maintenance_hint(len(executed), len(blocked), avg_conf),
    }


def _maintenance_hint(executed: int, blocked: int, avg_conf: float) -> str:
    if executed == 0 and blocked > 5:
        return "ブロックが多い — 最低信頼度を下げるか、イベント回避時間を短縮してください（週1回見直し推奨）。"
    if avg_conf < 60 and executed > 0:
        return "平均信頼度が低め — プリセットを「安定型」に変更することを検討してください。"
    if executed >= 10:
        return "運用中 — 週1回、シミュレーション結果と実行ログを確認してください（トライオートFX推奨と同様）。"
    return "ドライラン評価 → シミュレーション確認 → 有効化の順で開始してください。"
