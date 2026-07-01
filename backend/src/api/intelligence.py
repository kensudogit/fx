"""
5大分析の統合 BFF（バックエンドフォーフロントエンド）モジュール

このモジュールは、FX トレーディングにおける 5 つの主要分析を統合した
インテリジェンス（総合分析）データを構築する `build_intelligence` 関数を提供する。

統合する 5 大分析:
  1. トレンド予測（ML モデルによる方向予測）
  2. ニュース分析（RSS + ML センチメント + OpenAI GPT 解析）
  3. SNS センチメント（ソーシャルメディアの市場心理）
  4. 経済指標分析（主要経済指標・金利政策の影響評価）
  5. ボラティリティ予測（ML モデルによる変動率予測）

これらの分析結果を統合した複合スコア（-100〜100）と総合見通し（bullish/bearish/neutral）
を計算して返す。

設計方針:
  - キャッシュ: スタンドアロン呼び出し（trend・volatility が未指定）の場合のみキャッシュを使用
    し、TTL 内であれば同一パラメータのリクエストに対して計算を省略する
  - 外部依存の分離: trend・volatility を引数で受け取ることで、呼び出し元が
    事前計算済みの値を渡せる設計（キャッシュヒット率の向上と不要な再計算の防止）
  - OpenAI フォールバック: OpenAI API キーが未設定の場合は GPT 分析をスキップし、
    ML ベースの分析のみで結果を返す（サービス継続性の確保）
"""

import asyncio

from src.ai.client import resolve_openai_api_key
from src.ai.news import analyze_news, fetch_rss_news
from src.analysis.economic import analyze_economic
from src.analysis.sns import analyze_sns
from src.config import settings
from src.infra.analysis_cache import cache_get, cache_key, cache_put
from src.ml.news_sentiment import analyze_headlines_ml
from src.ml.trend_predictor import predict_trend
from src.ml.volatility_predictor import predict_volatility


