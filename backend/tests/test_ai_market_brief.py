"""市場ブリーフ生成 — src.ai.market_brief のテスト

ニュース・SNS・経済指標の取得と OpenAI 呼び出しはモックへ差し替え、
集約と OpenAI 未設定時のフォールバックを検証する。
"""

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from src.ai.market_brief import build_market_brief


def article(title="ドル円が上昇") -> dict:
    """ニュース記事 1 件。"""
    return {"title": title, "url": "https://example.com", "published_at": "", "source": "Reuters"}


def sns_result(posts=3) -> dict:
    """SNS 分析結果。"""
    return {
        "summary": "SNS は強気優勢",
        "sentiment": {"sentiment": "bullish", "sentiment_score": 40},
        "engagement": "medium",
        "posts": [{"title": f"post {i}", "subreddit": "forex", "score": 10}
                  for i in range(posts)],
    }


def economic_result(indicators=3, alerts=2) -> dict:
    """経済指標分析結果。"""
    return {
        "pair_bias": "bullish",
        "pair_bias_label": "USDJPY ファンダメンタル強気",
        "overview": "米指標は堅調",
        "indicators": [{"name": f"指標{i}", "comment": "改善", "pair_direction": "bullish"}
                       for i in range(indicators)],
        "high_impact_alerts": [{"title": f"event {i}"} for i in range(alerts)],
    }


def build(articles=None, sns=None, economic=None, api_key="", ai_result=None, ai_error=None):
    """依存をモックしてブリーフを生成する。"""
    with patch("src.ai.market_brief.fetch_rss_news",
               new=AsyncMock(return_value=articles if articles is not None else [article()])), \
         patch("src.ai.market_brief.analyze_sns",
               new=AsyncMock(return_value=sns or sns_result())), \
         patch("src.ai.market_brief.analyze_economic",
               new=AsyncMock(return_value=economic or economic_result())), \
         patch("src.ai.market_brief.resolve_openai_api_key", return_value=api_key), \
         patch("src.ai.market_brief.chat_json",
               side_effect=ai_error,
               return_value=ai_result or {"executive_summary": "AI 要約"}) as chat:
        return asyncio.run(build_market_brief("USDJPY")), chat


class TestBuildMarketBrief:
    """build_market_brief() のテスト"""

    def test_returns_all_sections(self):
        """ニュース・SNS・経済指標・OpenAI の 4 セクションを返すこと"""
        result, _ = build()
        assert set(result) >= {"symbol", "news", "sns", "economic", "openai"}

    def test_normalizes_the_symbol(self):
        """シンボルを大文字化すること"""
        with patch("src.ai.market_brief.fetch_rss_news", new=AsyncMock(return_value=[article()])), \
             patch("src.ai.market_brief.analyze_sns", new=AsyncMock(return_value=sns_result())), \
             patch("src.ai.market_brief.analyze_economic",
                   new=AsyncMock(return_value=economic_result())), \
             patch("src.ai.market_brief.resolve_openai_api_key", return_value=""):
            assert asyncio.run(build_market_brief("usdjpy"))["symbol"] == "USDJPY"

    def test_news_includes_ml_sentiment(self):
        """ニュースに ML センチメントを付けること"""
        result, _ = build(articles=[article("strong rally"), article("gains surge")])
        assert result["news"]["ml"]["sentiment"] == "bullish"

    def test_news_articles_are_capped_at_eight(self):
        """記事は 8 件までに絞ること"""
        result, _ = build(articles=[article(f"n{i}") for i in range(20)])
        assert len(result["news"]["articles"]) == 8

    def test_sns_section_is_summarised(self):
        """SNS は要約・センチメント・エンゲージメントに絞ること"""
        result, _ = build()
        assert set(result["sns"]) == {"summary", "sentiment", "engagement", "posts"}

    def test_sns_posts_are_capped_at_five(self):
        """SNS 投稿は 5 件までに絞ること"""
        result, _ = build(sns=sns_result(posts=20))
        assert len(result["sns"]["posts"]) == 5

    def test_economic_section_is_summarised(self):
        """経済指標はバイアス・概要・主要指標・アラートに絞ること"""
        result, _ = build()
        assert set(result["economic"]) == {
            "pair_bias", "pair_bias_label", "overview", "indicators", "alerts",
        }

    def test_economic_indicators_are_capped_at_five(self):
        """経済指標は 5 件までに絞ること"""
        result, _ = build(economic=economic_result(indicators=20))
        assert len(result["economic"]["indicators"]) == 5

    def test_alerts_are_capped_at_three(self):
        """高影響アラートは 3 件までに絞ること"""
        result, _ = build(economic=economic_result(alerts=10))
        assert len(result["economic"]["alerts"]) == 3

    def test_openai_is_skipped_without_a_key(self):
        """API キーが無ければ OpenAI を呼ばず None のままにすること"""
        result, chat = build(api_key="")

        assert result["openai"] is None
        chat.assert_not_called()

    def test_openai_result_is_attached(self):
        """API キーがあれば OpenAI の要約を付けること"""
        result, _ = build(api_key="sk-test", ai_result={"executive_summary": "ドル高継続"})
        assert result["openai"]["executive_summary"] == "ドル高継続"

    def test_openai_failure_does_not_break_the_brief(self):
        """OpenAI が失敗してもブリーフ自体は返すこと"""
        result, _ = build(api_key="sk-test", ai_error=RuntimeError("rate limit"))

        assert result["symbol"] == "USDJPY"
        assert result["news"]["ml"]["sentiment"] in ("bullish", "bearish", "neutral")

    def test_prompt_includes_all_three_sources(self):
        """プロンプトにニュース・SNS・経済指標をすべて含めること"""
        _, chat = build(api_key="sk-test")
        user_prompt = chat.call_args[0][1]

        assert "ドル円が上昇" in user_prompt
        assert "post 0" in user_prompt
        assert "指標0" in user_prompt

    def test_works_without_any_news(self):
        """ニュースが 0 件でも例外にならないこと"""
        result, _ = build(articles=[])
        assert result["news"]["articles"] == []
        assert result["news"]["ml"]["sentiment"] == "neutral"
