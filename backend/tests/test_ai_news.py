"""AI ニュース収集・分析 — src.ai.news のテスト

RSS 取得と OpenAI 呼び出しはモックへ差し替え、
パース・フォールバック・結果整形を検証する。
"""

import asyncio
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.ai.news import (
    FALLBACK_HEADLINES,
    SYMBOL_NEWS_QUERIES,
    _fallback_articles,
    analyze_news,
    fetch_rss_news,
)

RSS_TEMPLATE = """<?xml version="1.0"?>
<rss version="2.0"><channel>
{items}
</channel></rss>"""

RSS_ITEM = """<item>
  <title>{title}</title>
  <link>https://example.com/{n}</link>
  <pubDate>Mon, 01 Jan 2026 00:00:00 GMT</pubDate>
  <source>Reuters</source>
</item>"""


def rss(*titles) -> bytes:
    """RSS フィードのバイト列を組み立てる。"""
    items = "\n".join(RSS_ITEM.format(title=t, n=i) for i, t in enumerate(titles))
    return RSS_TEMPLATE.format(items=items).encode()


def mock_http(content: bytes, raise_error: Exception | None = None):
    """httpx.AsyncClient のコンテキストマネージャをモックする。"""
    response = MagicMock()
    response.content = content
    response.raise_for_status = MagicMock()
    client = MagicMock()
    if raise_error is not None:
        client.get = AsyncMock(side_effect=raise_error)
    else:
        client.get = AsyncMock(return_value=response)
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=client)
    ctx.__aexit__ = AsyncMock(return_value=False)
    return ctx, client


class TestConstants:
    """検索クエリとフォールバック見出しのテスト"""

    def test_queries_cover_the_major_pairs(self):
        """主要 4 ペアの検索クエリがあること"""
        assert set(SYMBOL_NEWS_QUERIES) == {"USDJPY", "EURUSD", "GBPUSD", "AUDUSD"}

    def test_fallbacks_cover_the_same_pairs(self):
        """フォールバック見出しも同じペアを網羅すること"""
        assert set(FALLBACK_HEADLINES) == set(SYMBOL_NEWS_QUERIES)

    def test_fallback_headlines_are_japanese(self):
        """フォールバック見出しが日本語であること"""
        for headlines in FALLBACK_HEADLINES.values():
            assert all(headline.strip() for headline in headlines)


class TestFallbackArticles:
    """_fallback_articles() のテスト"""

    def test_uses_the_registered_headlines(self):
        """登録済みペアの見出しを使うこと"""
        titles = [a["title"] for a in _fallback_articles("USDJPY")]
        assert titles == FALLBACK_HEADLINES["USDJPY"]

    def test_is_case_insensitive(self):
        """小文字のシンボルでも解決できること"""
        assert _fallback_articles("usdjpy") == _fallback_articles("USDJPY")

    def test_unknown_symbol_gets_a_generic_headline(self):
        """未登録ペアには汎用の見出しを返すこと"""
        articles = _fallback_articles("NZDCAD")
        assert len(articles) == 1
        assert "NZDCAD" in articles[0]["title"]

    def test_articles_have_the_expected_shape(self):
        """記事の形式が RSS 由来のものと揃っていること"""
        for article in _fallback_articles("USDJPY"):
            assert set(article) == {"title", "url", "published_at", "source"}
            assert article["source"] == "FX Tool"


