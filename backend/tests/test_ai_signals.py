"""AI 統合シグナル — src.ai.signals のテスト

市場データ・MTF・トレンド予測・OpenAI はモックへ差し替え、
多数決ロジックと AI 判断の上書きを検証する。
"""

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from src.ai.signals import _signal_summary, generate_ai_signals
from src.analysis.market_context import MarketContext


def mtf_result(alignment="neutral") -> dict:
    """MTF 分析結果。"""
    return {"alignment": alignment, "alignment_label": f"MTF:{alignment}", "timeframes": {}}


def trend_result(trend="neutral") -> dict:
    """トレンド予測結果。"""
    return {"trend": trend, "trend_label": f"トレンド:{trend}", "confidence": 60.0}


def run(indicators_df, mtf="neutral", trend="neutral", api_key="", ai_decision=None,
        ai_error=None):
    """依存をモックしてシグナル生成を実行する。"""
    ctx = MarketContext("USDJPY", 200, "database", indicators_df)
    decision = AsyncMock(return_value=ai_decision or {"action": "hold", "confidence": 0.5})
    if ai_error is not None:
        decision = AsyncMock(side_effect=ai_error)

    with patch("src.ai.signals.resolve_openai_api_key", return_value=api_key), \
         patch("src.ai.signals.make_trading_decision", new=decision):
        return asyncio.run(generate_ai_signals(
            "usdjpy", ctx=ctx, mtf=mtf_result(mtf), trend=trend_result(trend)))


class TestSignalSummary:
    """_signal_summary() のテスト"""

    def test_translates_the_action(self):
        """アクションを日本語に変換すること"""
        summary = _signal_summary("buy", 70, [], trend_result(), mtf_result())
        assert "買い" in summary

    @pytest.mark.parametrize("action,label", [("buy", "買い"), ("sell", "売り"), ("hold", "様子見")])
    def test_all_actions_have_labels(self, action, label):
        """3 種類のアクションすべてに日本語ラベルがあること"""
        assert label in _signal_summary(action, 70, [], trend_result(), mtf_result())

    def test_counts_rule_signals(self):
        """テクニカルシグナルの内訳を含めること"""
        rules = [{"signal": "buy"}, {"signal": "buy"}, {"signal": "sell"}]
        assert "2買い/1売り" in _signal_summary("buy", 70, rules, trend_result(), mtf_result())

    def test_includes_confidence_trend_and_mtf(self):
        """信頼度・トレンド・MTF を要約に含めること"""
        summary = _signal_summary("buy", 82, [], trend_result("bullish"), mtf_result("bullish"))

        assert "82%" in summary
        assert "トレンド:bullish" in summary
        assert "MTF:bullish" in summary


class TestGenerateAiSignals:
    """generate_ai_signals() のテスト"""

    def test_returns_expected_keys(self, indicators_df):
        """結果のキーが揃っていること"""
        assert set(run(indicators_df)) == {
            "symbol", "source", "price", "action", "confidence",
            "rule_signals", "multi_timeframe", "trend_ml", "ai_decision", "summary",
        }

    def test_normalizes_the_symbol(self, indicators_df):
        """シンボルを大文字化すること"""
        assert run(indicators_df)["symbol"] == "USDJPY"

    def test_reports_the_source_and_price(self, indicators_df):
        """データソースと現在価格を返すこと"""
        result = run(indicators_df)

        assert result["source"] == "database"
        assert result["price"] == round(float(indicators_df["close"].iloc[-1]), 4)

    def test_bullish_majority_yields_buy(self, indicators_df):
        """強気票が多ければ買いになること"""
        result = run(indicators_df, mtf="bullish", trend="bullish")

        assert result["action"] == "buy"
        assert result["confidence"] > 50

    def test_bearish_majority_yields_sell(self, indicators_df):
        """弱気票が多ければ売りになること"""
        result = run(indicators_df, mtf="bearish", trend="bearish")
        assert result["action"] == "sell"

    def test_tie_yields_hold(self, indicators_df):
        """票が割れれば様子見になること

        投票はテクニカル・トレンド予測・MTF の 3 者。テクニカルを中立にした上で
        残りを 1 対 1 にすると同数になり hold が選ばれる。
        """
        with patch("src.ai.signals.signals_from_row", return_value=[]):
            result = run(indicators_df, mtf="bullish", trend="bearish")

        assert result["action"] == "hold"
        assert result["confidence"] == 40

    def test_confidence_is_capped(self, indicators_df):
        """信頼度は 95% を超えないこと"""
        assert run(indicators_df, mtf="bullish", trend="bullish")["confidence"] <= 95

    def test_includes_the_trend_summary(self, indicators_df):
        """トレンド予測の要約を含めること"""
        trend_ml = run(indicators_df, trend="bullish")["trend_ml"]

        assert trend_ml["trend"] == "bullish"
        assert trend_ml["label"] == "トレンド:bullish"
        assert trend_ml["confidence"] == 60.0

    def test_openai_is_skipped_without_a_key(self, indicators_df):
        """API キーが無ければ AI 判断を呼ばないこと"""
        result = run(indicators_df, api_key="")
        assert result["ai_decision"] is None

    def test_ai_decision_overrides_the_action(self, indicators_df):
        """AI の判断が最終アクションを上書きすること"""
        result = run(indicators_df, mtf="bullish", trend="bullish",
                     api_key="sk-test", ai_decision={"action": "sell", "confidence": 0.8})

        assert result["action"] == "sell"
        assert result["ai_decision"]["action"] == "sell"

    def test_agreeing_ai_raises_confidence(self, indicators_df):
        """AI が多数決と一致すれば信頼度を引き上げうること"""
        result = run(indicators_df, mtf="bullish", trend="bullish",
                     api_key="sk-test", ai_decision={"action": "buy", "confidence": 0.95})
        assert result["confidence"] >= 80

    def test_openai_failure_is_tolerated(self, indicators_df):
        """AI 呼び出しが失敗しても多数決の結果を返すこと"""
        result = run(indicators_df, mtf="bullish", trend="bullish",
                     api_key="sk-test", ai_error=RuntimeError("timeout"))

        assert result["action"] == "buy"
        assert result["ai_decision"] is None

    def test_invalid_ai_action_is_ignored(self, indicators_df):
        """AI が想定外のアクションを返しても採用しないこと"""
        result = run(indicators_df, mtf="bullish", trend="bullish",
                     api_key="sk-test", ai_decision={"action": "moon", "confidence": 0.9})
        assert result["action"] == "buy"

    def test_rule_signals_are_included(self, indicators_df):
        """ルールベースのシグナル一覧を返すこと"""
        for signal in run(indicators_df)["rule_signals"]:
            assert signal["signal"] in ("buy", "sell")

    def test_injected_context_avoids_recomputation(self, indicators_df):
        """外部から渡したコンテキストを再計算しないこと"""
        ctx = MarketContext("USDJPY", 200, "database", indicators_df)
        with patch("src.ai.signals.resolve_openai_api_key", return_value=""), \
             patch("src.analysis.market_context.MarketContext.load") as load:
            asyncio.run(generate_ai_signals("USDJPY", ctx=ctx,
                                            mtf=mtf_result(), trend=trend_result()))

        load.assert_not_called()
