"""分散ロック・PnL のテスト"""

from datetime import datetime, timezone

from src.autotrade.pnl import aggregate_pnl, calc_realized_pnl_usd, weekly_pnl_breakdown
from src.infra.distributed_lock import lock_status, release_lock, try_acquire_lock


class TestDistributedLockPnl:
    """分散ロック・PnL モジュールのテストクラス"""

    def test_calc_realized_pnl_usdjpy_buy(self):
        pnl = calc_realized_pnl_usd("USDJPY", "buy", 10000, 150.00, 150.50)
        assert pnl > 0

    def test_calc_realized_pnl_usdjpy_sell_loss(self):
        pnl = calc_realized_pnl_usd("USDJPY", "sell", 10000, 150.00, 150.50)
        assert pnl < 0

    def test_aggregate_pnl(self):
        closed = [
            {"realized_pnl_usd": 50.0},
            {"realized_pnl_usd": -20.0},
            {"realized_pnl_usd": 30.0},
        ]
        agg = aggregate_pnl(closed)
        assert agg["total_realized_usd"] == 60.0
        assert agg["wins"] == 2
        assert agg["losses"] == 1

    def test_weekly_pnl_breakdown(self):
        now = datetime.now(timezone.utc).isoformat()
        closed = [
            {
                "closed_at": now,
                "symbol": "USDJPY",
                "side": "buy",
                "units": 1000,
                "entry_price": 150,
                "close_price": 151,
                "realized_pnl_usd": 10,
            }
        ]
        weeks = weekly_pnl_breakdown(closed, weeks=2)
        assert len(weeks) == 2
        assert any(w["trades"] >= 1 for w in weeks)

    def test_distributed_lock_acquire_release(self):
        token = try_acquire_lock("test:lock:unit", ttl_seconds=10)
        assert token is not None
        assert try_acquire_lock("test:lock:unit", ttl_seconds=10) is None
        release_lock("test:lock:unit", token)
        assert try_acquire_lock("test:lock:unit", ttl_seconds=10) is not None
        release_lock("test:lock:unit", token)

    def test_lock_status(self):
        status = lock_status()
        assert status["backend"] in ("redis", "in_process")
        assert "redis_url_configured" in status
