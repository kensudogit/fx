"""FX ニュース収集（RSS + OpenAI 分析）"""

import logging
import xml.etree.ElementTree as ET
from datetime import datetime
from urllib.parse import quote

import httpx

from src.ai.client import chat_json

logger = logging.getLogger(__name__)

SYMBOL_NEWS_QUERIES = {
    "USDJPY": "USD JPY ドル円 forex",
    "EURUSD": "EUR USD ユーロドル forex",
    "GBPUSD": "GBP USD ポンドドル forex",
    "AUDUSD": "AUD USD 豪ドル forex",
}


async def fetch_rss_news(symbol: str, limit: int = 10) -> list[dict]:
    """Google News RSS からニュースを収集"""
    query = SYMBOL_NEWS_QUERIES.get(symbol.upper(), f"{symbol} forex")
    url = f"https://news.google.com/rss/search?q={quote(query)}&hl=ja&gl=JP&ceid=JP:ja"

    async with httpx.AsyncClient(timeout=20.0, follow_redirects=True) as client:
        response = await client.get(
            url,
            headers={"User-Agent": "Mozilla/5.0 (compatible; FXTool/1.0)"},
        )
        response.raise_for_status()

    root = ET.fromstring(response.text)
    items = []
    for item in root.findall(".//item")[:limit]:
        title = item.findtext("title", "")
        link = item.findtext("link", "")
        pub_date = item.findtext("pubDate", "")
        source = item.findtext("source", "")
        items.append(
            {
                "title": title,
                "url": link,
                "published_at": pub_date,
                "source": source,
            }
        )
    return items


async def analyze_news(symbol: str, limit: int = 8) -> dict:
    """ニュース収集 + OpenAI による要約・センチメント分析"""
    articles = await fetch_rss_news(symbol, limit)

    if not articles:
        return {
            "symbol": symbol,
            "articles": [],
            "summary": "ニュースを取得できませんでした。",
            "sentiment": "neutral",
            "sentiment_score": 0,
            "key_topics": [],
            "market_impact": "low",
        }

    headlines = "\n".join(f"- {a['title']} ({a['source']})" for a in articles)

    result = chat_json(
        system="""あなたはFXアナリストです。ニュースヘッドラインを分析し、JSONのみで回答してください。
出力形式:
{
  "summary": "市場への影響を3-5文で要約（日本語）",
  "sentiment": "bullish|bearish|neutral のいずれか",
  "sentiment_score": -100から100の整数（正=通貨ペアの基軸通貨強気）,
  "key_topics": ["トピック1", "トピック2"],
  "market_impact": "high|medium|low",
  "currency_outlook": {
    "base": "基軸通貨の見通し（1文）",
    "quote": "決済通貨の見通し（1文）"
  }
}""",
        user=f"通貨ペア: {symbol}\n\nヘッドライン:\n{headlines}",
    )

    return {
        "symbol": symbol,
        "collected_at": datetime.utcnow().isoformat(),
        "articles": articles,
        **result,
    }
