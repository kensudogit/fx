"""AI トレードコーチング — src.ai.coaching のテスト"""

import asyncio
from unittest.mock import patch

import pytest

from src.ai.coaching import _order_stats, _rule_coaching, generate_coaching


def order(symbol="USDJPY", side="buy", status="FILLED", units=1000) -> dict:
    """注文履歴 1 件を組み立てる。"""
    return {"symbol": symbol, "side": side, "units": units, "status": status,
            "fill_price": 150.0, "created_at": "2026-01-01T00:00:00Z"}


class TestOrderStats:
    """_order_stats() のテスト"""

    def test_empty_history(self):
        """履歴が無ければ件数 0 とメッセージを返すこと"""
        assert _order_stats([]) == {"total": 0, "message": "取引履歴がありません"}

    def test_counts_orders(self):
        """総数と約定数を数えること"""
        stats = _order_stats([order(), order(status="PENDING"), order()])

        assert stats["total"] == 3
        assert stats["filled"] == 2

    def test_counts_by_side(self):
        """売買方向ごとの件数を数えること"""
        stats = _order_stats([order(side="buy"), order(side="buy"), order(side="sell")])

        assert stats["buy_count"] == 2
        assert stats["sell_count"] == 1

    def test_counts_by_symbol(self):
        """通貨ペアごとの取引数を集計すること"""
        stats = _order_stats([order(symbol="USDJPY"), order(symbol="EURUSD"),
                              order(symbol="USDJPY")])
        assert stats["symbols_traded"] == {"USDJPY": 2, "EURUSD": 1}

    def test_recent_is_capped_at_ten(self):
        """直近の履歴は 10 件までに絞ること"""
        assert len(_order_stats([order() for _ in range(25)])["recent"]) == 10


class TestRuleCoaching:
    """_rule_coaching() のテスト"""

    def test_no_history_encourages_paper_trading(self):
        """履歴が無ければペーパー取引から始めるよう促すこと"""
        result = _rule_coaching({"total": 0})

        assert "ペーパー取引" in result["overall_assessment"]
        assert result["risk_discipline_score"] == 50

    def test_detects_a_buy_bias(self):
        """買い偏重を検出すること"""
        result = _rule_coaching({"total": 10, "buy_count": 9, "sell_count": 1})
        assert "買い偏重" in result["overall_assessment"]

    def test_detects_a_sell_bias(self):
        """売り偏重を検出すること"""
        result = _rule_coaching({"total": 10, "buy_count": 1, "sell_count": 9})
        assert "売り偏重" in result["overall_assessment"]

    def test_balanced_trading_is_recognised(self):
        """売買が均衡していればバランス型と評価すること"""
        result = _rule_coaching({"total": 10, "buy_count": 5, "sell_count": 5})
        assert "バランス型" in result["overall_assessment"]

    def test_always_returns_actionable_advice(self):
        """具体的な助言と次の焦点を返すこと"""
        result = _rule_coaching({"total": 10, "buy_count": 5, "sell_count": 5})

        assert len(result["recommendations"]) >= 1
        assert result["next_focus"]

    def test_mentions_risk_limits(self):
        """リスク管理の基本（1〜2% ルール）に触れること"""
        advice = " ".join(_rule_coaching({"total": 5, "buy_count": 3, "sell_count": 2})
                          ["recommendations"])
        assert "1-2%" in advice

    def test_score_is_bounded(self):
        """規律スコアは 0〜100 に収まること"""
        for stats in ({"total": 0}, {"total": 10, "buy_count": 5, "sell_count": 5}):
            assert 0 <= _rule_coaching(stats)["risk_discipline_score"] <= 100


class TestGenerateCoaching:
    """generate_coaching() のテスト"""

    def _run(self, orders=None, api_key="", ai_result=None, ai_error=None, symbol="USDJPY"):
        patches = {
            "src.ai.coaching.list_orders": orders if orders is not None else [order()],
            "src.ai.coaching.resolve_openai_api_key": api_key,
        }
        with patch("src.ai.coaching.list_orders", return_value=patches[
                "src.ai.coaching.list_orders"]), \
             patch("src.ai.coaching.resolve_openai_api_key", return_value=api_key), \
             patch("src.ai.coaching.chat_json",
                   side_effect=ai_error,
                   return_value=ai_result or {"overall_assessment": "良好"}):
            return asyncio.run(generate_coaching(symbol))

    def test_normalizes_the_symbol(self):
        """シンボルを大文字化すること"""
        assert self._run(symbol="usdjpy")["symbol"] == "USDJPY"

    def test_uses_rule_coaching_without_an_api_key(self):
        """API キーが無ければルールベースの助言を返すこと"""
        result = self._run(api_key="")

        assert result["coaching"]["risk_discipline_score"] in (50, 60)
        assert "coaching_error" not in result

    def test_uses_openai_when_available(self):
        """API キーがあれば OpenAI の結果を使うこと"""
        result = self._run(api_key="sk-test", ai_result={"overall_assessment": "AI 評価"})
        assert result["coaching"]["overall_assessment"] == "AI 評価"

    def test_falls_back_when_openai_fails(self):
        """OpenAI が失敗したらルールベースへフォールバックし、原因を残すこと"""
        result = self._run(api_key="sk-test", ai_error=RuntimeError("rate limit"))

        assert result["coaching"]["risk_discipline_score"] in (50, 60)
        assert "rate limit" in result["coaching_error"]

    def test_filters_orders_by_symbol(self):
        """指定シンボルの取引に絞って分析すること"""
        orders = [order(symbol="USDJPY"), order(symbol="EURUSD"), order(symbol="EURUSD")]
        result = self._run(orders=orders, symbol="EURUSD")

        assert result["trade_stats"]["total"] == 2

    def test_falls_back_to_all_orders_when_symbol_has_none(self):
        """該当シンボルの取引が無ければ全体の履歴で分析すること"""
        orders = [order(symbol="USDJPY"), order(symbol="USDJPY")]
        result = self._run(orders=orders, symbol="GBPUSD")

        assert result["trade_stats"]["total"] == 2

    def test_includes_trade_stats(self):
        """取引統計を結果に含めること"""
        assert "trade_stats" in self._run()

    def test_history_is_sent_to_the_model(self):
        """直近の取引履歴をプロンプトへ渡すこと"""
        with patch("src.ai.coaching.list_orders", return_value=[order()]), \
             patch("src.ai.coaching.resolve_openai_api_key", return_value="sk-test"), \
             patch("src.ai.coaching.chat_json", return_value={}) as chat:
            asyncio.run(generate_coaching("USDJPY"))

        user_prompt = chat.call_args[0][1]
        assert "USDJPY" in user_prompt
        assert "buy" in user_prompt

    def test_empty_history_is_handled(self):
        """取引履歴が空でも例外にならないこと"""
        result = self._run(orders=[])
        assert result["trade_stats"]["total"] == 0
