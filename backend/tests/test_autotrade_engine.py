"""自動売買エンジン — src.autotrade.engine のテスト

シグナル収集・リスク判定・ブローカー発注・分散ロックはすべてモックへ差し替え、
判定フロー（decision の決まり方）と安全機構を検証する。
"""

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from src.autotrade.engine import _result, _tenant_lock_name, evaluate_symbol
from src.autotrade.models import DEFAULT_CONFIG


def config(**overrides) -> dict:
    """自動売買設定を組み立てる。"""
    return {**DEFAULT_CONFIG, "enabled": True, **overrides}


def fused(action="buy", confidence=80) -> dict:
    """統合済みシグナルを組み立てる。"""
    return {"action": action, "confidence": confidence, "breakdown": [],
            "context": {"mtf": {"action": action}}}


def evaluate(cfg=None, signal=None, guard=(True, "リスクチェック通過"),
             lock_token="token", dry_run=True, execute_result=None, **kwargs):
    """依存をモックして evaluate_symbol() を実行する。"""
    order_plan = {"units": 1000, "side": "buy", "stop_loss": 149.0, "take_profit": 152.0}
    with patch("src.autotrade.engine.get_config", return_value=cfg or config()), \
         patch("src.autotrade.engine.gather_signal_context",
               new=AsyncMock(return_value={"price": 150.0, "mtf": {"action": "buy"}})), \
         patch("src.autotrade.engine.fuse_signals", return_value=signal or fused()), \
         patch("src.autotrade.engine.check_risk_guards", return_value=guard), \
         patch("src.autotrade.engine.compute_order_size", return_value=order_plan), \
         patch("src.autotrade.engine.try_acquire_lock", return_value=lock_token), \
         patch("src.autotrade.engine.release_lock"), \
         patch("src.autotrade.engine.execute_order",
               new=AsyncMock(return_value=execute_result or {"decision": "executed"})) as execute:
        result = asyncio.run(evaluate_symbol("USDJPY", tenant_id=1, dry_run=dry_run, **kwargs))
        return result, execute


class TestTenantLockName:
    """_tenant_lock_name() のテスト"""

    def test_includes_the_tenant_id(self):
        """テナントごとに別のロック名になること"""
        assert _tenant_lock_name(1) != _tenant_lock_name(2)

    def test_handles_missing_tenant(self):
        """テナント未指定でもロック名を返すこと"""
        assert isinstance(_tenant_lock_name(None), str)


class TestResultHelper:
    """_result() のテスト"""

    def test_returns_the_standard_shape(self):
        """統一フォーマットの結果を返すこと"""
        result = _result("usdjpy", "ready", "buy", 70, "ok", {}, tenant_id=1)

        assert result["symbol"] == "USDJPY"
        assert result["decision"] == "ready"
        assert result["action"] == "buy"
        assert result["confidence"] == 70
        assert result["reason"] == "ok"

    def test_attaches_the_order_plan_to_the_snapshot(self):
        """注文プランをスナップショットへ含めること"""
        snapshot = {}
        plan = {"units": 1000}
        _result("USDJPY", "ready", "buy", 70, "ok", snapshot, 1, order_plan=plan)
        assert snapshot["order_plan"] is plan

    def test_existing_snapshot_plan_is_kept(self):
        """既にスナップショットにプランがあれば上書きしないこと"""
        snapshot = {"order_plan": {"units": 5}}
        _result("USDJPY", "ready", "buy", 70, "ok", snapshot, 1, order_plan={"units": 1000})
        assert snapshot["order_plan"] == {"units": 5}


class TestEvaluateSymbolDecisions:
    """evaluate_symbol() の判定テスト"""

    def test_dry_run_ready_when_all_checks_pass(self):
        """ドライランで条件を満たせば ready になること"""
        result, execute = evaluate()

        assert result["decision"] == "ready"
        assert result["action"] == "buy"
        execute.assert_not_called()

    def test_hold_signal_is_skipped(self):
        """hold シグナルは skipped になること"""
        result, _ = evaluate(signal=fused(action="hold"))
        assert result["decision"] == "skipped"

    def test_failed_guard_is_blocked(self):
        """リスクガードで弾かれたら blocked になること"""
        result, _ = evaluate(guard=(False, "信頼度不足"))

        assert result["decision"] == "blocked"
        assert result["reason"] == "信頼度不足"

    def test_disabled_autotrade_blocks_live_runs(self):
        """自動取引が無効なら本番実行は disabled になること"""
        result, execute = evaluate(cfg=config(enabled=False), dry_run=False)

        assert result["decision"] == "disabled"
        execute.assert_not_called()

    def test_disabled_autotrade_still_allows_dry_run(self):
        """無効でもドライラン評価はできること（設定確認のため）"""
        result, _ = evaluate(cfg=config(enabled=False), dry_run=True)
        assert result["decision"] != "disabled"

    def test_live_run_places_the_order(self):
        """本番実行では発注処理を呼ぶこと"""
        result, execute = evaluate(dry_run=False)

        execute.assert_awaited_once()
        assert result["decision"] == "executed"

    def test_order_plan_is_included_when_ready(self):
        """実行可能なときは注文プランを添えること"""
        result, _ = evaluate()
        assert result["signal_snapshot"]["order_plan"]["units"] == 1000

    def test_no_order_plan_when_blocked(self):
        """ブロック時は注文プランを作らないこと"""
        result, _ = evaluate(guard=(False, "クールダウン中"))
        assert result["signal_snapshot"]["order_plan"] is None

    def test_snapshot_records_the_guard_reason(self):
        """判定理由をスナップショットに残すこと（監査用）"""
        result, _ = evaluate(guard=(False, "イベント回避中"))
        assert result["signal_snapshot"]["guard_reason"] == "イベント回避中"

    def test_snapshot_records_the_price(self):
        """評価時の価格を残すこと"""
        result, _ = evaluate()
        assert result["signal_snapshot"]["price"] == 150.0


