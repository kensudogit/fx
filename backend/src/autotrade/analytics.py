"""
運用パフォーマンス分析モジュール

自動取引の実行ログ・ブローカー注文・決済ポジションを横断的に集計し、
パフォーマンス指標・PnL サマリー・メンテナンスヒントを構築する。
API レイヤー（/api/autotrade/performance など）から呼び出される。
"""

from src.autotrade.models import list_runs
from src.autotrade.pnl import aggregate_pnl, weekly_pnl_breakdown
from src.autotrade.positions import list_closed_positions
from src.broker.oanda import list_orders


def build_performance(tenant_id: int | None = None, limit: int = 100) -> dict:
    """
    運用パフォーマンスの全体サマリーを構築する。

    直近の実行ログ・ブローカー注文・決済済みポジションを収集し、
    実行率・平均信頼度・PnL・ブロック理由などを一括返却する。

    Args:
        tenant_id: テナント識別子。None の場合は非マルチテナント環境で動作。
        limit: 取得するログの上限件数（デフォルト 100 件）。

    Returns:
        以下のキーを含む辞書:
            - summary: 実行件数・ブロック件数・実行率・平均信頼度など
            - pnl: 実現損益合計 + 週次内訳
            - broker_orders: ブローカーに送信された注文数
            - top_block_reasons: ブロック理由の上位 5 件（理由・件数）
            - recent_executed: 直近 10 件の実行ログ
            - recent_closed: 直近 10 件の決済済みポジション
            - maintenance_hint: 運用状態に応じたメンテナンス推奨メッセージ
    """
    # 実行ログ・注文履歴・決済ポジションを取得
    runs = list_runs(limit, tenant_id)
    orders = list_orders(limit, tenant_id)
    closed = list_closed_positions(tenant_id, days=90)

    # decision フィールドでログを分類
    # "executed" = 注文が実際にブローカーへ送信・成立した
    # "blocked"  = リスクガードや信頼度不足などで注文を見送った
    # "skipped"  = hold シグナルのため注文しなかった
    executed = [r for r in runs if r.get("decision") == "executed"]
    blocked = [r for r in runs if r.get("decision") == "blocked"]
    skipped = [r for r in runs if r.get("decision") == "skipped"]

    # 実行ログのうち buy / sell それぞれの件数をカウント
    buy_count = sum(1 for r in executed if r.get("action") == "buy")
    sell_count = sum(1 for r in executed if r.get("action") == "sell")

    # 実行済みログの平均信頼度を算出（信頼度が None のレコードは除外）
    confidences = [r["confidence"] for r in executed if r.get("confidence") is not None]
    avg_conf = round(sum(confidences) / len(confidences), 1) if confidences else 0

    # ブロック理由ごとに集計（理由文字列は最大 40 文字に切り詰めてキーにする）
    block_reasons: dict[str, int] = {}
    for r in blocked:
        reason = (r.get("reason") or "unknown")[:40]
        block_reasons[reason] = block_reasons.get(reason, 0) + 1

    # 件数降順で上位 5 件のブロック理由を取得
    top_blocks = sorted(block_reasons.items(), key=lambda x: -x[1])[:5]

    # 決済済みポジションから PnL を集計し、週次内訳（直近 4 週）も生成
    pnl_summary = aggregate_pnl(closed)
    weekly = weekly_pnl_breakdown(closed, weeks=4)

    return {
        "summary": {
            "total_runs": len(runs),
            "executed": len(executed),
            "blocked": len(blocked),
            "skipped": len(skipped),
            # 実行率 = 実行件数 / 全ログ件数（ゼロ除算を max で回避）
            "execution_rate_pct": round(len(executed) / max(len(runs), 1) * 100, 1),
            "avg_confidence": avg_conf,
            "buy_trades": buy_count,
            "sell_trades": sell_count,
        },
        "pnl": {
            **pnl_summary,
            "weekly": weekly,
        },
        "broker_orders": len(orders),
        # top_block_reasons はフロントエンドで円グラフ等に利用
        "top_block_reasons": [{"reason": r, "count": c} for r, c in top_blocks],
        # 直近 10 件を UI の「最近の実行」テーブルに表示
        "recent_executed": executed[:10],
        "recent_closed": closed[:10],
        # 運用状態を診断してユーザーへ具体的な改善提案を返す
        "maintenance_hint": _maintenance_hint(
            len(executed), len(blocked), avg_conf, pnl_summary.get("total_realized_usd", 0)
        ),
    }


def _maintenance_hint(executed: int, blocked: int, avg_conf: float, total_pnl: float) -> str:
    """
    運用状態を診断し、メンテナンス推奨メッセージを返す内部ヘルパー。

    診断ルール（優先順）:
        1. 実行 0 件 かつ ブロック 5 件超
           → 最低信頼度が高すぎるか、イベント回避時間が長すぎる可能性
        2. 平均信頼度 60% 未満 かつ 実行あり
           → プリセットを「安定型」に変更して誤エントリーを減らす
        3. 実現損益マイナス かつ 実行 5 件以上
           → リスク% またはプリセットの見直しを促す
        4. 実行 10 件以上
           → 定期レビュー推奨メッセージ
        5. それ以外（開始前/ドライラン段階）
           → オンボーディング手順を案内

    Args:
        executed:  実行済みログ件数
        blocked:   ブロック件数
        avg_conf:  実行済みログの平均信頼度（0〜100）
        total_pnl: 実現損益合計（USD）

    Returns:
        ユーザー向けの日本語メンテナンスヒント文字列
    """
    if executed == 0 and blocked > 5:
        return "ブロックが多い — 最低信頼度を下げるか、イベント回避時間を短縮してください（週1回見直し推奨）。"
    if avg_conf < 60 and executed > 0:
        return "平均信頼度が低め — プリセットを「安定型」に変更することを検討してください。"
    if total_pnl < 0 and executed >= 5:
        return f"実現損益 ${total_pnl} — 週次レポートを確認し、リスク%またはプリセットの見直しを推奨します。"
    if executed >= 10:
        return "運用中 — 週1回、実現損益・シミュレーション結果と実行ログを確認してください。"
    return "ドライラン評価 → シミュレーション確認 → 有効化の順で開始してください。"
