"""FX ニュース収集（RSS + OpenAI 分析）"""

import logging
import xml.etree.ElementTree as ET
from datetime import datetime
from urllib.parse import quote

import httpx

from src.ai.client import chat_json

logger = logging.getLogger(__name__)

SYMBOL_NEWS_QUERIES = {
    "USDJPY": "USD JPY forex",
    "EURUSD": "EUR USD forex",
    "GBPUSD": "GBP USD forex",
    "AUDUSD": "AUD USD forex",
}

FALLBACK_HEADLINES = {
    "USDJPY": [
        "米国金利動向がドル円相場を左右",
        "日銀金融政策への注目が高まる",
        "米経済指標発表を控えドル円は様子見",
    ],
    "EURUSD": [
        "欧州中央銀行の政策がユーロに影響",
        "米欧金利差がユーロドルに波及",
    ],
    "GBPUSD": [
        "英国経済指標にポンドが反応",
        "米国金利とポンドの動きに注目",
    ],
    "AUDUSD": [
        "中国経済指標が豪ドルに影響",
        "商品価格動向が豪ドル相場を左右",
    ],
}


def _fallback_articles(symbol: str) -> list[dict]:
    headlines = FALLBACK_HEADLINES.get(symbol.upper(), [f"{symbol} 為替市場の動向"])
    return [
        {
            "title": title,
            "url": "",
            "published_at": datetime.utcnow().isoformat(),
            "source": "FX Tool",
        }
        for title in headlines
    ]


async def fetch_rss_news(symbol: str, limit: int = 10) -> list[dict]:
    """Google News RSS からニュースを収集（失敗時はフォールバック）"""
    query = SYMBOL_NEWS_QUERIES.get(symbol.upper(), f"{symbol} forex")
    url = f"https://news.google.com/rss/search?q={quote(query)}&hl=en-US&gl=US&ceid=US:en"

    try:
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
            response = await client.get(
                url,
                headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                    "Accept": "application/rss+xml, application/xml, text/xml",
                },
            )
            response.raise_for_status()

        root = ET.fromstring(response.content)
        items = []
        for item in root.findall(".//item")[:limit]:
            title = item.findtext("title", "")
            if not title:
                continue
            items.append(
                {
                    "title": title,
                    "url": item.findtext("link", ""),
                    "published_at": item.findtext("pubDate", ""),
                    "source": item.findtext("source", "Google News"),
                }
            )
        if items:
            return items
    except Exception as e:
        logger.warning("RSS fetch failed for %s: %s", symbol, e)

    return _fallback_articles(symbol)


async def analyze_news(symbol: str, limit: int = 8) -> dict:
    """ニュース収集 + OpenAI による要約・センチメント分析"""
    articles = await fetch_rss_news(symbol, limit)
    headlines = "\n".join(f"- {a['title']} ({a['source']})" for a in articles)

    result = await asyncio.to_thread(
        chat_json,
        """あなたはFXアナリストです。ニュースヘッドラインを分析し、JSONのみで回答してください。
出力形式:
{
  "summary": "市場への影響を3-5文で要約（日本語）",
  "sentiment": "bullish|bearish|neutral のいずれか",
  "sentiment_score": -100から100の整数,
  "key_topics": ["トピック1", "トピック2"],
  "market_impact": "high|medium|low",
  "currency_outlook": {
    "base": "基軸通貨の見通し（1文）",
    "quote": "決済通貨の見通し（1文）"
  }
}""",
        f"通貨ペア: {symbol}\n\nヘッドライン:\n{headlines}",
    )

    return {
        "symbol": symbol,
        "collected_at": datetime.utcnow().isoformat(),
        "articles": articles,
        **result,
    }