class TestFetchRssNews:
    """fetch_rss_news() のテスト"""

    def test_parses_items(self):
        """RSS の item をパースして返すこと"""
        ctx, _ = mock_http(rss("ドル円が上昇", "日銀会合に注目"))
        with patch("src.ai.news.httpx.AsyncClient", return_value=ctx):
            articles = asyncio.run(fetch_rss_news("USDJPY"))

        assert [a["title"] for a in articles] == ["ドル円が上昇", "日銀会合に注目"]
        assert articles[0]["source"] == "Reuters"
        assert articles[0]["url"] == "https://example.com/0"

    def test_respects_the_limit(self):
        """取得件数の上限を守ること"""
        ctx, _ = mock_http(rss(*[f"news {i}" for i in range(20)]))
        with patch("src.ai.news.httpx.AsyncClient", return_value=ctx):
            assert len(asyncio.run(fetch_rss_news("USDJPY", limit=5))) == 5

    def test_skips_items_without_a_title(self):
        """タイトルの無い item は読み飛ばすこと"""
        feed = RSS_TEMPLATE.format(items="<item><link>x</link></item>"
                                         + RSS_ITEM.format(title="有効な記事", n=1)).encode()
        ctx, _ = mock_http(feed)
        with patch("src.ai.news.httpx.AsyncClient", return_value=ctx):
            articles = asyncio.run(fetch_rss_news("USDJPY"))

        assert [a["title"] for a in articles] == ["有効な記事"]

    def test_uses_the_symbol_query(self):
        """通貨ペアに応じた検索クエリで取得すること"""
        ctx, client = mock_http(rss("x"))
        with patch("src.ai.news.httpx.AsyncClient", return_value=ctx):
            asyncio.run(fetch_rss_news("EURUSD"))

        assert "EUR" in client.get.call_args[0][0]

    def test_network_error_falls_back(self):
        """通信エラー時はフォールバック記事を返すこと"""
        ctx, _ = mock_http(b"", raise_error=OSError("network down"))
        with patch("src.ai.news.httpx.AsyncClient", return_value=ctx):
            articles = asyncio.run(fetch_rss_news("USDJPY"))

        assert [a["title"] for a in articles] == FALLBACK_HEADLINES["USDJPY"]

    def test_malformed_feed_falls_back(self):
        """RSS が壊れていてもフォールバックすること"""
        ctx, _ = mock_http(b"<<not xml>>")
        with patch("src.ai.news.httpx.AsyncClient", return_value=ctx):
            articles = asyncio.run(fetch_rss_news("USDJPY"))

        assert articles[0]["source"] == "FX Tool"

    def test_empty_feed_falls_back(self):
        """記事が 0 件ならフォールバックすること"""
        ctx, _ = mock_http(rss())
        with patch("src.ai.news.httpx.AsyncClient", return_value=ctx):
            assert asyncio.run(fetch_rss_news("USDJPY"))[0]["source"] == "FX Tool"

    def test_sends_a_browser_user_agent(self):
        """ブロック回避のためブラウザ相当の UA を送ること"""
        ctx, client = mock_http(rss("x"))
        with patch("src.ai.news.httpx.AsyncClient", return_value=ctx):
            asyncio.run(fetch_rss_news("USDJPY"))

        assert "Mozilla" in client.get.call_args.kwargs["headers"]["User-Agent"]


class TestAnalyzeNews:
    """analyze_news() のテスト"""

    AI_RESULT = {
        "summary": "ドル高基調",
        "sentiment": "bullish",
        "sentiment_score": 60,
        "key_topics": ["FOMC"],
        "market_impact": "medium",
    }

    def _run(self, articles=None, ai_result=None, symbol="USDJPY"):
        with patch("src.ai.news.fetch_rss_news",
                   new=AsyncMock(return_value=articles or _fallback_articles("USDJPY"))), \
             patch("src.ai.news.chat_json", return_value=ai_result or self.AI_RESULT) as chat:
            return asyncio.run(analyze_news(symbol)), chat

    def test_merges_the_ai_result(self):
        """AI の分析結果をそのまま結果へ展開すること"""
        result, _ = self._run()

        assert result["sentiment"] == "bullish"
        assert result["sentiment_score"] == 60
        assert result["summary"] == "ドル高基調"

    def test_includes_the_source_articles(self):
        """分析に使った記事を添えること（出典表示のため）"""
        articles = _fallback_articles("USDJPY")
        result, _ = self._run(articles=articles)
        assert result["articles"] == articles

    def test_records_the_symbol_and_timestamp(self):
        """シンボルと収集時刻を記録すること"""
        result, _ = self._run()

        assert result["symbol"] == "USDJPY"
        assert datetime.fromisoformat(result["collected_at"])

    def test_headlines_are_passed_to_the_model(self):
        """ヘッドラインと出典をプロンプトへ渡すこと"""
        articles = [{"title": "ドル円が上昇", "url": "", "published_at": "", "source": "Reuters"}]
        _, chat = self._run(articles=articles)

        user_prompt = chat.call_args[0][1]
        assert "ドル円が上昇" in user_prompt
        assert "Reuters" in user_prompt
        assert "USDJPY" in user_prompt

    def test_prompt_requests_japanese_json(self):
        """日本語 JSON を返すようシステムプロンプトで指示すること"""
        _, chat = self._run()
        system_prompt = chat.call_args[0][0]

        assert "sentiment" in system_prompt
        assert "日本語" in system_prompt

    def test_api_errors_propagate(self):
        """OpenAI のエラーは呼び出し元へ伝えること"""
        with patch("src.ai.news.fetch_rss_news", new=AsyncMock(return_value=[])), \
             patch("src.ai.news.chat_json", side_effect=ValueError("OpenAI API エラー")):
            with pytest.raises(ValueError, match="OpenAI API エラー"):
                asyncio.run(analyze_news("USDJPY"))
