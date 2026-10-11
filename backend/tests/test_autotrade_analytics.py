"""運用パフォーマンス分析 — src.autotrade.analytics のテスト

実行ログ・注文・決済履歴の取得はモックへ差し替え、集計とヒント生成を検証する。
"""

from datetime import datetime, timezone
from unittest.mock import patch

import pytest

from src.autotrade.analytics import _maintenance_hint, build_performance


def run(decision="executed", action="buy", confidence=70.0, reason="") -> dict:
    """実行ログ 1 件を組み立てる。"""
    return {"decision": decision, "action": action, "confidence": confidence, "reason": reason}


def closed_position(pnl=10.0) -> dict:
    """決済済みポジション 1 件を組み立てる。"""
    return {"symbol": "USDJPY", "side": "buy", "units": 10_000,
            "entry_price": 150.0, "close_price": 151.0, "realized_pnl_usd": pnl,
            "closed_at": datetime.now(timezone.utc).isoformat()}


def perf(runs=None, orders=None, closed=None) -> dict:
    """依存をモックして build_performance() を呼ぶ。"""
    with patch("src.autotrade.analytics.list_runs", return_value=runs or []), \
         patch("src.autotrade.analytics.list_orders", return_value=orders or []), \
         patch("src.autotrade.analytics.list_closed_positions", return_value=closed or []):
        return build_performance(tenant_id=1)


class TestBuildPerformanceSummary:
    """build_performance() のサマリー集計テスト"""

    def test_returns_expected_sections(self):
        """主要セクションが揃っていること"""
        result = perf()
        assert set(result) == {
            "summary", "pnl", "broker_orders", "top_block_reasons",
            "recent_executed", "recent_closed", "maintenance_hint",
        }

    def test_counts_by_decision(self):
        """判定ごとの件数を数えること"""
        summary = perf(runs=[run("executed"), run("blocked"), run("blocked"),
                             run("skipped")])["summary"]

        assert summary["total_runs"] == 4
        assert summary["executed"] == 1
        assert summary["blocked"] == 2
        assert summary["skipped"] == 1

    def test_execution_rate(self):
        """約定率を百分率で返すこと"""
        summary = perf(runs=[run("executed"), run("blocked"),
                             run("blocked"), run("blocked")])["summary"]
        assert summary["execution_rate_pct"] == 25.0

    def test_execution_rate_without_runs(self):
        """ログが無くても 0 除算にならないこと"""
        assert perf()["summary"]["execution_rate_pct"] == 0.0

    def test_counts_buy_and_sell(self):
        """約定した売買方向を数えること"""
        summary = perf(runs=[run(action="buy"), run(action="buy"),
                             run(action="sell")])["summary"]

        assert summary["buy_trades"] == 2
        assert summary["sell_trades"] == 1

    def test_only_executed_runs_count_as_trades(self):
        """ブロックされたログは売買件数に含めないこと"""
        summary = perf(runs=[run("blocked", action="buy"), run("executed", action="buy")])["summary"]
        assert summary["buy_trades"] == 1

    def test_average_confidence(self):
        """約定時の平均信頼度を返すこと"""
        summary = perf(runs=[run(confidence=60.0), run(confidence=80.0)])["summary"]
        assert summary["avg_confidence"] == 70.0

    def test_average_confidence_ignores_missing_values(self):
        """信頼度が無いログは平均に含めないこと"""
        summary = perf(runs=[run(confidence=60.0), run(confidence=None)])["summary"]
        assert summary["avg_confidence"] == 60.0

    def test_average_confidence_without_trades(self):
        """約定が無ければ 0 を返すこと"""
        assert perf()["summary"]["avg_confidence"] == 0


