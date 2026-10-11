"""SNS（Reddit）センチメント分析 — src.analysis.sns のテスト

外部 API とキャッシュはモックへ差し替え、集計とフォールバックを検証する。
"""

import asyncio
from datetime import datetime
from unittest.mock import AsyncMock, patch

import pytest

from src.analysis.sns import FALLBACK_SNS, SYMBOL_REDDIT_QUERIES, analyze_sns


def post(title="USDJPY breakout", subreddit="forex", score=10, comments=5,
         source="reddit") -> dict:
    """投稿 1 件を組み立てる。"""
    return {"title": title, "subreddit": subreddit, "score": score,
            "num_comments": comments, "source": source}


def analyze(posts, symbol="USDJPY", limit=10) -> dict:
    """投稿取得をモックして分析を実行する。"""
    with patch("src.analysis.sns.cache_get", return_value=None), \
         patch("src.analysis.sns.cache_put"), \
         patch("src.analysis.sns.fetch_reddit_posts", new=AsyncMock(return_value=posts)):
        return asyncio.run(analyze_sns(symbol, limit))


class TestConstants:
    """検索クエリとフォールバックデータのテスト"""

    def test_queries_cover_the_major_pairs(self):
        """主要 4 通貨ペアの検索クエリを持つこと"""
        assert set(SYMBOL_REDDIT_QUERIES) == {"USDJPY", "EURUSD", "GBPUSD", "AUDUSD"}

    def test_fallback_covers_the_same_pairs(self):
        """フォールバックデータも同じペアを網羅すること"""
        assert set(FALLBACK_SNS) == set(SYMBOL_REDDIT_QUERIES)

    def test_fallback_posts_have_required_fields(self):
        """フォールバック投稿がタイトル・サブレディット・スコアを持つこと"""
        for posts in FALLBACK_SNS.values():
            for p in posts:
                assert {"title", "subreddit", "score"} <= set(p)

    def test_fallback_is_never_empty(self):
        """どのペアにも最低 1 件のフォールバックがあること"""
        assert all(len(posts) >= 1 for posts in FALLBACK_SNS.values())


class TestAnalyzeSns:
    """analyze_sns() のテスト"""

    def test_returns_expected_keys(self):
        """分析結果のキーが揃っていること"""
        assert set(analyze([post()])) == {
            "symbol", "collected_at", "platform", "platform_label", "post_count",
            "posts", "sentiment", "engagement", "total_score", "total_comments",
            "subreddits", "summary",
        }

    def test_normalizes_the_symbol(self):
        """シンボルを大文字化すること"""
        assert analyze([post()], symbol="usdjpy")["symbol"] == "USDJPY"

    def test_counts_posts(self):
        """投稿件数を返すこと"""
        result = analyze([post(), post(), post()])
        assert result["post_count"] == 3
        assert len(result["posts"]) == 3

    def test_sums_scores_and_comments(self):
        """スコアとコメント数を合計すること"""
        result = analyze([post(score=10, comments=3), post(score=25, comments=7)])
        assert result["total_score"] == 35
        assert result["total_comments"] == 10

    @pytest.mark.parametrize("score,comments,engagement", [
        (0, 0, "low"),
        (30, 0, "low"),
        (31, 0, "medium"),
        (100, 0, "medium"),
        (101, 0, "high"),
        (0, 51, "high"),
    ])
    def test_engagement_thresholds(self, score, comments, engagement):
        """スコア・コメント数に応じてエンゲージメントを分類すること"""
        assert analyze([post(score=score, comments=comments)])["engagement"] == engagement

    def test_counts_subreddits(self):
        """サブレディットごとの投稿数を集計すること"""
        result = analyze([post(subreddit="forex"), post(subreddit="forex"),
                          post(subreddit="Forexstrategy")])
        assert result["subreddits"] == {"forex": 2, "Forexstrategy": 1}

    def test_missing_subreddit_becomes_unknown(self):
        """サブレディット不明の投稿は unknown として数えること"""
        result = analyze([{"title": "x", "score": 1, "source": "reddit"}])
        assert result["subreddits"] == {"unknown": 1}

    def test_sentiment_is_computed_from_titles(self):
        """投稿タイトルからセンチメントを判定すること"""
        bullish = analyze([post(title="strong rally and gains"),
                           post(title="surge continues, growth")])
        assert bullish["sentiment"]["sentiment"] == "bullish"

    @pytest.mark.parametrize("source,label", [
        ("reddit", "Reddit"),
        ("google_news", "Google News（Reddit 代替）"),
        ("sample", "サンプルデータ"),
    ])
    def test_platform_labels(self, source, label):
        """取得元プラットフォームを日本語ラベルで返すこと"""
        result = analyze([post(source=source)])
        assert result["platform"] == source
        assert result["platform_label"] == label

    def test_unknown_platform_falls_back_to_the_raw_name(self):
        """未知の取得元はそのまま表示すること"""
        assert analyze([post(source="mastodon")])["platform_label"] == "mastodon"

    def test_empty_posts_are_handled(self):
        """投稿が 0 件でも例外にならないこと"""
        result = analyze([])

        assert result["post_count"] == 0
        assert result["platform"] == "sample"
        assert result["engagement"] == "low"
        assert result["sentiment"]["sentiment"] == "neutral"

    def test_summary_mentions_counts_and_sentiment(self):
        """要約に件数・センチメント・エンゲージメントを含めること"""
        summary = analyze([post(title="rally", score=200)])["summary"]

        assert "1件" in summary
        assert "bullish" in summary
        assert "high" in summary

    def test_collected_at_is_iso_timestamp(self):
        """収集時刻を ISO 8601 で返すこと"""
        assert datetime.fromisoformat(analyze([post()])["collected_at"])

    def test_uses_the_cached_result(self):
        """キャッシュヒット時は取得処理を行わないこと"""
        cached = {"symbol": "USDJPY"}
        with patch("src.analysis.sns.cache_get", return_value=cached), \
             patch("src.analysis.sns.fetch_reddit_posts", new=AsyncMock()) as fetch:
            assert asyncio.run(analyze_sns("USDJPY")) is cached
        fetch.assert_not_awaited()

    def test_stores_the_result_in_the_cache(self):
        """計算結果をキャッシュへ保存すること"""
        with patch("src.analysis.sns.cache_get", return_value=None), \
             patch("src.analysis.sns.cache_put") as cache_put, \
             patch("src.analysis.sns.fetch_reddit_posts",
                   new=AsyncMock(return_value=[post()])):
            result = asyncio.run(analyze_sns("USDJPY"))

        assert cache_put.call_args[0][1] == result

    def test_limit_is_passed_through(self):
        """取得件数の上限を取得処理へ渡すこと"""
        with patch("src.analysis.sns.cache_get", return_value=None), \
             patch("src.analysis.sns.cache_put"), \
             patch("src.analysis.sns.fetch_reddit_posts",
                   new=AsyncMock(return_value=[])) as fetch:
            asyncio.run(analyze_sns("USDJPY", limit=25))

        assert fetch.await_args[0][1] == 25
