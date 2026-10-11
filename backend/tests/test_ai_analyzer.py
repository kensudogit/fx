"""OpenAI 総合分析 — src.ai.analyzer のテスト

OpenAI 呼び出しと市場データ取得はモックへ差し替え、
コンテキスト構築・ルールベースフォールバック・並列実行を検証する。
"""

import asyncio
from unittest.mock import AsyncMock, patch

import numpy as np
import pandas as pd
import pytest

from src.ai.analyzer import (
    CURRENCY_MAP,
    _build_technical_context,
    _calc_volatility,
    _rule_based_trading_fallback,
    _safe_round,
    assess_risk,
    generate_full_report,
    make_trading_decision,
)


def technical(price=150.0, buy=2, sell=0, atr=0.9) -> dict:
    """テクニカルコンテキストを組み立てる。"""
    return {"price": price, "buy_signals": buy, "sell_signals": sell,
            "volatility": {"atr": atr, "atr_percent": 0.6}}


class TestCurrencyMap:
    """CURRENCY_MAP のテスト"""

    def test_splits_pairs(self):
        """通貨ペアを基軸・決済に分解できること"""
        assert CURRENCY_MAP["USDJPY"] == ("USD", "JPY")

    def test_codes_are_three_letters(self):
        """通貨コードが 3 文字であること"""
        for base, quote in CURRENCY_MAP.values():
            assert len(base) == 3 and len(quote) == 3


class TestCalcVolatility:
    """_calc_volatility() のテスト"""

    def test_returns_expected_keys(self, ohlcv):
        """ボラティリティ指標のキーが揃っていること"""
        assert set(_calc_volatility(ohlcv)) == {
            "atr", "atr_percent", "daily_volatility", "max_drawdown_30d",
        }

    def test_values_are_non_negative(self, ohlcv):
        """ATR と日次ボラは 0 以上であること"""
        result = _calc_volatility(ohlcv)
        assert result["atr"] >= 0
        assert result["daily_volatility"] >= 0

    def test_drawdown_is_not_positive(self, ohlcv):
        """30 日ドローダウンは 0 以下であること"""
        assert _calc_volatility(ohlcv)["max_drawdown_30d"] <= 0

    def test_short_history_has_no_drawdown(self):
        """30 本に満たなければドローダウンは None を返すこと"""
        df = pd.DataFrame({"high": [101.0] * 20, "low": [99.0] * 20, "close": [100.0] * 20})
        assert _calc_volatility(df)["max_drawdown_30d"] is None

    def test_flat_market_is_zero(self):
        """値動きが無ければすべて 0 になること"""
        df = pd.DataFrame({"high": [100.0] * 40, "low": [100.0] * 40, "close": [100.0] * 40})
        result = _calc_volatility(df)

        assert result["atr"] == 0.0
        assert result["daily_volatility"] == 0.0


class TestSafeRound:
    """_safe_round() のテスト"""

    def test_rounds_numbers(self):
        """指定桁に丸めること"""
        assert _safe_round(1.23456789) == 1.2346

    def test_custom_digits(self):
        """桁数を指定できること"""
        assert _safe_round(1.23456789, digits=2) == 1.23

    @pytest.mark.parametrize("value", [None, float("nan"), np.nan])
    def test_missing_values_become_none(self, value):
        """None / NaN は None にすること（JSON 化のため）"""
        assert _safe_round(value) is None

    def test_accepts_integers(self):
        """整数も float へ丸めて返すこと"""
        assert _safe_round(5) == 5.0


class TestBuildTechnicalContext:
    """_build_technical_context() のテスト"""

    def test_collects_price_and_signals(self, ohlcv):
        """価格とシグナル集計を含むこと"""
        with patch("src.ai.analyzer.get_ohlcv_data", return_value=(ohlcv, "database")):
            ctx = _build_technical_context("USDJPY")

        assert ctx["price"] > 0
        assert ctx["buy_signals"] >= 0
        assert ctx["sell_signals"] >= 0

    def test_includes_volatility(self, ohlcv):
        """ボラティリティ情報を含むこと"""
        with patch("src.ai.analyzer.get_ohlcv_data", return_value=(ohlcv, "database")):
            assert "atr" in _build_technical_context("USDJPY")["volatility"]

    def test_values_are_json_serialisable(self, ohlcv):
        """NaN を含まず JSON 化できること"""
        import json

        with patch("src.ai.analyzer.get_ohlcv_data", return_value=(ohlcv, "database")):
            ctx = _build_technical_context("USDJPY")

        json.dumps(ctx)  # 例外が出なければ成功


