"""
AI 売買シグナル生成モジュール（テクニカル + ML + OpenAI 統合）。

このモジュールは三層のシグナル分析を統合して最終的な売買シグナルを生成する:
  1. ルールベース: テクニカル指標からの買い/売りシグナルカウント
  2. ML ベース: 機械学習モデルによるトレンド予測
  3. AI ベース: OpenAI GPT による総合判断（APIキー設定時のみ）

三層の投票（votes）を集計し、多数決原理で composite_action を決定する。
OpenAI が利用可能な場合はその判断を最終的な action として採用し、信頼度も調整する。
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from src.ai.analyzer import make_trading_decision
from src.ai.client import resolve_openai_api_key
from src.analysis.multi_timeframe import analyze_multi_timeframe
from src.analysis.signals import signals_from_row
from src.ml.trend_predictor import predict_trend

# 型チェック時のみ MarketContext をインポートし、循環インポートを防止する
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
    """
    テクニカル・ML・OpenAI を統合した総合売買シグナルを生成する。

    呼び出し元が既に ctx/mtf/trend を持っている場合は再計算せず引数で受け取ることで、
    API の重複呼び出しとデータ再取得を防止する。

    投票メカニズム（votes）:
        - ルールベース: テクニカルシグナルの買い/売り多数がいずれかの票を投じる
        - ML トレンド予測: trend["trend"] が票を投じる
        - マルチタイムフレーム: mtf["alignment"] が bullish/bearish/neutral の場合のみ票を投じる
    最終的な composite_action は bull 票と bear 票の多数決で決定し、
    OpenAI の判断がある場合は OpenAI の action を採用する。

    Args:
        symbol: 通貨ペアのシンボル（例: "USDJPY"）
        days: テクニカル分析・ML に使用する過去データの日数（デフォルト 200）
        ctx: 事前計算済みの MarketContext（None の場合は内部で生成する）
        mtf: 事前計算済みのマルチタイムフレーム分析結果（None の場合は内部で生成する）
        trend: 事前計算済みのトレンド予測結果（None の場合は内部で生成する）

    Returns:
        dict: 以下のキーを含む総合シグナル辞書
            - symbol: 通貨ペア（大文字）
            - source: データソース識別子
            - price: 現在価格
            - action: 最終売買アクション（"buy" | "sell" | "hold"）
            - confidence: 信頼度（0-95%）
            - rule_signals: ルールベースの個別シグナルリスト
            - multi_timeframe: マルチタイムフレーム分析結果
            - trend_ml: ML トレンド予測（trend・label・confidence）
            - ai_decision: OpenAI の売買判断（利用不可時 None）
            - summary: 人間が読みやすい総合シグナルの要約テキスト
    """
    # MarketContext が渡されていない場合は同期処理をスレッドプールで実行する
    if ctx is None:
        from src.analysis.market_context import MarketContext

        # MarketContext.load は同期処理のため asyncio.to_thread で非同期化する
        ctx = await asyncio.to_thread(MarketContext.load, symbol, days)

    # 最新の指標値（DataFrame の最終行）を取得する
    latest = ctx.result_df.iloc[-1]
    price = float(latest["close"])
    # ルールベースのシグナル（RSI・MACD・BB 等に基づく個別シグナル）を生成する
    rule_signals = signals_from_row(latest)

    # マルチタイムフレーム分析が未計算の場合は実行する（キャッシュ活用で重複計算を防ぐ）
    if mtf is None:
        mtf = await asyncio.to_thread(analyze_multi_timeframe, symbol)
    # ML トレンド予測が未計算の場合は実行する
    if trend is None:
        trend = await asyncio.to_thread(
            predict_trend,
            symbol,
            days,
            # ctx から得たデータを再利用して重複する OHLCV 取得を避ける
            result_df=ctx.result_df,
            source=ctx.source,
            mtf=mtf,
        )

    # ルールベースシグナルの買い/売り票数をカウントする
    buy = sum(1 for s in rule_signals if s["signal"] == "buy")
    sell = sum(1 for s in rule_signals if s["signal"] == "sell")

    # 三層投票システムによる多数決: 各分析ソースがひとつの票を投じる
    votes: list[str] = []
    # 1票目: ルールベースシグナルの多数決（同数の場合は neutral）
    if buy > sell:
        votes.append("bullish")
    elif sell > buy:
        votes.append("bearish")
    else:
        votes.append("neutral")
    # 2票目: ML トレンド予測の方向性
    votes.append(trend["trend"])
    # 3票目: マルチタイムフレームの整合性（bullish/bearish/neutral の場合のみ有効票）
    if mtf.get("alignment") in ("bullish", "bearish", "neutral"):
        votes.append(mtf["alignment"])

    # 投票結果を集計して複合アクションを決定する
    bull = votes.count("bullish")
    bear = votes.count("bearish")
    if bull > bear:
        composite_action = "buy"
        # 信頼度 = 基礎値 50% + 強気票数 × 15%（最大 95% に制限）
        # 1票差=65%、2票差=80%、3票差=95% となるスケール
        confidence = min(95, 50 + bull * 15)
    elif bear > bull:
        composite_action = "sell"
        # 売りの場合も同じスケールで信頼度を計算する
        confidence = min(95, 50 + bear * 15)
    else:
        # 同数の場合は様子見とし、低めの信頼度 40% を設定する
        composite_action = "hold"
        confidence = 40

    # OpenAI による高精度な売買判断を試みる（APIキー設定時のみ）
    ai_decision = None
    if resolve_openai_api_key():
        try:
            ai_decision = await make_trading_decision(symbol, days)
            if ai_decision.get("action") in ("buy", "sell", "hold"):
                # OpenAI とルールベースの方向が一致、またはルールが様子見の場合は
                # OpenAI の信頼度（0-1スケール）をパーセントに変換して採用する
                if ai_decision["action"] == composite_action or composite_action == "hold":
                    confidence = max(confidence, int(ai_decision.get("confidence", 0) * 100))
                # OpenAI の判断を最終的なアクションとして採用する
                composite_action = ai_decision["action"]
        except Exception:
            # OpenAI 失敗時はルールベース+MLの複合判断をそのまま使用する（サイレントフォールバック）
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
        # ai_decision は OpenAI 利用不可時は None となる
        "ai_decision": ai_decision,
        # 人間が読みやすい日本語サマリーを生成する
        "summary": _signal_summary(composite_action, confidence, rule_signals, trend, mtf),
    }


def _signal_summary(action, confidence, rules, trend, mtf) -> str:
    """
    シグナル情報を人間が読みやすい日本語の要約文に変換する。

    UI 表示やアラート通知で使用するためのシンプルな一文要約を生成する。

    Args:
        action: 最終アクション（"buy" | "sell" | "hold"）
        confidence: 信頼度パーセンテージ（0-95）
        rules: ルールベースシグナルのリスト（各要素に signal キーが必要）
        trend: ML トレンド予測辞書（trend_label キーが必要）
        mtf: マルチタイムフレーム分析辞書（alignment_label キーが必要）

    Returns:
        str: 総合シグナルを日本語で表現した要約文
    """
    # action の英語表現を日本語に変換する
    action_ja = {"buy": "買い", "sell": "売り", "hold": "様子見"}.get(action, action)
    # ルールベースシグナルの買い/売り件数を再カウントして要約に含める
    buy = sum(1 for s in rules if s["signal"] == "buy")
    sell = sum(1 for s in rules if s["signal"] == "sell")
    return (
        f"総合シグナル: {action_ja}（信頼度 {confidence}%）。"
        f"テクニカル {buy}買い/{sell}売り、"
        f"トレンド予測 {trend['trend_label']}、"
        # MTF アライメントラベルが取得できない場合は "—" を表示する
        f"MTF {mtf.get('alignment_label', '—')}。"
    )
