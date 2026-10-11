"""自動売買のポジション管理 — src.autotrade.positions のテスト

DB はモックへ差し替え、SL / TP / 逆シグナル決済の判定ロジックを中心に検証する。
"""

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

import src.autotrade.positions as positions
from src.autotrade.positions import (
    AutoTradePosition,
    _pos_dict,
    check_exits,
    has_open_position,
    open_position,
)


@pytest.fixture(autouse=True)
def isolate_module_state():
    """メモリフォールバックとテーブル初期化を無効化する。"""
    positions._memory_positions = []
    with patch("src.autotrade.positions._ensure_table"):
        yield
    positions._memory_positions = []


def pos(side="buy", stop_loss=None, take_profit=None, units=1000, pos_id=1) -> dict:
    """オープンポジションの辞書を組み立てる。"""
    return {"id": pos_id, "symbol": "USDJPY", "side": side, "units": units,
            "entry_price": 150.0, "stop_loss": stop_loss, "take_profit": take_profit,
            "status": "OPEN"}


def row(**kwargs):
    """AutoTradePosition 相当のスタブを返す。"""
    defaults = dict(id=1, symbol="USDJPY", side="buy", units=1000, entry_price=150.0,
                    stop_loss=149.0, take_profit=152.0, status="OPEN", order_id=None,
                    opened_at=datetime.now(timezone.utc), closed_at=None,
                    close_price=None, close_reason=None)
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


class TestTableDefinition:
    """AutoTradePosition テーブル定義のテスト"""

    def test_table_name(self):
        """テーブル名が autotrade_positions であること"""
        assert AutoTradePosition.__tablename__ == "autotrade_positions"

    def test_has_protective_order_columns(self):
        """SL / TP を保持できること"""
        columns = {c.name for c in AutoTradePosition.__table__.columns}
        assert {"stop_loss", "take_profit", "status", "close_reason"} <= columns

    def test_is_tenant_scoped(self):
        """テナント分離のため tenant_id を持つこと"""
        assert "tenant_id" in {c.name for c in AutoTradePosition.__table__.columns}


class TestOpenPosition:
    """open_position() のテスト"""

    def test_persists_and_returns_the_record(self):
        """ポジションを保存し、ID 付きのレコードを返すこと"""
        session = MagicMock()

        def refresh(r):
            r.id = 42

        session.refresh.side_effect = refresh
        with patch("src.autotrade.positions.SessionLocal", return_value=session):
            record = open_position(1, "usdjpy", "buy", 1000, 150.0, 149.0, 152.0)

        assert record["id"] == 42
        assert record["symbol"] == "USDJPY"
        assert record["status"] == "OPEN"
        session.commit.assert_called_once()

    def test_records_the_protective_levels(self):
        """SL / TP を記録すること"""
        with patch("src.autotrade.positions.SessionLocal", return_value=MagicMock()):
            record = open_position(1, "USDJPY", "buy", 1000, 150.0, 149.0, 152.0)

        assert record["stop_loss"] == 149.0
        assert record["take_profit"] == 152.0

    def test_records_the_open_timestamp(self):
        """建玉日時を ISO 文字列で保持すること"""
        with patch("src.autotrade.positions.SessionLocal", return_value=MagicMock()):
            record = open_position(1, "USDJPY", "buy", 1000, 150.0, None, None)

        assert datetime.fromisoformat(record["opened_at"])

    def test_falls_back_to_memory_on_failure(self):
        """DB 保存に失敗してもポジションを見失わないこと"""
        session = MagicMock()
        session.commit.side_effect = OSError("db down")
        with patch("src.autotrade.positions.SessionLocal", return_value=session):
            record = open_position(1, "USDJPY", "buy", 1000, 150.0, None, None)

        session.rollback.assert_called_once()
        assert positions._memory_positions == [record]


