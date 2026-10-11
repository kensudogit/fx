"""統合インテリジェンス分析 — src.api.intelligence のテスト

5 種類の分析はモックへ差し替え、複合スコアの重み付けとキャッシュ方針を検証する。
"""

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from src.api.intelligence import build_intelligence


def trend(direction="neutral") -> dict:
    """トレンド予測結果。"""
    return {"trend": direction, "trend_label": f"トレンド:{direction}", "confidence": 60}


def volatility(vol_trend="stable") -> dict:
    """ボラティリティ予測結果。"""
    return {"forecast": {"vol_trend": vol_trend, "regime": "medium",
                         "atr": 0.9, "atr_percent": 0.6},
            "current": {"atr": 0.9, "atr_percent": 0.6},
            "interpretation": "平常"}


def build(trend_dir="neutral", news="neutral", sns="neutral", economic="neutral",
          vol_trend="stable", api_key="", ai_error=None, **kwargs):
    """依存をモックして統合分析を実行する。"""
    with patch("src.api.intelligence.cache_get", return_value=None), \
         patch("src.api.intelligence.cache_put"), \
         patch("src.api.intelligence.predict_trend", return_value=trend(trend_dir)), \
         patch("src.api.intelligence.predict_volatility", return_value=volatility(vol_trend)), \
         patch("src.api.intelligence.analyze_economic",
               new=AsyncMock(return_value={"pair_bias": economic, "overview": "x",
                                           "indicators": [], "high_impact_alerts": [],
                                           "pair_bias_label": "y"})), \
         patch("src.api.intelligence.analyze_sns",
               new=AsyncMock(return_value={"sentiment": {"sentiment": sns}, "summary": "s",
                                           "posts": [], "engagement": "low"})), \
         patch("src.api.intelligence.fetch_rss_news", new=AsyncMock(return_value=[])), \
         patch("src.api.intelligence.analyze_headlines_ml",
               return_value={"sentiment": news, "sentiment_score": 0, "summary": "m",
                             "bullish_hits": 0, "bearish_hits": 0, "key_topics": []}), \
         patch("src.api.intelligence.resolve_openai_api_key", return_value=api_key), \
         patch("src.api.intelligence.analyze_news",
               new=AsyncMock(side_effect=ai_error,
                             return_value={"summary": "AI", "sentiment": "bullish",
                                           "sentiment_score": 60, "market_impact": "high"})):
        return asyncio.run(build_intelligence("USDJPY", **kwargs))


class TestBuildIntelligence:
    """build_intelligence() のテスト"""

    def test_returns_the_core_keys(self):
        """複合スコアと見通しを返すこと"""
        result = build()
        assert {"symbol", "composite_score", "outlook", "outlook_label"} <= set(result)

    def test_normalizes_the_symbol(self):
        """シンボルを大文字化すること"""
        assert build()["symbol"] == "USDJPY"

    def test_all_neutral_scores_zero(self):
        """すべて中立ならスコア 0・見通し中立になること"""
        result = build()

        assert result["composite_score"] == 0
        assert result["outlook"] == "neutral"

    def test_trend_has_the_largest_weight(self):
        """トレンドの重みが最大（±30）であること"""
        assert build(trend_dir="bullish")["composite_score"] == 30

    def test_economic_weight(self):
        """経済指標の重みが ±25 であること"""
        assert build(economic="bullish")["composite_score"] == 25

    def test_news_weight(self):
        """ニュース ML の重みが ±20 であること"""
        assert build(news="bullish")["composite_score"] == 20

    def test_sns_weight(self):
        """SNS の重みが ±15 であること"""
        assert build(sns="bullish")["composite_score"] == 15

    @pytest.mark.parametrize("vol_trend,delta", [
        ("expanding", -5), ("contracting", 5), ("stable", 0),
    ])
    def test_volatility_adjusts_the_score(self, vol_trend, delta):
        """ボラ拡大は減点、収縮は加点すること"""
        assert build(vol_trend=vol_trend)["composite_score"] == delta

    def test_components_are_summed(self):
        """各要素のスコアを合算すること"""
        result = build(trend_dir="bullish", news="bullish", sns="bullish", economic="bullish")
        assert result["composite_score"] == 90

    def test_opposing_components_cancel(self):
        """逆方向の要素は打ち消し合うこと"""
        assert build(trend_dir="bullish", economic="bearish")["composite_score"] == 5

    def test_score_is_bounded(self):
        """スコアは -100〜100 に収まること"""
        strong = build(trend_dir="bullish", news="bullish", sns="bullish",
                       economic="bullish", vol_trend="contracting")
        assert -100 <= strong["composite_score"] <= 100

    @pytest.mark.parametrize("args,outlook", [
        ({"trend_dir": "bullish", "economic": "bullish"}, "bullish"),
        ({"trend_dir": "bearish", "economic": "bearish"}, "bearish"),
        ({"sns": "bullish"}, "neutral"),
    ])
    def test_outlook_thresholds(self, args, outlook):
        """スコア ±25 を境に見通しを切り替えること"""
        assert build(**args)["outlook"] == outlook

    def test_outlook_label_is_japanese(self):
        """見通しのラベルが日本語であること"""
        assert "強気" in build(trend_dir="bullish", economic="bullish")["outlook_label"]

    def test_openai_is_skipped_without_a_key(self):
        """API キーが無ければ OpenAI ニュース分析を行わないこと"""
        assert build(api_key="")["news"]["openai"] is None

    def test_openai_result_is_attached(self):
        """API キーがあれば OpenAI の要約を付けること"""
        assert build(api_key="sk-test")["news"]["openai"]["sentiment"] == "bullish"

    def test_openai_error_is_recorded(self):
        """OpenAI が失敗しても分析は続行し、原因を残すこと"""
        result = build(api_key="sk-test", ai_error=RuntimeError("rate limit"))

        assert result["news"]["openai"] is None
        assert "rate limit" in result["news"]["openai_error"]


