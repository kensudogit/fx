"""ニュース・SNS・経済指標の統合要約と市場影響分析"""

import asyncio

from src.ai.client import chat_json, resolve_openai_api_key
from src.ai.news import fetch_rss_news
from src.analysis.economic import analyze_economic
from src.analysis.sns import analyze_sns
from src.ml.news_sentiment import analyze_headlines_ml


async def build_market_brief(symbol: str) -> dict:
    news_task = fetch_rss_news(symbol, 10)
    sns_task = analyze_sns(symbol, 8)
    economic = await analyze_economic(symbol)
    articles = await news_task
    sns = await sns_task

    headlines = [a["title"] for a in articles]
    news_ml = analyze_headlines_ml(headlines)

    brief = {
        "symbol": symbol.upper(),
        "news": {
            "articles": articles[:8],
            "ml": news_ml,
        },
        "sns": {
            "summary": sns["summary"],
            "sentiment": sns["sentiment"],
            "engagement": sns["engagement"],
            "posts": sns["posts"][:5],
        },
        "economic": {
            "pair_bias": economic["pair_bias"],
            "pair_bias_label": economic["pair_bias_label"],
            "overview": economic["overview"],
            "indicators": economic["indicators"][:5],
            "alerts": economic["high_impact_alerts"][:3],
        },
        "openai": None,
    }

    if resolve_openai_api_key():
        headlines_text = "\n".join(f"- {h}" for h in headlines[:8])
        sns_text = "\n".join(f"- {p['title']}" for p in sns["posts"][:5])
        econ_text = "\n".join(
            f"- {i['name']}: {i['comment']} ({i['pair_direction']})"
            for i in economic["indicators"][:5]
        )
        try:
            ai = await asyncio.to_thread(
                chat_json,
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
                f"通貨ペア: {symbol}\n\n【ニュース】\n{headlines_text}\n\n【SNS】\n{sns_text}\n\n【経済指標】\n{econ_text}",
            )
            brief["openai"] = ai
        except Exception as e:
            brief["openai_error"] = str(e)

    if not brief.get("openai"):
        impact = news_ml["sentiment"]
        brief["fallback_summary"] = {
            "executive_summary": (
                f"{symbol}: ニュースML={impact}、SNS={sns['sentiment']['sentiment']}、"
                f"経済={economic['pair_bias_label']}。"
            ),
            "market_impact": "medium",
            "impact_direction": economic["pair_bias"],
        }

    return brief