class TestPosDict:
    """_pos_dict() のテスト"""

    def test_open_position_has_no_close_fields(self):
        """建玉中は決済情報を含めないこと"""
        result = _pos_dict(row(status="OPEN"))
        assert "close_price" not in result
        assert "realized_pnl_usd" not in result

    def test_closed_position_includes_close_fields(self):
        """決済済みなら決済情報を含めること"""
        result = _pos_dict(row(status="CLOSED", close_price=151.0,
                               close_reason="take_profit",
                               closed_at=datetime.now(timezone.utc)))

        assert result["close_price"] == 151.0
        assert result["close_reason"] == "take_profit"
        assert result["realized_pnl_usd"] > 0

    def test_include_close_flag_forces_the_fields(self):
        """include_close=True なら建玉中でも決済欄を用意すること"""
        result = _pos_dict(row(status="OPEN"), include_close=True)
        assert "close_price" in result

    def test_optional_levels_become_none(self):
        """SL / TP 未設定なら None を返すこと"""
        result = _pos_dict(row(stop_loss=None, take_profit=None))
        assert result["stop_loss"] is None
        assert result["take_profit"] is None

    def test_prices_are_floats(self):
        """価格は float へ変換すること（Decimal を返さない）"""
        assert type(_pos_dict(row())["entry_price"]) is float


class TestCheckExitsStopLoss:
    """ストップロス決済のテスト"""

    def _run(self, open_positions, price, **kwargs):
        with patch("src.autotrade.positions.list_open_positions", return_value=open_positions), \
             patch("src.autotrade.positions.oanda_close") as close, \
             patch("src.autotrade.positions.place_market_order"), \
             patch("src.autotrade.positions.close_position_record",
                   side_effect=lambda pid, p, r, t: {"id": pid, "close_price": p}):
            return check_exits("USDJPY", price, tenant_id=1, **kwargs), close

    def test_long_hits_stop_loss(self):
        """買いポジションが SL 以下に下落したら決済すること"""
        closed, _ = self._run([pos("buy", stop_loss=149.0)], 148.5)
        assert closed[0]["close_reason"] == "stop_loss"

    def test_long_above_stop_loss_is_kept(self):
        """SL に達していなければ保持すること"""
        closed, _ = self._run([pos("buy", stop_loss=149.0)], 149.5)
        assert closed == []

    def test_short_hits_stop_loss(self):
        """売りポジションが SL 以上に上昇したら決済すること"""
        closed, _ = self._run([pos("sell", stop_loss=151.0)], 151.5)
        assert closed[0]["close_reason"] == "stop_loss"

    def test_exact_touch_triggers_the_stop(self):
        """SL ちょうどでも決済すること（不等号に等号を含む）"""
        closed, _ = self._run([pos("buy", stop_loss=149.0)], 149.0)
        assert closed[0]["close_reason"] == "stop_loss"

    def test_no_stop_loss_means_no_stop_exit(self):
        """SL 未設定なら SL 決済は発生しないこと"""
        closed, _ = self._run([pos("buy", stop_loss=None)], 100.0)
        assert closed == []


class TestCheckExitsTakeProfit:
    """テイクプロフィット決済のテスト"""

    def _run(self, open_positions, price, **kwargs):
        with patch("src.autotrade.positions.list_open_positions", return_value=open_positions), \
             patch("src.autotrade.positions.oanda_close"), \
             patch("src.autotrade.positions.place_market_order"), \
             patch("src.autotrade.positions.close_position_record",
                   side_effect=lambda pid, p, r, t: {"id": pid}):
            return check_exits("USDJPY", price, tenant_id=1, **kwargs)

    def test_long_hits_take_profit(self):
        """買いポジションが TP 以上に上昇したら決済すること"""
        closed = self._run([pos("buy", take_profit=152.0)], 152.5)
        assert closed[0]["close_reason"] == "take_profit"

    def test_short_hits_take_profit(self):
        """売りポジションが TP 以下に下落したら決済すること"""
        closed = self._run([pos("sell", take_profit=148.0)], 147.5)
        assert closed[0]["close_reason"] == "take_profit"

    def test_stop_loss_takes_priority(self):
        """SL と TP の両方に該当する場合は SL を優先すること（保守的な判定）"""
        closed = self._run([pos("buy", stop_loss=153.0, take_profit=152.0)], 152.5)
        assert closed[0]["close_reason"] == "stop_loss"