class TestCaching:
    """キャッシュ方針のテスト"""

    def test_standalone_calls_use_the_cache(self):
        """単独呼び出しではキャッシュを参照すること"""
        cached = {"symbol": "USDJPY", "composite_score": 42}
        with patch("src.api.intelligence.cache_get", return_value=cached), \
             patch("src.api.intelligence.predict_trend") as predict:
            assert asyncio.run(build_intelligence("USDJPY")) is cached
        predict.assert_not_called()

    def test_shared_calls_skip_the_cache(self):
        """事前計算済みの結果を渡された場合はキャッシュを使わないこと"""
        with patch("src.api.intelligence.cache_get") as cache_get, \
             patch("src.api.intelligence.cache_put") as cache_put, \
             patch("src.api.intelligence.analyze_economic",
                   new=AsyncMock(return_value={"pair_bias": "neutral", "overview": "",
                                               "indicators": [], "high_impact_alerts": [],
                                               "pair_bias_label": ""})), \
             patch("src.api.intelligence.analyze_sns",
                   new=AsyncMock(return_value={"sentiment": {"sentiment": "neutral"},
                                               "summary": "", "posts": [],
                                               "engagement": "low"})), \
             patch("src.api.intelligence.fetch_rss_news", new=AsyncMock(return_value=[])), \
             patch("src.api.intelligence.analyze_headlines_ml",
                   return_value={"sentiment": "neutral", "sentiment_score": 0,
                                 "summary": "", "bullish_hits": 0, "bearish_hits": 0,
                                 "key_topics": []}), \
             patch("src.api.intelligence.resolve_openai_api_key", return_value=""):
            asyncio.run(build_intelligence("USDJPY", trend=trend(), volatility=volatility()))

        cache_get.assert_not_called()
        cache_put.assert_not_called()

    def test_result_is_cached_for_standalone_calls(self):
        """単独呼び出しの結果はキャッシュへ保存すること"""
        with patch("src.api.intelligence.cache_get", return_value=None), \
             patch("src.api.intelligence.cache_put") as cache_put, \
             patch("src.api.intelligence.predict_trend", return_value=trend()), \
             patch("src.api.intelligence.predict_volatility", return_value=volatility()), \
             patch("src.api.intelligence.analyze_economic",
                   new=AsyncMock(return_value={"pair_bias": "neutral", "overview": "",
                                               "indicators": [], "high_impact_alerts": [],
                                               "pair_bias_label": ""})), \
             patch("src.api.intelligence.analyze_sns",
                   new=AsyncMock(return_value={"sentiment": {"sentiment": "neutral"},
                                               "summary": "", "posts": [],
                                               "engagement": "low"})), \
             patch("src.api.intelligence.fetch_rss_news", new=AsyncMock(return_value=[])), \
             patch("src.api.intelligence.analyze_headlines_ml",
                   return_value={"sentiment": "neutral", "sentiment_score": 0,
                                 "summary": "", "bullish_hits": 0, "bearish_hits": 0,
                                 "key_topics": []}), \
             patch("src.api.intelligence.resolve_openai_api_key", return_value=""):
            result = asyncio.run(build_intelligence("USDJPY"))

        assert cache_put.call_args[0][1] == result