async def build_intelligence(
    symbol: str,
    days: int = 200,
    *,
    trend: dict | None = None,
    volatility: dict | None = None,
) -> dict:
    """
    5大分析を統合したインテリジェンス（総合市場分析）データを構築して返す。

    トレンド・ニュース・SNS・経済指標・ボラティリティの 5 種類の分析を
    並列または順次実行し、各結果を統合した複合スコアと総合見通しを計算する。

    キャッシュ設計:
        trend と volatility が両方 None（スタンドアロン呼び出し）の場合のみキャッシュを参照・保存する。
        キャッシュ TTL は settings.analysis_cache_ttl_seconds で設定する。
        呼び出し元が trend または volatility を渡す場合（他のエンドポイントとの共有実行）は
        キャッシュをスキップして常に最新データを計算する。

    複合スコア計算:
        各分析の結果を重み付けして合算する（合計重みは最大 100）:
            - トレンド予測: ±30 点（最大の重みを持つ）
            - 経済指標: ±25 点
            - ニュース ML センチメント: ±20 点
            - SNS センチメント: ±15 点
            - ボラティリティトレンド: ±5 点（拡大=リスク増でマイナス）
        合計が +25 超 → bullish、-25 未満 → bearish、それ以外 → neutral

    Args:
        symbol (str): 通貨ペア（例: "USDJPY"）
        days (int): 分析対象の過去日数（デフォルト: 200）
        trend (dict | None): 事前計算済みのトレンド予測結果（None の場合は内部で計算）
        volatility (dict | None): 事前計算済みのボラティリティ予測結果（None の場合は内部で計算）

    Returns:
        dict: インテリジェンス分析結果。以下のキーを含む:
            - symbol (str): 大文字の通貨ペア
            - composite_score (int): 複合スコア（-100〜100）
            - outlook (str): 総合見通し（"bullish" / "bearish" / "neutral"）
            - outlook_label (str): 総合見通しの日本語ラベル
            - trend (dict): ML トレンド予測結果
            - news (dict): ニュース分析結果（articles / ml / openai / openai_error）
            - sns (dict): SNS センチメント分析結果
            - economic (dict): 経済指標分析結果
            - volatility (dict): ボラティリティ予測結果
    """
    # キャッシュキーを生成（symbol + days の組み合わせでユニークな識別子を作成）
    key = cache_key("intel", symbol, days=days)
    # trend・volatility が両方 None の場合はスタンドアロン呼び出しとしてキャッシュを使用する
    standalone = trend is None and volatility is None
    if standalone:
        # キャッシュにヒットした場合は即座に返却してバックエンド処理を省略する
        # （重い ML 推論・API 呼び出しをスキップできるため、レイテンシと API コストを削減）
        cached = cache_get(key)
        if cached is not None:
            return cached

    if trend is None:
        # トレンド予測は CPU バウンドの同期関数のため、asyncio.to_thread でスレッドプールに委託
        # これにより FastAPI のイベントループをブロックせずに実行できる
        trend = await asyncio.to_thread(predict_trend, symbol, days)
    if volatility is None:
        # ボラティリティ予測も同様に CPU バウンドのためスレッドプールで実行
        volatility = await asyncio.to_thread(
            predict_volatility,
            symbol,
            days,
            result_df=None,
        )

    # 経済指標分析（GDP・金利・CPI など主要経済データを非同期で取得・分析）
    economic = await analyze_economic(symbol)
    # SNS センチメント分析（最新 10 件の投稿を分析）
    sns = await analyze_sns(symbol, 10)

    # RSS フィードから最新ニュース記事を最大 8 件取得
    articles = await fetch_rss_news(symbol, 8)
    # タイトルのみ抽出して ML センチメント分析の入力とする（本文は重いため使わない）
    headlines = [a["title"] for a in articles]
    # ML モデルによるヘッドラインセンチメント分析
    news_ml = analyze_headlines_ml(headlines)

    # OpenAI GPT によるニュース分析（APIキーが設定されている場合のみ実行）
    news_openai = None
    news_error = None
    if resolve_openai_api_key():
        try:
            # GPT を使用した高品質なニュース分析（API 呼び出しが失敗してもサービスは継続）
            ai = await analyze_news(symbol, 8)
            news_openai = {
                "summary": ai.get("summary"),
                "sentiment": ai.get("sentiment"),
                "sentiment_score": ai.get("sentiment_score"),
                "market_impact": ai.get("market_impact"),
            }
        except Exception as e:
            # OpenAI API エラーはログに記録するが、ML 分析で代替するためサービスは継続する
            news_error = str(e)

    # 総合スコア（-100〜100）
    # 各分析の方向性をスコアに変換して重み付き合算する
    score_map = {"bullish": 1, "bearish": -1, "neutral": 0}
    components = [
        score_map.get(trend["trend"], 0) * 30,                           # トレンド: 最大±30点
        score_map.get(news_ml["sentiment"], 0) * 20,                     # ニュース ML: 最大±20点
        score_map.get(sns["sentiment"]["sentiment"], 0) * 15,             # SNS: 最大±15点
        score_map.get(economic["pair_bias"], 0) * 25,                    # 経済指標: 最大±25点
        {"expanding": -5, "contracting": 5, "stable": 0}.get(           # ボラティリティ: 最大±5点
            volatility["forecast"]["vol_trend"], 0                       # 拡大=リスク増でマイナス
        ),
    ]
    # 各成分を合算し、-100〜100 の範囲にクランプ（上限・下限を制限）
    composite = max(-100, min(100, sum(components)))

    # 複合スコアを閾値で判定して総合見通しを決定
    if composite > 25:
        # スコアが +25 超: 強気見通し
        outlook = "bullish"
        outlook_label = "総合見通し: 強気"
    elif composite < -25:
        # スコアが -25 未満: 弱気見通し
        outlook = "bearish"
        outlook_label = "総合見通し: 弱気"
    else:
        # スコアが -25〜+25: 中立見通し（方向性が不明確）
        outlook = "neutral"
        outlook_label = "総合見通し: 中立"

    result = {
        "symbol": symbol.upper(),
        "composite_score": composite,
        "outlook": outlook,
        "outlook_label": outlook_label,
        "trend": trend,
        "news": {
            "articles": articles,
            "ml": news_ml,
            "openai": news_openai,          # OpenAI API が未設定またはエラーの場合は None
            "openai_error": news_error,      # エラーメッセージ（正常時は None）
        },
        "sns": sns,
        "economic": economic,
        "volatility": volatility,
    }
    if standalone:
        # スタンドアロン呼び出しの場合のみキャッシュに保存（TTL は設定値に従う）
        # これにより同じシンボル・日数での連続リクエストを高速に処理できる
        cache_put(key, result, ttl_seconds=settings.analysis_cache_ttl_seconds)
    return result
