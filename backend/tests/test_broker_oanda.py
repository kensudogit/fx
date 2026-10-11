"""OANDA ブローカー連携 — src.broker.oanda のテスト

OANDA API と DB はモックへ差し替え、
未設定時のペーパー取引フォールバックと発注内容を検証する。
"""

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from src.broker.oanda import (
    OANDA_TO_SYMBOL,
    SYMBOL_TO_OANDA,
    BrokerOrder,
    _base_url,
    _headers,
    fetch_live_prices,
    get_account_summary,
    is_oanda_configured,
    list_orders,
    place_market_order,
)
from src.broker.tenant_oanda import OandaCredentials


def creds(configured=True, mode="live", token="token", account="101-001"):
    """OANDA 認証情報を組み立てる。"""
    return OandaCredentials(configured=configured, mode=mode, api_token=token,
                            account_id=account, source="tenant" if configured else "paper")


def http_client(payload=None, error=None):
    """httpx.Client のコンテキストマネージャをモックする。"""
    response = MagicMock()
    response.json.return_value = payload or {}
    response.raise_for_status = MagicMock()
    client = MagicMock()
    if error is not None:
        client.get.side_effect = error
        client.post.side_effect = error
    else:
        client.get.return_value = response
        client.post.return_value = response
    ctx = MagicMock()
    ctx.__enter__.return_value = client
    ctx.__exit__.return_value = False
    return ctx, client


class TestSymbolMapping:
    """シンボル変換テーブルのテスト"""

    def test_maps_to_oanda_instruments(self):
        """OANDA の instrument 形式へ変換できること"""
        assert SYMBOL_TO_OANDA["USDJPY"] == "USD_JPY"
        assert SYMBOL_TO_OANDA["EURUSD"] == "EUR_USD"

    def test_reverse_mapping_is_consistent(self):
        """逆引きテーブルが整合していること"""
        for symbol, instrument in SYMBOL_TO_OANDA.items():
            assert OANDA_TO_SYMBOL[instrument] == symbol


class TestTableDefinition:
    """BrokerOrder テーブル定義のテスト"""

    def test_table_name(self):
        """テーブル名が broker_orders であること"""
        assert BrokerOrder.__tablename__ == "broker_orders"

    def test_columns(self):
        """必要なカラムを備えること"""
        columns = {c.name for c in BrokerOrder.__table__.columns}
        assert {"symbol", "side", "units", "status", "broker", "tenant_id"} <= columns


class TestIsOandaConfigured:
    """is_oanda_configured() のテスト"""

    def test_true_when_credentials_exist(self):
        """認証情報が揃っていれば True を返すこと"""
        with patch("src.broker.oanda.resolve_oanda_credentials", return_value=creds()):
            assert is_oanda_configured(1) is True

    def test_false_when_unconfigured(self):
        """未設定なら False を返すこと"""
        with patch("src.broker.oanda.resolve_oanda_credentials",
                   return_value=creds(configured=False)):
            assert is_oanda_configured(1) is False


class TestBaseUrlAndHeaders:
    """_base_url() / _headers() のテスト"""

    def test_live_uses_the_production_endpoint(self):
        """live モードでは本番 API を使うこと"""
        assert _base_url(creds(mode="live")) == "https://api-fxtrade.oanda.com/v3"

    @pytest.mark.parametrize("mode", ["practice", "paper", ""])
    def test_non_live_uses_the_demo_endpoint(self, mode):
        """live 以外はデモ API を使うこと（誤って本番へ出さない）"""
        assert _base_url(creds(mode=mode)) == "https://api-fxpractice.oanda.com/v3"

    def test_headers_carry_the_bearer_token(self):
        """Bearer トークンを付与すること"""
        headers = _headers(creds(token="secret"))

        assert headers["Authorization"] == "Bearer secret"
        assert headers["Content-Type"] == "application/json"


class TestGetAccountSummary:
    """get_account_summary() のテスト"""

    def test_unconfigured_returns_paper_defaults(self):
        """未設定ならペーパー取引の既定値を返すこと"""
        with patch("src.broker.oanda.resolve_oanda_credentials",
                   return_value=creds(configured=False)):
            summary = get_account_summary(1)

        assert summary["configured"] is False
        assert summary["mode"] == "paper"
        assert summary["balance"] == 10000
        assert "OANDA 未設定" in summary["message"]

    def test_returns_live_account_data(self):
        """OANDA の口座情報を返すこと"""
        ctx, _ = http_client({"account": {"balance": "25000.50", "currency": "JPY",
                                          "unrealizedPL": "12.5", "openTradeCount": 3}})
        with patch("src.broker.oanda.resolve_oanda_credentials", return_value=creds()), \
             patch("src.broker.oanda.httpx.Client", return_value=ctx):
            summary = get_account_summary(1)

        assert summary["configured"] is True
        assert summary["balance"] == 25000.5
        assert summary["currency"] == "JPY"
        assert summary["unrealized_pl"] == 12.5
        assert summary["open_trade_count"] == 3

    def test_requests_the_account_summary_endpoint(self):
        """口座サマリーのエンドポイントを叩くこと"""
        ctx, client = http_client({"account": {}})
        with patch("src.broker.oanda.resolve_oanda_credentials",
                   return_value=creds(account="101-999")), \
             patch("src.broker.oanda.httpx.Client", return_value=ctx):
            get_account_summary(1)

        assert "/accounts/101-999/summary" in client.get.call_args[0][0]


