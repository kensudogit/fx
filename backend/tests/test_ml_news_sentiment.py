"""ニュースのキーワードセンチメント分析 — src.ml.news_sentiment のテスト"""

import pytest

from src.ml.news_sentiment import BEARISH_WORDS, BULLISH_WORDS, analyze_headlines_ml


class TestWordLists:
    """キーワード辞書のテスト"""

    def test_both_lists_are_non_empty(self):
        """強気・弱気の双方に語彙があること"""
        assert BULLISH_WORDS and BEARISH_WORDS

    def test_lists_do_not_overlap(self):
        """同じ語が両方に登録されていないこと（判定が相殺されるため）"""
        assert BULLISH_WORDS & BEARISH_WORDS == set()

    def test_covers_english_and_japanese(self):
        """英語・日本語の双方を含むこと"""
        assert "rally" in BULLISH_WORDS
        assert "上昇" in BULLISH_WORDS
        assert "decline" in BEARISH_WORDS
        assert "下落" in BEARISH_WORDS


class TestAnalyzeHeadlines:
    """analyze_headlines_ml() のテスト"""

    def test_returns_expected_keys(self):
        """分析結果のキーが揃っていること"""
        assert set(analyze_headlines_ml(["dollar rally"])) == {
            "method", "sentiment", "sentiment_score", "bullish_hits",
            "bearish_hits", "key_topics", "summary",
        }

    def test_method_is_reported(self):
        """判定手法を明示すること（OpenAI 分析と区別するため）"""
        assert analyze_headlines_ml(["x"])["method"] == "ml_keyword"

    def test_bullish_headlines(self):
        """強気語が多ければ bullish になること"""
        result = analyze_headlines_ml([
            "Dollar rally continues", "Strong growth beats forecasts", "Yen gains surge",
        ])
        assert result["sentiment"] == "bullish"
        assert result["sentiment_score"] > 15
        assert result["bullish_hits"] > result["bearish_hits"]

    def test_bearish_headlines(self):
        """弱気語が多ければ bearish になること"""
        result = analyze_headlines_ml([
            "Dollar declines sharply", "Weak data misses estimates", "Recession fears drop stocks",
        ])
        assert result["sentiment"] == "bearish"
        assert result["sentiment_score"] < -15

    def test_balanced_headlines_are_neutral(self):
        """強気・弱気が拮抗すれば neutral になること"""
        result = analyze_headlines_ml(["rally and decline", "gain and drop"])
        assert result["sentiment"] == "neutral"

    def test_no_keywords_is_neutral(self):
        """キーワードが無ければ中立になること（0 除算も起きない）"""
        result = analyze_headlines_ml(["The central bank meets on Tuesday"])
        assert result["sentiment"] == "neutral"
        assert result["sentiment_score"] == 0

    def test_empty_input_is_safe(self):
        """ヘッドラインが空でも例外にならないこと"""
        result = analyze_headlines_ml([])
        assert result["sentiment"] == "neutral"
        assert result["key_topics"] == []

    def test_japanese_headlines(self):
        """日本語のヘッドラインも判定できること"""
        result = analyze_headlines_ml(["ドル円が上昇", "好調な経済指標で買い優勢"])
        assert result["sentiment"] == "bullish"

    def test_score_is_bounded(self):
        """スコアは -100〜100 に収まること"""
        strong = analyze_headlines_ml(["rally " * 50])
        weak = analyze_headlines_ml(["decline " * 50])

        assert -100 <= strong["sentiment_score"] <= 100
        assert -100 <= weak["sentiment_score"] <= 100

    def test_is_case_insensitive(self):
        """大文字・小文字を区別しないこと"""
        assert (analyze_headlines_ml(["RALLY"])["sentiment"]
                == analyze_headlines_ml(["rally"])["sentiment"])

    def test_matches_inflected_words(self):
        """語形変化（rallies / declines）にも部分一致で反応すること"""
        assert analyze_headlines_ml(["markets rallied strongly"])["bullish_hits"] > 0

    def test_key_topics_are_extracted(self):
        """頻出語をキートピックとして抽出すること"""
        result = analyze_headlines_ml([
            "inflation data", "inflation report", "inflation outlook", "dollar dollar dollar",
        ])
        assert "inflation" in result["key_topics"]

    def test_key_topics_skip_short_words(self):
        """3 文字以下の語はトピックに含めないこと（ノイズ除去）"""
        result = analyze_headlines_ml(["the fed is on the way", "the fed is on the way"])
        assert all(len(t) > 2 for t in result["key_topics"])

    def test_key_topics_are_capped_at_five(self):
        """キートピックは最大 5 件までであること"""
        headlines = [" ".join(f"topic{i}" for _ in range(3)) for i in range(20)]
        assert len(analyze_headlines_ml(headlines)["key_topics"]) <= 5

    def test_summary_reports_hit_counts(self):
        """要約に強気・弱気のヒット数を含めること"""
        result = analyze_headlines_ml(["rally", "decline"])
        assert str(result["bullish_hits"]) in result["summary"]
        assert str(result["bearish_hits"]) in result["summary"]

    def test_hits_are_non_negative(self):
        """ヒット数は 0 以上であること"""
        result = analyze_headlines_ml(["neutral wording here"])
        assert result["bullish_hits"] >= 0
        assert result["bearish_hits"] >= 0