class TestRuleBasedFallback:
    """_rule_based_trading_fallback() のテスト"""

    def test_marks_itself_as_a_fallback(self):
        """フォールバックであることを明示すること"""
        result = _rule_based_trading_fallback("USDJPY", technical(), {}, {})

        assert result["fallback"] is True
        assert any("OpenAI 応答不可" in w for w in result["warnings"])

    def test_buy_when_signals_agree(self):
        """テクニカル・ニュース・ファンダが揃えば買いになること"""
        result = _rule_based_trading_fallback(
            "USDJPY", technical(buy=2, sell=0),
            {"sentiment": "bullish"}, {"pair_bias": "bullish"})
        assert result["action"] == "buy"

    def test_sell_when_signals_agree(self):
        """弱気が揃えば売りになること"""
        result = _rule_based_trading_fallback(
            "USDJPY", technical(buy=0, sell=2),
            {"sentiment": "bearish"}, {"pair_bias": "bearish"})
        assert result["action"] == "sell"

    def test_hold_when_mixed(self):
        """判断が割れれば様子見にすること"""
        result = _rule_based_trading_fallback(
            "USDJPY", technical(buy=1, sell=1),
            {"sentiment": "neutral"}, {"pair_bias": "neutral"})
        assert result["action"] == "hold"

    def test_take_profit_is_twice_the_stop(self):
        """買いでは利確幅が損切り幅の 2 倍になること（RR 1:2）"""
        result = _rule_based_trading_fallback(
            "USDJPY", technical(price=150.0, buy=3, sell=0, atr=1.0),
            {"sentiment": "bullish"}, {"pair_bias": "bullish"})

        assert result["take_profit"] == 152.0
        assert result["stop_loss"] == 149.0
        assert result["risk_reward_ratio"] == 2.0

    def test_sell_levels_are_mirrored(self):
        """売りでは利確・損切りの上下が反転すること"""
        result = _rule_based_trading_fallback(
            "USDJPY", technical(price=150.0, buy=0, sell=3, atr=1.0),
            {"sentiment": "bearish"}, {"pair_bias": "bearish"})

        assert result["take_profit"] == 148.0
        assert result["stop_loss"] == 151.0

    def test_hold_uses_the_current_price(self):
        """様子見では利確・損切りを現在価格にすること"""
        result = _rule_based_trading_fallback("USDJPY", technical(buy=0, sell=0), {}, {})
        assert result["take_profit"] == result["stop_loss"] == 150.0

    def test_confidence_is_capped(self):
        """フォールバックの信頼度は 75% を超えないこと"""
        result = _rule_based_trading_fallback(
            "USDJPY", technical(buy=10, sell=0),
            {"sentiment": "bullish"}, {"pair_bias": "bullish"})
        assert result["confidence"] <= 75

    def test_atr_falls_back_to_a_price_ratio(self):
        """ATR が無ければ価格の 0.5% を代用すること"""
        ctx = {"price": 150.0, "buy_signals": 3, "sell_signals": 0, "volatility": {}}
        result = _rule_based_trading_fallback("USDJPY", ctx, {"sentiment": "bullish"},
                                              {"pair_bias": "bullish"})
        assert result["take_profit"] == pytest.approx(151.5)

    def test_error_detail_is_appended(self):
        """エラー内容を警告に含めること（原因追跡のため）"""
        result = _rule_based_trading_fallback("USDJPY", technical(), {}, {},
                                              error="rate limit exceeded")
        assert any("rate limit" in w for w in result["warnings"])


class TestMakeTradingDecision:
    """make_trading_decision() のテスト"""

    def _run(self, decision_side_effect=None):
        with patch("src.ai.analyzer._build_technical_context", return_value=technical()), \
             patch("src.ai.analyzer.analyze_news",
                   new=AsyncMock(return_value={"sentiment": "bullish", "summary": "x"})), \
             patch("src.ai.analyzer.analyze_fundamentals",
                   new=AsyncMock(return_value={"pair_bias": "bullish", "overview": "y"})), \
             patch("src.ai.analyzer._trading_decision_from_context",
                   side_effect=decision_side_effect or (lambda *a: {"action": "buy"})):
            return asyncio.run(make_trading_decision("USDJPY"))

    def test_returns_the_ai_decision(self):
        """OpenAI の判断をそのまま返すこと"""
        assert self._run()["action"] == "buy"

    def test_falls_back_on_openai_error(self):
        """OpenAI が失敗したらルールベースへフォールバックすること"""
        def boom(*args):
            raise ValueError("OpenAI API エラー")

        result = self._run(decision_side_effect=boom)

        assert result["fallback"] is True
        assert result["action"] in ("buy", "sell", "hold")


class TestAssessRisk:
    """assess_risk() のテスト"""

    def test_delegates_to_the_risk_context(self):
        """リスク評価をコンテキスト付きで呼ぶこと"""
        with patch("src.ai.analyzer._build_technical_context", return_value=technical()), \
             patch("src.ai.analyzer._risk_from_context",
                   return_value={"risk_level": "medium"}) as risk:
            result = asyncio.run(assess_risk("USDJPY", account_balance=50_000))

        assert result["risk_level"] == "medium"
        assert risk.call_args[0][2] == 50_000


class TestGenerateFullReport:
    """generate_full_report() のテスト"""

    def _run(self):
        with patch("src.ai.analyzer._build_technical_context",
                   return_value=technical()) as build, \
             patch("src.ai.analyzer.analyze_news",
                   new=AsyncMock(return_value={"sentiment": "bullish"})), \
             patch("src.ai.analyzer.analyze_fundamentals",
                   new=AsyncMock(return_value={"pair_bias": "bullish"})), \
             patch("src.ai.analyzer._trading_decision_from_context",
                   return_value={"action": "buy"}), \
             patch("src.ai.analyzer._risk_from_context",
                   return_value={"risk_level": "medium"}):
            return asyncio.run(generate_full_report("USDJPY")), build

    def test_aggregates_all_sections(self):
        """ニュース・ファンダ・売買判断・リスクを集約すること"""
        result, _ = self._run()

        assert set(result) >= {"symbol", "news", "fundamentals",
                               "trading_decision", "risk_management"}
        assert result["trading_decision"]["action"] == "buy"
        assert result["risk_management"]["risk_level"] == "medium"

    def test_technical_context_is_computed_once(self):
        """テクニカル分析は 1 回だけ実行して使い回すこと（重複 API 回避）"""
        _, build = self._run()
        build.assert_called_once()