class TestFetchLivePrices:
    """fetch_live_prices() のテスト"""

    def test_returns_oanda_quotes(self):
        """OANDA の bid/ask から mid 価格を計算すること"""
        payload = {"prices": [{"instrument": "USD_JPY", "time": "2026-01-01T00:00:00Z",
                               "bids": [{"price": "151.00"}], "asks": [{"price": "151.02"}]}]}
        ctx, _ = http_client(payload)
        with patch("src.broker.oanda.resolve_oanda_credentials", return_value=creds()), \
             patch("src.broker.oanda.httpx.Client", return_value=ctx):
            prices = fetch_live_prices(["USDJPY"], 1)

        assert prices["USDJPY"]["bid"] == 151.00
        assert prices["USDJPY"]["ask"] == 151.02
        assert prices["USDJPY"]["price"] == 151.01
        assert prices["USDJPY"]["source"] == "oanda"

    def test_unsupported_symbols_are_dropped(self):
        """未対応シンボルは除外すること"""
        with patch("src.broker.oanda.resolve_oanda_credentials",
                   return_value=creds(configured=False)):
            assert fetch_live_prices(["XAUUSD"], 1) == {}

    def test_falls_back_to_market_data(self, ohlcv):
        """OANDA 未設定なら市場データの終値を使うこと"""
        with patch("src.broker.oanda.resolve_oanda_credentials",
                   return_value=creds(configured=False)), \
             patch("src.data.market_data.get_ohlcv_data", return_value=(ohlcv, "database")):
            prices = fetch_live_prices(["USDJPY"], 1)

        assert prices["USDJPY"]["price"] == pytest.approx(float(ohlcv["close"].iloc[-1]))
        assert prices["USDJPY"]["source"] == "database"

    def test_api_failure_falls_back(self, ohlcv):
        """OANDA が失敗しても市場データで補完すること"""
        ctx, _ = http_client(error=OSError("api down"))
        with patch("src.broker.oanda.resolve_oanda_credentials", return_value=creds()), \
             patch("src.broker.oanda.httpx.Client", return_value=ctx), \
             patch("src.data.market_data.get_ohlcv_data", return_value=(ohlcv, "database")):
            prices = fetch_live_prices(["USDJPY"], 1)

        assert prices["USDJPY"]["source"] == "database"

    def test_symbols_are_uppercased(self, ohlcv):
        """小文字のシンボルも扱えること"""
        with patch("src.broker.oanda.resolve_oanda_credentials",
                   return_value=creds(configured=False)), \
             patch("src.data.market_data.get_ohlcv_data", return_value=(ohlcv, "database")):
            assert "USDJPY" in fetch_live_prices(["usdjpy"], 1)