class TestCheckExitsReverseSignal:
    """逆シグナル決済のテスト"""

    def _run(self, open_positions, price, **kwargs):
        with patch("src.autotrade.positions.list_open_positions", return_value=open_positions), \
             patch("src.autotrade.positions.oanda_close"), \
             patch("src.autotrade.positions.place_market_order"), \
             patch("src.autotrade.positions.close_position_record",
                   side_effect=lambda pid, p, r, t: {"id": pid}):
            return check_exits("USDJPY", price, tenant_id=1, **kwargs)

    def test_long_closed_on_sell_signal(self):
        """買い保有中に売りシグナルが出たら決済すること"""
        closed = self._run([pos("buy")], 150.0, reverse_action="sell")
        assert closed[0]["close_reason"] == "reverse_signal"

    def test_short_closed_on_buy_signal(self):
        """売り保有中に買いシグナルが出たら決済すること"""
        closed = self._run([pos("sell")], 150.0, reverse_action="buy")
        assert closed[0]["close_reason"] == "reverse_signal"

    def test_same_direction_signal_is_ignored(self):
        """同方向のシグナルでは決済しないこと"""
        assert self._run([pos("buy")], 150.0, reverse_action="buy") == []

    def test_hold_signal_is_ignored(self):
        """hold では決済しないこと"""
        assert self._run([pos("buy")], 150.0, reverse_action="hold") == []

    def test_can_be_disabled(self):
        """設定で無効化されていれば逆シグナル決済をしないこと"""
        closed = self._run([pos("buy")], 150.0, reverse_action="sell",
                           auto_exit_on_reverse=False)
        assert closed == []


class TestCheckExitsBehaviour:
    """check_exits() のその他の挙動テスト"""

    def test_no_positions_returns_empty(self):
        """建玉が無ければ空リストを返すこと（ブローカーも呼ばない）"""
        with patch("src.autotrade.positions.list_open_positions", return_value=[]), \
             patch("src.autotrade.positions.oanda_close") as close:
            assert check_exits("USDJPY", 150.0, tenant_id=1) == []
        close.assert_not_called()

    def test_closes_multiple_positions(self):
        """条件を満たす複数ポジションをまとめて決済すること"""
        with patch("src.autotrade.positions.list_open_positions",
                   return_value=[pos("buy", stop_loss=149.0, pos_id=1),
                                 pos("buy", stop_loss=149.5, pos_id=2)]), \
             patch("src.autotrade.positions.oanda_close"), \
             patch("src.autotrade.positions.place_market_order"), \
             patch("src.autotrade.positions.close_position_record",
                   side_effect=lambda pid, p, r, t: {"id": pid}):
            closed = check_exits("USDJPY", 148.0, tenant_id=1)

        assert {c["id"] for c in closed} == {1, 2}

    def test_falls_back_to_market_order_when_close_fails(self):
        """OANDA の決済 API が失敗したら反対売買で手仕舞うこと"""
        with patch("src.autotrade.positions.list_open_positions",
                   return_value=[pos("buy", stop_loss=149.0)]), \
             patch("src.autotrade.positions.oanda_close", side_effect=RuntimeError("api down")), \
             patch("src.autotrade.positions.place_market_order") as market, \
             patch("src.autotrade.positions.close_position_record",
                   side_effect=lambda pid, p, r, t: {"id": pid}):
            check_exits("USDJPY", 148.0, tenant_id=1)

        # 買いポジションなので反対売買は sell
        assert market.call_args[0][1] == "sell"

    def test_passes_the_trading_mode_through(self):
        """取引モードをブローカー呼び出しへ渡すこと"""
        with patch("src.autotrade.positions.list_open_positions",
                   return_value=[pos("buy", stop_loss=149.0)]), \
             patch("src.autotrade.positions.oanda_close") as close, \
             patch("src.autotrade.positions.place_market_order"), \
             patch("src.autotrade.positions.close_position_record",
                   side_effect=lambda pid, p, r, t: {"id": pid}):
            check_exits("USDJPY", 148.0, tenant_id=1, trading_mode="live")

        assert close.call_args.kwargs["trading_mode"] == "live"


class TestHasOpenPosition:
    """has_open_position() のテスト"""

    def test_true_when_positions_exist(self):
        """建玉があれば True を返すこと"""
        with patch("src.autotrade.positions.list_open_positions", return_value=[pos()]):
            assert has_open_position(1, "USDJPY") is True

    def test_false_when_empty(self):
        """建玉が無ければ False を返すこと"""
        with patch("src.autotrade.positions.list_open_positions", return_value=[]):
            assert has_open_position(1, "USDJPY") is False

    def test_scoped_to_tenant_and_symbol(self):
        """テナントとシンボルで絞り込むこと"""
        with patch("src.autotrade.positions.list_open_positions", return_value=[]) as list_open:
            has_open_position(7, "EURUSD")
        assert list_open.call_args[0] == (7, "EURUSD")
