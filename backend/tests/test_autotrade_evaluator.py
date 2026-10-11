"""自動売買のシグナル統合・リスクガード — src.autotrade.evaluator のテスト

外部データ取得と DB 参照はモックへ差し替え、
シグナル統合の加重計算・リスク判定・注文サイズ算出を検証する。
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from src.autotrade.evaluator import (
    ACTION_SCORE,
    SOURCE_WEIGHTS,
    _normalize_action,
    check_risk_guards,
    compute_order_size,
    fuse_signals,
)
from src.autotrade.models import DEFAULT_CONFIG


def context(ai="hold", technical="hold", intelligence="hold", mtf="hold",
            confidence=80, price=150.0, atr=0.9) -> dict:
    """シグナル統合用のコンテキストを組み立てる。"""
    def src(action):
        return {"action": action, "confidence": confidence}

    return {
        "ai": src(ai), "technical": src(technical),
        "intelligence": src(intelligence), "mtf": src(mtf),
        "price": price, "atr": atr,
    }


def config(**overrides) -> dict:
    """自動売買設定を組み立てる。"""
    return {**DEFAULT_CONFIG, **overrides}


class TestNormalizeAction:
    """_normalize_action() のテスト"""

    @pytest.mark.parametrize("raw", ["buy", "BUY", "long", "go long", "bullish", "strong_buy"])
    def test_buy_synonyms(self, raw):
        """買いを表す多様な表現を buy へ正規化すること"""
        assert _normalize_action(raw) == "buy"

    @pytest.mark.parametrize("raw", ["sell", "SELL", "short", "bearish", "strong_sell"])
    def test_sell_synonyms(self, raw):
        """売りを表す多様な表現を sell へ正規化すること"""
        assert _normalize_action(raw) == "sell"

    @pytest.mark.parametrize("raw", ["hold", "neutral", "wait", "", None, "unknown"])
    def test_everything_else_is_hold(self, raw):
        """判断できない表現は hold にフォールバックすること"""
        assert _normalize_action(raw) == "hold"


class TestSourceWeights:
    """加重テーブルのテスト"""

    def test_ai_has_the_highest_weight(self):
        """AI シグナルの加重が最も大きいこと"""
        assert SOURCE_WEIGHTS["ai"] == max(SOURCE_WEIGHTS.values())

    def test_weights_are_positive(self):
        """すべての加重が正であること"""
        assert all(w > 0 for w in SOURCE_WEIGHTS.values())

    def test_action_scores_are_symmetric(self):
        """買いと売りのスコアが対称であること"""
        assert ACTION_SCORE["buy"] == -ACTION_SCORE["sell"]
        assert ACTION_SCORE["hold"] == 0.0


class TestFuseSignals:
    """fuse_signals() のテスト"""

    def test_returns_expected_keys(self):
        """統合結果のキーが揃っていること"""
        assert set(fuse_signals(context(), config())) == {
            "action", "confidence", "score", "breakdown", "context",
        }

    def test_unanimous_buy(self):
        """全ソースが買いなら buy になること"""
        result = fuse_signals(context(ai="buy", technical="buy",
                                      intelligence="buy", mtf="buy"), config())
        assert result["action"] == "buy"
        assert result["score"] == pytest.approx(1.0)

    def test_unanimous_sell(self):
        """全ソースが売りなら sell になること"""
        result = fuse_signals(context(ai="sell", technical="sell",
                                      intelligence="sell", mtf="sell"), config())
        assert result["action"] == "sell"
        assert result["score"] == pytest.approx(-1.0)

    def test_all_hold_is_hold(self):
        """全ソースが hold なら hold になること"""
        assert fuse_signals(context(), config())["action"] == "hold"

    def test_conflicting_signals_cancel_out(self):
        """同じ加重の買いと売りが拮抗すれば hold になること"""
        cfg = config(sources=["technical", "intelligence"])
        # technical(0.25) と intelligence(0.20) では加重が異なるため、
        # 同一加重になるよう信頼度で調整して打ち消し合う状況を作る
        ctx = context(technical="buy", intelligence="sell")
        ctx["technical"]["confidence"] = 40   # 0.25 × 0.40 = 0.10
        ctx["intelligence"]["confidence"] = 50  # 0.20 × 0.50 = 0.10

        assert fuse_signals(ctx, cfg)["action"] == "hold"

    def test_ai_outweighs_lower_weighted_sources(self):
        """加重の大きい AI が小さいソースを上回ること"""
        result = fuse_signals(context(ai="buy", mtf="sell"), config())
        assert result["action"] == "buy"

    def test_only_configured_sources_are_used(self):
        """設定で選ばれたソースのみを使うこと"""
        result = fuse_signals(context(ai="buy", technical="sell"),
                              config(sources=["technical"]))

        assert result["action"] == "sell"
        assert {b["source"] for b in result["breakdown"]} == {"technical"}

    def test_unknown_sources_are_ignored(self):
        """未知のソース名は無視すること"""
        result = fuse_signals(context(ai="buy"), config(sources=["ai", "astrology"]))
        assert {b["source"] for b in result["breakdown"]} == {"ai"}

    def test_confidence_is_bounded(self):
        """信頼度は 30〜95 に収まること"""
        strong = fuse_signals(context(ai="buy", technical="buy", intelligence="buy",
                                      mtf="buy", confidence=100), config())
        weak = fuse_signals(context(confidence=0), config())

        assert 30 <= strong["confidence"] <= 95
        assert 30 <= weak["confidence"] <= 95

    def test_stronger_agreement_raises_confidence(self):
        """一致度が高いほど信頼度が上がること"""
        unanimous = fuse_signals(context(ai="buy", technical="buy",
                                         intelligence="buy", mtf="buy"), config())
        partial = fuse_signals(context(ai="buy"), config())
        assert unanimous["confidence"] >= partial["confidence"]

    def test_breakdown_lists_each_vote(self):
        """各ソースの投票内容を内訳として返すこと"""
        breakdown = fuse_signals(context(ai="buy", technical="sell"), config())["breakdown"]
        by_source = {b["source"]: b["action"] for b in breakdown}

        assert by_source["ai"] == "buy"
        assert by_source["technical"] == "sell"

    def test_tradingview_signal_is_counted_when_enabled(self):
        """TradingView シグナルは設定が有効なときのみ加算されること"""
        cfg = config(sources=["mtf"], auto_execute_tradingview=True)
        result = fuse_signals(context(), cfg, tv_signal={"action": "buy"})

        assert "tradingview" in {b["source"] for b in result["breakdown"]}

    def test_tradingview_signal_is_ignored_when_disabled(self):
        """設定が無効なら TradingView シグナルを無視すること"""
        cfg = config(auto_execute_tradingview=False)
        result = fuse_signals(context(), cfg, tv_signal={"action": "buy"})

        assert "tradingview" not in {b["source"] for b in result["breakdown"]}

    def test_empty_sources_fall_back_to_all(self):
        """ソース未指定（空リスト）は全ソースを使う扱いになること

        `config.get("sources") or list(SOURCE_WEIGHTS)` のため、空リストは
        「指定なし」と同義であり、全ソースの加重投票が行われる。
        """
        result = fuse_signals(context(ai="buy"), config(sources=[]))
        assert {b["source"] for b in result["breakdown"]} == set(SOURCE_WEIGHTS) - {"tradingview"}
        assert result["action"] == "buy"

    def test_unmatched_sources_yield_hold(self):
        """設定されたソースがどれも存在しなければ hold になること（0 除算も起きない）"""
        result = fuse_signals(context(ai="buy"), config(sources=["astrology"]))
        assert result["action"] == "hold"
        assert result["score"] == 0.0

    def test_context_is_passed_through(self):
        """統合結果に元のコンテキストを含めること"""
        ctx = context(ai="buy")
        assert fuse_signals(ctx, config())["context"] is ctx


class TestCheckRiskGuards:
    """check_risk_guards() のテスト"""

    def _check(self, fused, cfg=None, alerts=None, today=0, last=None, has_position=False):
        with patch("src.autotrade.evaluator.get_event_alerts", return_value=alerts or []), \
             patch("src.autotrade.evaluator.count_today_trades", return_value=today), \
             patch("src.autotrade.evaluator.last_executed_at", return_value=last), \
             patch("src.autotrade.evaluator.has_open_position", return_value=has_position):
            return check_risk_guards("USDJPY", cfg or config(), 1, fused)

    def fused(self, action="buy", confidence=80, mtf="buy") -> dict:
        """統合済みシグナルを組み立てる。"""
        return {"action": action, "confidence": confidence,
                "context": {"mtf": {"action": mtf}}}

    def test_passes_when_all_checks_are_satisfied(self):
        """すべての条件を満たせば通過すること"""
        passed, reason = self._check(self.fused(),
                                     config(event_blackout_hours=0, require_mtf_alignment=False))
        assert passed is True
        assert reason == "リスクチェック通過"

    def test_hold_signal_is_blocked(self):
        """hold ではエントリーしないこと"""
        passed, reason = self._check(self.fused(action="hold"))
        assert passed is False
        assert "hold" in reason

    def test_low_confidence_is_blocked(self):
        """信頼度が閾値未満ならブロックすること"""
        passed, reason = self._check(self.fused(confidence=50), config(min_confidence=65))
        assert passed is False
        assert "信頼度" in reason

    def test_mtf_mismatch_is_blocked(self):
        """MTF と方向が食い違えばブロックすること"""
        passed, reason = self._check(self.fused(action="buy", mtf="sell"),
                                     config(require_mtf_alignment=True))
        assert passed is False
        assert "MTF" in reason

    def test_mtf_hold_does_not_block(self):
        """MTF が hold なら不一致とみなさないこと"""
        passed, _ = self._check(self.fused(action="buy", mtf="hold"),
                                config(require_mtf_alignment=True, event_blackout_hours=0))
        assert passed is True

    def test_mtf_check_can_be_disabled(self):
        """設定で MTF 一致を要求しないこともできること"""
        passed, _ = self._check(self.fused(action="buy", mtf="sell"),
                                config(require_mtf_alignment=False, event_blackout_hours=0))
        assert passed is True

    def test_event_blackout_blocks(self):
        """高影響イベントが近ければブロックすること"""
        passed, reason = self._check(self.fused(),
                                     config(require_mtf_alignment=False,
                                            event_blackout_hours=8),
                                     alerts=[{"title": "米国雇用統計"}])
        assert passed is False
        assert "米国雇用統計" in reason

    def test_event_blackout_can_be_disabled(self):
        """ブラックアウト時間 0 ならイベントを確認しないこと"""
        with patch("src.autotrade.evaluator.get_event_alerts") as get_alerts, \
             patch("src.autotrade.evaluator.count_today_trades", return_value=0), \
             patch("src.autotrade.evaluator.last_executed_at", return_value=None), \
             patch("src.autotrade.evaluator.has_open_position", return_value=False):
            check_risk_guards("USDJPY",
                              config(require_mtf_alignment=False, event_blackout_hours=0),
                              1, self.fused())

        get_alerts.assert_not_called()

    def test_daily_limit_blocks(self):
        """日次取引上限に達していればブロックすること"""
        passed, reason = self._check(self.fused(),
                                     config(require_mtf_alignment=False,
                                            event_blackout_hours=0, max_daily_trades=3),
                                     today=3)
        assert passed is False
        assert "取引上限" in reason

    def test_cooldown_blocks(self):
        """クールダウン中はブロックすること"""
        recent = datetime.now(timezone.utc) - timedelta(minutes=10)
        passed, reason = self._check(self.fused(),
                                     config(require_mtf_alignment=False,
                                            event_blackout_hours=0, cooldown_minutes=60),
                                     last=recent)
        assert passed is False
        assert "クールダウン" in reason

    def test_cooldown_expires(self):
        """クールダウンを過ぎていれば通過すること"""
        old = datetime.now(timezone.utc) - timedelta(minutes=120)
        passed, _ = self._check(self.fused(),
                                config(require_mtf_alignment=False,
                                       event_blackout_hours=0, cooldown_minutes=60),
                                last=old)
        assert passed is True

    def test_existing_position_blocks(self):
        """同一通貨の建玉があればブロックすること（ナンピン禁止）"""
        passed, reason = self._check(self.fused(),
                                     config(require_mtf_alignment=False,
                                            event_blackout_hours=0,
                                            allow_add_to_position=False),
                                     has_position=True)
        assert passed is False
        assert "オープンポジション" in reason

    def test_adding_to_position_can_be_allowed(self):
        """設定で追加エントリーを許可できること"""
        passed, _ = self._check(self.fused(),
                                config(require_mtf_alignment=False, event_blackout_hours=0,
                                       allow_add_to_position=True),
                                has_position=True)
        assert passed is True


class TestComputeOrderSize:
    """compute_order_size() のテスト"""

    def _size(self, side="buy", cfg=None, symbol="USDJPY", price=150.0):
        with patch("src.autotrade.evaluator.get_account_summary",
                   return_value={"balance": 10_000}):
            return compute_order_size(symbol, cfg or config(), context(price=price), side,
                                      tenant_id=1)

    def test_returns_expected_keys(self):
        """注文情報のキーが揃っていること"""
        assert set(self._size()) >= {
            "units", "lots", "sizing", "account_balance", "side",
            "entry_price", "stop_loss", "take_profit", "stop_pips", "risk_reward",
        }

    def test_units_respect_the_minimum(self):
        """最小ユニット数を下回らないこと"""
        assert self._size(cfg=config(min_units=5000))["units"] >= 5000

    def test_lots_are_clamped_to_configured_bounds(self):
        """ロット数が設定の上下限に収まること"""
        result = self._size(cfg=config(min_lots=0.02, max_lots=0.5))
        assert 0.02 <= result["lots"] <= 0.5

    def test_buy_places_stop_below_and_target_above(self):
        """買いでは SL が現在値より下、TP が上に来ること"""
        result = self._size(side="buy", price=150.0)
        assert result["stop_loss"] < 150.0 < result["take_profit"]

    def test_sell_places_stop_above_and_target_below(self):
        """売りでは SL が現在値より上、TP が下に来ること"""
        result = self._size(side="sell", price=150.0)
        assert result["take_profit"] < 150.0 < result["stop_loss"]

    def test_risk_reward_ratio_is_applied(self):
        """TP 距離が SL 距離 × RR 比になること"""
        result = self._size(side="buy", cfg=config(risk_reward=3.0), price=150.0)
        sl_distance = result["entry_price"] - result["stop_loss"]
        tp_distance = result["take_profit"] - result["entry_price"]

        assert tp_distance == pytest.approx(sl_distance * 3.0, rel=0.01)

    def test_stop_loss_can_be_disabled(self):
        """SL を使わない設定なら None になること"""
        assert self._size(cfg=config(use_stop_loss=False))["stop_loss"] is None

    def test_take_profit_can_be_disabled(self):
        """TP を使わない設定なら None になること"""
        assert self._size(cfg=config(use_take_profit=False))["take_profit"] is None

    def test_uses_the_configured_balance(self):
        """設定の口座残高を使うこと"""
        assert self._size(cfg=config(account_balance=50_000))["account_balance"] == 50_000

    def test_falls_back_to_broker_balance(self):
        """設定に残高が無ければブローカーの残高を使うこと"""
        with patch("src.autotrade.evaluator.get_account_summary",
                   return_value={"balance": 33_333}):
            result = compute_order_size("USDJPY", config(account_balance=None),
                                        context(), "buy", tenant_id=1)

        assert result["account_balance"] == 33_333

    def test_jpy_pair_prices_are_rounded_to_three_decimals(self):
        """JPY ペアの SL / TP は小数 3 桁に丸めること"""
        result = self._size(symbol="USDJPY", price=150.0)
        assert result["stop_loss"] == round(result["stop_loss"], 3)

    def test_larger_balance_yields_larger_orders(self):
        """残高が大きいほど注文サイズが増えること"""
        small = self._size(cfg=config(account_balance=10_000, max_lots=100))
        large = self._size(cfg=config(account_balance=100_000, max_lots=100))
        assert large["units"] > small["units"]