class TestPlaceMarketOrder:
    """place_market_order() のテスト"""

    @pytest.mark.parametrize("side", ["hold", "long", ""])
    def test_rejects_invalid_sides(self, side):
        """buy / sell 以外は ValueError にすること"""
        with pytest.raises(ValueError, match="side must be buy or sell"):
            place_market_order("USDJPY", side, 1000)

    def test_defaults_to_paper_mode(self):
        """モード未指定ならペーパー取引として扱うこと（誤発注の防止）"""
        with patch("src.broker.oanda.resolve_oanda_credentials",
                   return_value=creds(configured=False)) as resolve, \
             patch("src.broker.oanda._save_paper_order", return_value={"broker": "paper"}):
            place_market_order("USDJPY", "buy", 1000, tenant_id=1)

        assert resolve.call_args[0][1] == "paper"

    def test_unconfigured_uses_paper_orders(self):
        """OANDA 未設定ならペーパー注文として記録すること"""
        with patch("src.broker.oanda.resolve_oanda_credentials",
                   return_value=creds(configured=False)), \
             patch("src.broker.oanda._save_paper_order",
                   return_value={"broker": "paper", "status": "FILLED"}) as paper:
            result = place_market_order("USDJPY", "buy", 1000, tenant_id=1)

        paper.assert_called_once()
        assert result["broker"] == "paper"

    def test_unsupported_symbol_raises(self):
        """OANDA が扱えない通貨ペアは ValueError にすること"""
        with patch("src.broker.oanda.resolve_oanda_credentials", return_value=creds()):
            with pytest.raises(ValueError, match="Unsupported symbol"):
                place_market_order("XAUUSD", "buy", 1000, tenant_id=1, trading_mode="live")

    def test_sell_orders_use_negative_units(self):
        """売り注文は units を負数で送ること（OANDA の仕様）"""
        ctx, client = http_client({"orderFillTransaction": {"id": "1", "price": "151.0"}})
        with patch("src.broker.oanda.resolve_oanda_credentials", return_value=creds()), \
             patch("src.broker.oanda.httpx.Client", return_value=ctx), \
             patch("src.broker.oanda._save_order", side_effect=lambda **kw: kw):
            place_market_order("USDJPY", "sell", 1000, tenant_id=1, trading_mode="live")

        body = client.post.call_args.kwargs["json"]["order"]
        assert body["units"] == "-1000"
        assert body["type"] == "MARKET"

    def test_buy_orders_use_positive_units(self):
        """買い注文は units を正数で送ること"""
        ctx, client = http_client({"orderFillTransaction": {"id": "1", "price": "151.0"}})
        with patch("src.broker.oanda.resolve_oanda_credentials", return_value=creds()), \
             patch("src.broker.oanda.httpx.Client", return_value=ctx), \
             patch("src.broker.oanda._save_order", side_effect=lambda **kw: kw):
            place_market_order("USDJPY", "buy", 1000, tenant_id=1, trading_mode="live")

        assert client.post.call_args.kwargs["json"]["order"]["units"] == "1000"

    def test_uses_fill_or_kill(self):
        """部分約定を避けるため FOK を指定すること"""
        ctx, client = http_client({"orderFillTransaction": {"id": "1", "price": "151.0"}})
        with patch("src.broker.oanda.resolve_oanda_credentials", return_value=creds()), \
             patch("src.broker.oanda.httpx.Client", return_value=ctx), \
             patch("src.broker.oanda._save_order", side_effect=lambda **kw: kw):
            place_market_order("USDJPY", "buy", 1000, tenant_id=1, trading_mode="live")

        assert client.post.call_args.kwargs["json"]["order"]["timeInForce"] == "FOK"


class TestListOrders:
    """list_orders() のテスト"""

    def _session(self, rows):
        db = MagicMock()
        db.execute.return_value.scalars.return_value.all.return_value = rows
        return db

    def _row(self):
        return SimpleNamespace(id=1, symbol="USDJPY", side="buy", units=1000,
                               fill_price=151.0, status="FILLED", broker="paper",
                               external_id="o-1", tenant_id=1,
                               created_at=datetime.now(timezone.utc))

    def test_maps_rows_to_dicts(self):
        """注文行を辞書へ変換すること"""
        with patch("src.broker.oanda._ensure_table"), \
             patch("src.broker.oanda.SessionLocal", return_value=self._session([self._row()])):
            orders = list_orders()

        assert orders[0]["symbol"] == "USDJPY"
        assert orders[0]["status"] == "FILLED"

    def test_empty_result(self):
        """注文が無ければ空リストを返すこと"""
        with patch("src.broker.oanda._ensure_table"), \
             patch("src.broker.oanda.SessionLocal", return_value=self._session([])):
            assert list_orders() == []

    def test_database_error_is_tolerated(self):
        """DB エラーでも例外を投げずに空を返すこと"""
        db = MagicMock()
        db.execute.side_effect = OSError("db down")
        with patch("src.broker.oanda._ensure_table"), \
             patch("src.broker.oanda.SessionLocal", return_value=db):
            assert list_orders() == []

    def test_falls_back_to_memory_orders(self):
        """DB エラー時はインメモリの注文を返すこと"""
        db = MagicMock()
        db.execute.side_effect = OSError("db down")
        with patch("src.broker.oanda._ensure_table"), \
             patch("src.broker.oanda._memory_orders", [{"symbol": "EURUSD"}]), \
             patch("src.broker.oanda.SessionLocal", return_value=db):
            assert list_orders() == [{"symbol": "EURUSD"}]

    def test_limit_is_applied_to_the_memory_fallback(self):
        """フォールバック時も取得件数の上限を守ること"""
        db = MagicMock()
        db.execute.side_effect = OSError("db down")
        with patch("src.broker.oanda._ensure_table"), \
             patch("src.broker.oanda._memory_orders", [{"symbol": "USDJPY"}] * 30), \
             patch("src.broker.oanda.SessionLocal", return_value=db):
            assert len(list_orders(limit=5)) == 5
