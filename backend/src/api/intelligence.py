"""5大分析の統合 BFF"""

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
    key = cache_key("intel", symbol, days=days)
    standalone = trend is None and volatility is None
    if standalone:
        cached = cache_get(key)
        if cached is not None:
            return cached

    if trend is None:
        trend = await asyncio.to_thread(predict_trend, symbol, days)
    if volatility is None:
        volatility = await asyncio.to_thread(
            predict_volatility,
            symbol,
            days,
            result_df=None,
        )

    economic = await analyze_economic(symbol)
    sns = await analyze_sns(symbol, 10)

    articles = await fetch_rss_news(symbol, 8)
    headlines = [a["title"] for a in articles]
    news_ml = analyze_headlines_ml(headlines)

    news_openai = None
    news_error = None
    if resolve_openai_api_key():
        try:
            ai = await analyze_news(symbol, 8)
            news_openai = {
                "summary": ai.get("summary"),
                "sentiment": ai.get("sentiment"),
                "sentiment_score": ai.get("sentiment_score"),
                "market_impact": ai.get("market_impact"),
            }
        except Exception as e:
            news_error = str(e)

    # 総合スコア（-100〜100）
    score_map = {"bullish": 1, "bearish": -1, "neutral": 0}
    components = [
        score_map.get(trend["trend"], 0) * 30,
        score_map.get(news_ml["sentiment"], 0) * 20,
        score_map.get(sns["sentiment"]["sentiment"], 0) * 15,
        score_map.get(economic["pair_bias"], 0) * 25,
        {"expanding": -5, "contracting": 5, "stable": 0}.get(
            volatility["forecast"]["vol_trend"], 0
        ),
    ]
    composite = max(-100, min(100, sum(components)))

    if composite > 25:
        outlook = "bullish"
        outlook_label = "総合見通し: 強気"
    elif composite < -25:
        outlook = "bearish"
        outlook_label = "総合見通し: 弱気"
    else:
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
            "openai": news_openai,
            "openai_error": news_error,
        },
        "sns": sns,
        "economic": economic,
        "volatility": volatility,
    }
    if standalone:
        cache_put(key, result, ttl_seconds=settings.analysis_cache_ttl_seconds)
    return result