class TestEvaluateSymbolLocking:
    """分散ロックによる多重実行防止のテスト"""

    def test_dry_run_does_not_take_the_lock(self):
        """ドライランではロックを取らないこと"""
        with patch("src.autotrade.engine.get_config", return_value=config()), \
             patch("src.autotrade.engine.gather_signal_context",
                   new=AsyncMock(return_value={"price": 150.0})), \
             patch("src.autotrade.engine.fuse_signals", return_value=fused()), \
             patch("src.autotrade.engine.check_risk_guards", return_value=(True, "ok")), \
             patch("src.autotrade.engine.compute_order_size", return_value={"units": 1000}), \
             patch("src.autotrade.engine.try_acquire_lock") as acquire:
            asyncio.run(evaluate_symbol("USDJPY", tenant_id=1, dry_run=True))

        acquire.assert_not_called()

    def test_live_run_takes_the_lock(self):
        """本番実行ではロックを取得すること"""
        with patch("src.autotrade.engine.get_config", return_value=config()), \
             patch("src.autotrade.engine.gather_signal_context",
                   new=AsyncMock(return_value={"price": 150.0})), \
             patch("src.autotrade.engine.fuse_signals", return_value=fused()), \
             patch("src.autotrade.engine.check_risk_guards", return_value=(True, "ok")), \
             patch("src.autotrade.engine.compute_order_size", return_value={"units": 1000}), \
             patch("src.autotrade.engine.try_acquire_lock", return_value="token") as acquire, \
             patch("src.autotrade.engine.release_lock"), \
             patch("src.autotrade.engine.execute_order",
                   new=AsyncMock(return_value={"decision": "executed"})):
            asyncio.run(evaluate_symbol("USDJPY", tenant_id=1, dry_run=False))

        acquire.assert_called_once()

    def test_blocked_when_another_instance_holds_the_lock(self):
        """他インスタンスが処理中なら発注せず blocked にすること"""
        result, execute = evaluate(dry_run=False, lock_token=None)

        assert result["decision"] == "blocked"
        assert "別インスタンス" in result["reason"]
        execute.assert_not_called()

    def test_lock_is_released_after_execution(self):
        """処理後にロックを解放すること"""
        with patch("src.autotrade.engine.get_config", return_value=config()), \
             patch("src.autotrade.engine.gather_signal_context",
                   new=AsyncMock(return_value={"price": 150.0})), \
             patch("src.autotrade.engine.fuse_signals", return_value=fused()), \
             patch("src.autotrade.engine.check_risk_guards", return_value=(True, "ok")), \
             patch("src.autotrade.engine.compute_order_size", return_value={"units": 1000}), \
             patch("src.autotrade.engine.try_acquire_lock", return_value="token"), \
             patch("src.autotrade.engine.release_lock") as release, \
             patch("src.autotrade.engine.execute_order",
                   new=AsyncMock(return_value={"decision": "executed"})):
            asyncio.run(evaluate_symbol("USDJPY", tenant_id=1, dry_run=False))

        release.assert_called_once()

    def test_lock_is_released_even_on_error(self):
        """発注中に例外が起きてもロックを解放すること"""
        with patch("src.autotrade.engine.get_config", return_value=config()), \
             patch("src.autotrade.engine.gather_signal_context",
                   new=AsyncMock(return_value={"price": 150.0})), \
             patch("src.autotrade.engine.fuse_signals", return_value=fused()), \
             patch("src.autotrade.engine.check_risk_guards", return_value=(True, "ok")), \
             patch("src.autotrade.engine.compute_order_size", return_value={"units": 1000}), \
             patch("src.autotrade.engine.try_acquire_lock", return_value="token"), \
             patch("src.autotrade.engine.release_lock") as release, \
             patch("src.autotrade.engine.execute_order",
                   new=AsyncMock(side_effect=RuntimeError("broker down"))):
            with pytest.raises(RuntimeError):
                asyncio.run(evaluate_symbol("USDJPY", tenant_id=1, dry_run=False))

        release.assert_called_once()


class TestEvaluateSymbolTradingViewSignal:
    """TradingView シグナル連携のテスト"""

    def test_signal_is_passed_to_the_fusion(self):
        """受け取った Webhook シグナルを統合処理へ渡すこと"""
        tv = {"action": "buy", "price": 150.0}
        with patch("src.autotrade.engine.get_config", return_value=config()), \
             patch("src.autotrade.engine.gather_signal_context",
                   new=AsyncMock(return_value={"price": 150.0})), \
             patch("src.autotrade.engine.fuse_signals", return_value=fused()) as fuse, \
             patch("src.autotrade.engine.check_risk_guards", return_value=(True, "ok")), \
             patch("src.autotrade.engine.compute_order_size", return_value={"units": 1000}):
            asyncio.run(evaluate_symbol("USDJPY", tenant_id=1, tv_signal=tv, dry_run=True))

        assert fuse.call_args[0][2] is tv
