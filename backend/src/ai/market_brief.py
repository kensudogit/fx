"""
ニュース・SNS・経済指標の統合要約と市場影響分析モジュール。

このモジュールは三つの情報ソース（RSSニュース・SNS投稿・経済指標データ）を並行収集し、
OpenAI GPT を用いて市場への総合的な影響を分析した「マーケットブリーフ」を生成する。
OpenAI が利用不可な場合は ML 感情分析と経済指標バイアスを組み合わせた
フォールバックサマリーを自動生成する。
"""

import asyncio

from src.ai.client import chat_json, resolve_openai_api_key
from src.ai.news import fetch_rss_news
from src.analysis.economic import analyze_economic
from src.analysis.sns import analyze_sns
from src.ml.news_sentiment import analyze_headlines_ml


async def build_market_brief(symbol: str) -> dict:
    """
    ニュース・SNS・経済指標を統合した市場ブリーフを生成する。

    三つのデータソースを可能な限り並行取得し、OpenAI で市場影響を総合分析する。
    OpenAI が利用不可な場合は ML ベースの感情分析と経済指標バイアスを
    組み合わせたフォールバックサマリーを提供する。

    処理フロー:
        1. ニュース RSS とSNS投稿を並行取得する
        2. 経済指標データを取得する
        3. ニュースヘッドラインを ML で感情分析する
        4. OpenAI で三ソースを統合分析する（可能な場合）
        5. OpenAI 失敗時はフォールバックサマリーを生成する

    Args:
        symbol: 分析対象の通貨ペア（例: "USDJPY"）

    Returns:
        dict: 以下のキーを含む市場ブリーフ辞書
            - symbol: 通貨ペア（大文字）
            - news: ニュース記事リストと ML 感情分析結果
            - sns: SNS の要約・感情・エンゲージメント・投稿
            - economic: 経済バイアス・概要・主要指標・高影響アラート
            - openai: OpenAI による統合分析結果（利用不可時 None）
            - fallback_summary: フォールバック時の簡易サマリー（フォールバック時のみ）
            - openai_error: OpenAI エラー内容（エラー時のみ）
    """
    # ニュースと SNS は独立したデータソースのため並行タスクとして開始する
    news_task = fetch_rss_news(symbol, 10)
    sns_task = analyze_sns(symbol, 8)
    # 経済指標は await で取得してから他のタスクの完了を待つ
    economic = await analyze_economic(symbol)
    # 並行タスクの完了を待って結果を取得する
    articles = await news_task
    sns = await sns_task

    # ヘッドライン一覧を抽出し、ML 感情分析の入力として使用する
    headlines = [a["title"] for a in articles]
    # OpenAI に依存しない ML ベースのニュース感情分析を実行する（フォールバック用にも使用）
    news_ml = analyze_headlines_ml(headlines)

    # 各データソースを構造化してブリーフの骨格を組み立てる
    brief = {
        "symbol": symbol.upper(),
        "news": {
            # 表示用の記事は最大 8 件に制限してレスポンスサイズを抑制する
            "articles": articles[:8],
            "ml": news_ml,
        },
        "sns": {
            "summary": sns["summary"],
            "sentiment": sns["sentiment"],
            "engagement": sns["engagement"],
            # SNS 投稿も最大 5 件に絞ってレスポンスサイズを管理する
            "posts": sns["posts"][:5],
        },
        "economic": {
            "pair_bias": economic["pair_bias"],
            "pair_bias_label": economic["pair_bias_label"],
            "overview": economic["overview"],
            # 主要指標は上位 5 件のみ表示する（トークン節約と読みやすさのバランス）
            "indicators": economic["indicators"][:5],
            # 高影響度アラートは最大 3 件に絞る
            "alerts": economic["high_impact_alerts"][:3],
        },
        # OpenAI 分析結果の初期値は None（後で設定するか、失敗時は None のまま）
        "openai": None,
    }

    # OpenAI API キーが設定されている場合のみ AI 分析を実行する
    if resolve_openai_api_key():
        # OpenAI プロンプトへの入力テキストを整形する
        # 各ソースから最重要情報を絞り込みトークン数を最小化する
        headlines_text = "\n".join(f"- {h}" for h in headlines[:8])
        sns_text = "\n".join(f"- {p['title']}" for p in sns["posts"][:5])
        econ_text = "\n".join(
            f"- {i['name']}: {i['comment']} ({i['pair_direction']})"
            for i in economic["indicators"][:5]
        )
        try:
            # 三つのデータソースを統合して市場影響を分析させる
            ai = await asyncio.to_thread(
                chat_json,
                # FX アナリストとして三ソースを総合評価させるシステムプロンプト
                """FXアナリストとして、ニュース・SNS・経済指標を統合し市場影響を分析。JSONのみ:
{
  "executive_summary": "3-5文の要約（日本語）",
  "market_impact": "high|medium|low",
  "impact_direction": "bullish|bearish|neutral",
  "key_drivers": ["要因1", "要因2"],
  "risks": ["リスク1"],
  "trading_implication": "トレードへの示唆（2-3文）",
  "confidence": 0-100
}""",
                # 三ソースのデータを明確にセクション分けして渡す
                f"通貨ペア: {symbol}\n\n【ニュース】\n{headlines_text}\n\n【SNS】\n{sns_text}\n\n【経済指標】\n{econ_text}",
            )
            brief["openai"] = ai
        except Exception as e:
            # OpenAI 失敗時はエラー内容を記録し、フォールバックサマリーに移行する
            brief["openai_error"] = str(e)

    # OpenAI の結果が得られなかった場合（未設定またはエラー）はフォールバックサマリーを生成する
    if not brief.get("openai"):
        # ML 感情分析・SNS 感情・経済バイアスを単純に組み合わせた簡易サマリー
        impact = news_ml["sentiment"]
        brief["fallback_summary"] = {
            # 各ソースの感情/バイアスをコンパクトに一文でまとめる
            "executive_summary": (
                f"{symbol}: ニュースML={impact}、SNS={sns['sentiment']['sentiment']}、"
                f"経済={economic['pair_bias_label']}。"
            ),
            # フォールバックでは中程度の影響度をデフォルトとする
            "market_impact": "medium",
            # 経済指標のバイアスを市場の方向性として使用する
            "impact_direction": economic["pair_bias"],
        }

    return brief
