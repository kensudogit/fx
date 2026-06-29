"""SNS 分析（Reddit / Google News RSS フォールバック + センチメント）"""

import logging
from datetime import datetime, timezone

import httpx

from src.config import settings
from src.infra.analysis_cache import cache_get, cache_key, cache_put
from src.ml.news_sentiment import analyze_headlines_ml

logger = logging.getLogger(__name__)

SYMBOL_REDDIT_QUERIES = {
    "USDJPY": "USDJPY OR dollar yen",
    "EURUSD": "EURUSD OR euro dollar",
    "GBPUSD": "GBPUSD OR pound dollar",
    "AUDUSD": "AUDUSD OR aussie dollar",
}

FALLBACK_SNS = {
    "USDJPY": [
        {"title": "Dollar/yen watching BOJ policy closely", "subreddit": "forex", "score": 42},
        {"title": "USDJPY breakout above 150?", "subreddit": "Forexstrategy", "score": 18},
    ],
    "EURUSD": [
        {"title": "ECB vs Fed — EURUSD range trade", "subreddit": "forex", "score": 35},
    ],
    "GBPUSD": [
        {"title": "Cable volatility ahead of UK data", "subreddit": "forex", "score": 28},
    ],
    "AUDUSD": [
        {"title": "AUDUSD tied to China PMI expectations", "subreddit": "forex", "score": 22},
    ],
}


async def _fetch_rss_as_posts(symbol: str, limit: int) -> list[dict]:
    """Reddit 失敗時に Google News RSS ヘッドラインを SNS 投稿形式で返す"""
    from src.ai.news import fetch_rss_news

    try:
        articles = await fetch_rss_news(symbol, limit)
        if not articles:
            return []
        return [
            {
                "title": a.get("title", ""),
                "url": a.get("link", ""),
                "subreddit": "google_news",
                "score": 0,
                "num_comments": 0,
                "published_at": a.get("published", datetime.now(timezone.utc).isoformat()),
                "source": "google_news",
            }
            for a in articles
            if a.get("title")
        ]
    except Exception as e:
        logger.warning("RSS SNS fallback failed for %s: %s", symbol, e)
        return []


async def fetch_reddit_posts(symbol: str, limit: int = 10) -> list[dict]:
    """Reddit 公開 JSON API から投稿を取得（失敗時 RSS → サンプル）"""
    query = SYMBOL_REDDIT_QUERIES.get(symbol.upper(), f"{symbol} forex")
    url = "https://www.reddit.com/r/forex/search.json"
    params = {"q": query, "sort": "new", "limit": min(limit, 25), "restrict_sr": "on"}

    try:
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
            res = await client.get(
                url,
                params=params,
                headers={"User-Agent": "FXTool/1.0 (market analysis bot)"},
            )
            res.raise_for_status()
            data = res.json()

        posts = []
        for child in data.get("data", {}).get("children", [])[:limit]:
            p = child.get("data", {})
            title = p.get("title", "")
            if not title:
                continue
            posts.append({
                "title": title,
                "url": f"https://reddit.com{p.get('permalink', '')}",
                "subreddit": p.get("subreddit", "forex"),
                "score": p.get("score", 0),
                "num_comments": p.get("num_comments", 0),
                "published_at": datetime.fromtimestamp(
                    p.get("created_utc", 0), tz=timezone.utc
                ).isoformat(),
                "source": "reddit",
            })
        if posts:
            return posts
    except Exception as e:
        logger.warning("Reddit fetch failed for %s: %s", symbol, e)

    rss_posts = await _fetch_rss_as_posts(symbol, limit)
    if rss_posts:
        return rss_posts

    fallback = FALLBACK_SNS.get(
        symbol.upper(),
        [{"title": f"{symbol} forex discussion", "subreddit": "forex", "score": 10}],
    )
    return [
        {
            **p,
            "url": "",
            "num_comments": 0,
            "published_at": datetime.now(timezone.utc).isoformat(),
            "source": "sample",
        }
        for p in fallback
    ]


async def analyze_sns(symbol: str, limit: int = 10) -> dict:
    key = cache_key("sns", symbol, limit=limit)
    cached = cache_get(key)
    if cached is not None:
        return cached

    posts = await fetch_reddit_posts(symbol, limit)
    headlines = [p["title"] for p in posts]
    sentiment = analyze_headlines_ml(headlines)

    total_score = sum(p.get("score", 0) for p in posts)
    total_comments = sum(p.get("num_comments", 0) for p in posts)
    engagement = "high" if total_score > 100 or total_comments > 50 else (
        "medium" if total_score > 30 else "low"
    )

    sub_counts: dict[str, int] = {}
    for p in posts:
        sub = p.get("subreddit", "unknown")
        sub_counts[sub] = sub_counts.get(sub, 0) + 1

    primary_source = posts[0]["source"] if posts else "sample"
    platform_labels = {
        "reddit": "Reddit",
        "google_news": "Google News（Reddit 代替）",
        "sample": "サンプルデータ",
    }

    result = {
        "symbol": symbol.upper(),
        "collected_at": datetime.now(timezone.utc).isoformat(),
        "platform": primary_source,
        "platform_label": platform_labels.get(primary_source, primary_source),
        "post_count": len(posts),
        "posts": posts,
        "sentiment": sentiment,
        "engagement": engagement,
        "total_score": total_score,
        "total_comments": total_comments,
        "subreddits": sub_counts,
        "summary": (
            f"{platform_labels.get(primary_source, primary_source)} {len(posts)}件 — "
            f"センチメント: {sentiment['sentiment']} "
            f"({sentiment['sentiment_score']}) / エンゲージメント: {engagement}"
        ),
    }
    cache_put(key, result, ttl_seconds=settings.sns_cache_ttl_seconds)
    return result
