"""
売買履歴ベースの AI コーチングモジュール。

このモジュールはユーザーの実際の取引履歴（注文データ）を分析し、
OpenAI GPT を用いてトレードの強み・弱点・改善策を提示する。
OpenAI が利用不可な場合はルールベースのフォールバックコーチングを提供する。
"""

import asyncio
from collections import Counter

from src.ai.client import chat_json, resolve_openai_api_key
from src.broker.oanda import list_orders


def _order_stats(orders: list[dict]) -> dict:
    """
    注文リストから統計情報を集計する。

    取引数・売買方向の偏り・通貨ペア別の取引数・約定済み注文を集計し、
    AI コーチング分析および UI 表示のためのサマリーデータを生成する。

    Args:
        orders: 注文情報の辞書リスト（各要素に side・symbol・status キーが必要）

    Returns:
        dict: 以下のキーを含む統計辞書
            - total: 総注文数
            - filled: 約定済み注文数（status == "FILLED"）
            - buy_count: 買い注文の総数
            - sell_count: 売り注文の総数
            - symbols_traded: 通貨ペア別の取引回数辞書
            - recent: 最新 10 件の注文リスト
            または取引履歴が空の場合:
            - total: 0
            - message: "取引履歴がありません"
    """
    # 取引履歴が空の場合は分析不要のため早期リターンする
    if not orders:
        return {"total": 0, "message": "取引履歴がありません"}
    # Counter で売買方向と通貨ペアの集計を一度に行う（O(n) の効率的な処理）
    by_side = Counter(o["side"] for o in orders)
    by_symbol = Counter(o["symbol"] for o in orders)
    # 約定済み（FILLED）注文のみを抽出してトレードパフォーマンスの分析対象とする
    filled = [o for o in orders if o.get("status") == "FILLED"]
    return {
        "total": len(orders),
        "filled": len(filled),
        "buy_count": by_side.get("buy", 0),
        "sell_count": by_side.get("sell", 0),
        "symbols_traded": dict(by_symbol),
        # 最新 10 件を AI への入力テキスト生成に使用する（トークン節約のため上限を設ける）
        "recent": orders[:10],
    }


async def generate_coaching(symbol: str, tenant_id: int | None = None, limit: int = 30) -> dict:
    """
    取引履歴を分析して AI コーチングアドバイスを生成する。

    指定通貨ペアの注文履歴を取得し、OpenAI で強み・弱点・改善策を分析する。
    OpenAI が利用不可な場合はルールベースのフォールバックコーチングを提供する。

    Args:
        symbol: 分析対象の通貨ペア（例: "USDJPY"）
        tenant_id: テナント ID（マルチテナント環境でのデータ分離用、None は全テナント）
        limit: 取得する注文の最大件数（デフォルト 30）

    Returns:
        dict: 以下のキーを含むコーチング結果辞書
            - symbol: 分析対象通貨ペア
            - trade_stats: 取引統計サマリー
            - coaching: AI またはルールベースのコーチング内容
                - overall_assessment: 総合評価テキスト
                - strengths: 強みのリスト
                - weaknesses: 改善点のリスト
                - behavioral_patterns: 行動パターンのリスト
                - recommendations: 具体的なアドバイスのリスト
                - next_focus: 次に集中すべきこと
                - risk_discipline_score: リスク管理規律スコア（0-100）
            - coaching_error: AI 分析失敗時のエラーメッセージ（フォールバック時のみ）
    """
    # 指定テナントの最新 limit 件の注文を取得する
    orders = list_orders(limit, tenant_id)
    # 指定通貨ペアの注文のみに絞り込む（ない場合は全注文で分析する）
    symbol_orders = [o for o in orders if o["symbol"] == symbol.upper()]
    # symbol_orders が空の場合は全注文データでコーチングする（データ不足を補う）
    stats = _order_stats(symbol_orders or orders)

    result = {
        "symbol": symbol.upper(),
        "trade_stats": stats,
        "coaching": None,
    }

    # OpenAI API キーが未設定の場合はルールベースフォールバックを使用する
    if not resolve_openai_api_key():
        result["coaching"] = _rule_coaching(stats)
        return result

    # 最新 10 件の取引履歴を読みやすいテキスト形式に変換する
    # （OpenAI のトークン効率を考慮してシンプルな 1 行形式を採用）
    history_text = "\n".join(
        f"- {o.get('created_at', '')[:10]} {o['symbol']} {o['side']} "
        f"{o['units']}units @ {o.get('fill_price', '—')} ({o['status']})"
        for o in stats.get("recent", [])
    ) or "（履歴なし）"

    try:
        # OpenAI の同期呼び出しを asyncio スレッドプールで非同期化する
        ai = await asyncio.to_thread(
            chat_json,
            # FX コーチとして取引履歴から行動パターンを分析させる
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
            # 統計サマリーと生の取引履歴テキストを両方渡して精度を高める
            f"通貨ペア: {symbol}\n統計: {stats}\n\n直近取引:\n{history_text}",
        )
        result["coaching"] = ai
    except Exception as e:
        # AI 分析失敗時はルールベースにフォールバックしサービスを継続する
        result["coaching"] = _rule_coaching(stats)
        # エラー内容を返してフロントエンドが原因を把握できるようにする
        result["coaching_error"] = str(e)

    return result


def _rule_coaching(stats: dict) -> dict:
    """
    OpenAI 失敗時または API キー未設定時のルールベースコーチングを生成する。

    取引統計から単純なルール（売買偏向の検出・基本的なリスク管理アドバイス）を
    適用して、API に依存しない最低限のコーチングを常に提供できるようにする。

    Args:
        stats: `_order_stats` が返す取引統計辞書

    Returns:
        dict: 以下のキーを含むルールベースコーチング辞書
            - overall_assessment: 総合評価テキスト
            - recommendations: 改善アドバイスのリスト
            - next_focus: 次に集中すべき課題
            - risk_discipline_score: ルールベースの固定リスクスコア
    """
    # 取引履歴がゼロの場合は初心者向けの基本アドバイスを返す
    if stats.get("total", 0) == 0:
        return {
            "overall_assessment": "まだ取引履歴がありません。ペーパー取引で記録を蓄積しましょう。",
            "recommendations": ["小ロットでエントリーし、損切りルールを先に決める"],
            "next_focus": "最初の10トレードは利益よりルール遵守を優先",
            # 履歴なしのため中立的なスコア 50 を設定する
            "risk_discipline_score": 50,
        }
    buy = stats.get("buy_count", 0)
    sell = stats.get("sell_count", 0)
    # 一方の取引数が 1.5 倍以上の場合に偏向ありと判定する
    # （例: buy=15, sell=8 → 15 > 8*1.5=12 → 買い偏重）
    bias = "買い偏重" if buy > sell * 1.5 else ("売り偏重" if sell > buy * 1.5 else "バランス型")
    return {
        "overall_assessment": f"取引{stats['total']}件。{bias}の傾向があります。",
        "recommendations": [
            # リスク管理の基本三原則を常にアドバイスとして含める
            "1トレードのリスクを口座の1-2%に制限",
            "エントリー前に必ず損切り価格を設定",
            "同方向への連続エントリーを避ける",
        ],
        "next_focus": "勝率よりリスクリワード比の改善",
        # ルールベースのデフォルトスコア: ある程度の取引履歴があるため 60 を設定する
        "risk_discipline_score": 60,
    }