class TestBlockReasons:
    """ブロック理由の集計テスト"""

    def test_counts_reasons(self):
        """理由ごとの件数を数えること"""
        result = perf(runs=[run("blocked", reason="信頼度不足"),
                            run("blocked", reason="信頼度不足"),
                            run("blocked", reason="イベント回避中")])

        counts = {item["reason"]: item["count"] for item in result["top_block_reasons"]}
        assert counts["信頼度不足"] == 2
        assert counts["イベント回避中"] == 1

    def test_sorted_by_frequency(self):
        """件数の多い順に並べること"""
        result = perf(runs=[run("blocked", reason="A"), run("blocked", reason="B"),
                            run("blocked", reason="B")])
        assert result["top_block_reasons"][0]["reason"] == "B"

    def test_limited_to_five(self):
        """上位 5 件までに絞ること"""
        runs = [run("blocked", reason=f"reason-{i}") for i in range(10)]
        assert len(perf(runs=runs)["top_block_reasons"]) == 5

    def test_reason_is_truncated(self):
        """長い理由は 40 文字に切り詰めること"""
        result = perf(runs=[run("blocked", reason="あ" * 100)])
        assert len(result["top_block_reasons"][0]["reason"]) == 40

    def test_missing_reason_becomes_unknown(self):
        """理由が空なら unknown として集計すること"""
        result = perf(runs=[run("blocked", reason=None)])
        assert result["top_block_reasons"][0]["reason"] == "unknown"


class TestPnlSection:
    """PnL セクションのテスト"""

    def test_includes_aggregate_and_weekly(self):
        """集計値と週次内訳を含むこと"""
        pnl = perf(closed=[closed_position(50.0)])["pnl"]

        assert pnl["total_realized_usd"] == 50.0
        assert pnl["closed_trades"] == 1
        assert len(pnl["weekly"]) == 4

    def test_zero_when_no_positions(self):
        """決済履歴が無ければゼロになること"""
        assert perf()["pnl"]["total_realized_usd"] == 0.0


class TestRecentLists:
    """直近リストのテスト"""

    def test_recent_executed_is_capped_at_ten(self):
        """直近の約定は 10 件までに絞ること"""
        assert len(perf(runs=[run() for _ in range(25)])["recent_executed"]) == 10

    def test_recent_closed_is_capped_at_ten(self):
        """直近の決済も 10 件までに絞ること"""
        assert len(perf(closed=[closed_position() for _ in range(25)])["recent_closed"]) == 10

    def test_broker_order_count(self):
        """ブローカー注文の件数を返すこと"""
        assert perf(orders=[{"id": 1}, {"id": 2}])["broker_orders"] == 2


class TestMaintenanceHint:
    """_maintenance_hint() のテスト"""

    def test_many_blocks_suggests_loosening(self):
        """約定ゼロでブロック多数なら条件緩和を促すこと"""
        assert "ブロックが多い" in _maintenance_hint(executed=0, blocked=10,
                                                     avg_conf=0, total_pnl=0)

    def test_low_confidence_suggests_conservative_preset(self):
        """平均信頼度が低ければ安定型プリセットを勧めること"""
        hint = _maintenance_hint(executed=3, blocked=0, avg_conf=55, total_pnl=0)
        assert "安定型" in hint

    def test_losses_suggest_review(self):
        """損失が出ていれば見直しを促すこと"""
        hint = _maintenance_hint(executed=6, blocked=0, avg_conf=70, total_pnl=-120.0)
        assert "見直し" in hint
        assert "-120.0" in hint

    def test_active_operation_suggests_weekly_review(self):
        """十分に稼働していれば週次レビューを促すこと"""
        hint = _maintenance_hint(executed=15, blocked=0, avg_conf=70, total_pnl=100.0)
        assert "週1回" in hint

    def test_onboarding_hint_for_new_users(self):
        """実績が少なければ導入手順を案内すること"""
        hint = _maintenance_hint(executed=0, blocked=0, avg_conf=0, total_pnl=0)
        assert "ドライラン評価" in hint

    def test_block_rule_takes_priority(self):
        """ブロック多数の診断が他より優先されること"""
        hint = _maintenance_hint(executed=0, blocked=20, avg_conf=10, total_pnl=-500)
        assert "ブロックが多い" in hint

    def test_hint_is_always_a_non_empty_string(self):
        """どの条件でも何らかの助言を返すこと"""
        for args in [(0, 0, 0, 0), (5, 5, 65, 10), (100, 0, 90, 1000)]:
            assert _maintenance_hint(*args).strip()
