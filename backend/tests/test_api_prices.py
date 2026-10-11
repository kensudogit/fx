"""リアルタイム価格 API — src.api.prices のテスト

REST エンドポイントは TestClient、WebSocket は TestClient の websocket_connect で検証する。
価格取得はモックへ差し替える。
"""

from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.prices import _tenant_from_token, router
from src.auth.security import create_access_token
from src.data.sample_data import SYMBOL_BASE_PRICES


def quote(symbol="USDJPY", price=150.0) -> dict:
    """価格クォート 1 件。"""
    return {"symbol": symbol, "bid": price - 0.01, "ask": price + 0.01, "price": price}


@pytest.fixture
def client():
    """価格ルーターのみを載せたテストアプリ。"""
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


class TestTenantFromToken:
    """_tenant_from_token() のテスト"""

    def test_returns_none_without_a_token(self):
        """トークン未指定なら None を返すこと（価格は公開情報）"""
        assert _tenant_from_token(None) is None
        assert _tenant_from_token("") is None

    def test_extracts_the_tenant_id(self):
        """有効な JWT からテナント ID を取り出すこと"""
        token = create_access_token(1, 42, "a@example.com", "owner")
        assert _tenant_from_token(token) == 42

    def test_invalid_token_returns_none(self):
        """不正なトークンでも例外にせず None を返すこと"""
        assert _tenant_from_token("not-a-jwt") is None

    def test_expired_token_returns_none(self, override_settings):
        """期限切れトークンも None を返すこと"""
        override_settings(jwt_expire_hours=-1)
        token = create_access_token(1, 42, "a@example.com", "owner")
        assert _tenant_from_token(token) is None


class TestLivePrices:
    """GET /api/prices/live のテスト"""

    def test_returns_prices(self, client):
        """価格マップを返すこと"""
        with patch("src.api.prices.fetch_live_prices",
                   return_value={"USDJPY": quote()}) as fetch:
            body = client.get("/api/prices/live").json()

        assert body["prices"]["USDJPY"]["price"] == 150.0
        assert fetch.called

    def test_defaults_to_two_symbols(self, client):
        """既定では USDJPY と EURUSD を返すこと"""
        with patch("src.api.prices.fetch_live_prices", return_value={}) as fetch:
            client.get("/api/prices/live")

        assert fetch.call_args[0][0] == ["USDJPY", "EURUSD"]

    def test_parses_the_symbol_list(self, client):
        """カンマ区切りのシンボルを解釈すること"""
        with patch("src.api.prices.fetch_live_prices", return_value={}) as fetch:
            client.get("/api/prices/live?symbols=usdjpy, eurusd ,gbpusd")

        assert fetch.call_args[0][0] == ["USDJPY", "EURUSD", "GBPUSD"]

    def test_empty_entries_are_dropped(self, client):
        """空要素は除外すること"""
        with patch("src.api.prices.fetch_live_prices", return_value={}) as fetch:
            client.get("/api/prices/live?symbols=USDJPY,,")

        assert fetch.call_args[0][0] == ["USDJPY"]

    def test_is_unauthenticated(self, client):
        """認証なしで利用できること（テナント ID は None）"""
        with patch("src.api.prices.fetch_live_prices", return_value={}) as fetch:
            assert client.get("/api/prices/live").status_code == 200

        assert fetch.call_args[0][1] is None


class TestWebsocketPrices:
    """WebSocket /api/ws/prices のテスト"""

    def test_streams_prices(self, client):
        """接続すると価格を配信すること"""
        with patch("src.api.prices.fetch_live_prices", return_value={"USDJPY": quote()}):
            with client.websocket_connect("/api/ws/prices") as ws:
                message = ws.receive_json()

        assert message["type"] == "prices"
        assert message["data"]["USDJPY"]["price"] == 150.0

    def test_streams_all_symbols_by_default(self, client):
        """既定では全通貨ペアを配信すること"""
        with patch("src.api.prices.fetch_live_prices", return_value={}):
            with client.websocket_connect("/api/ws/prices") as ws:
                message = ws.receive_json()

        assert message["symbols"] == list(SYMBOL_BASE_PRICES)

    def test_subscription_filters_symbols(self, client):
        """購読メッセージで配信対象を絞り込めること"""
        with patch("src.api.prices.fetch_live_prices", return_value={}):
            with client.websocket_connect("/api/ws/prices") as ws:
                ws.receive_json()  # 初回配信
                ws.send_json({"symbols": ["eurusd"]})
                message = ws.receive_json()

        assert message["symbols"] == ["EURUSD"]

    def test_unknown_symbols_are_ignored(self, client):
        """未対応シンボルは購読リストから除外すること"""
        with patch("src.api.prices.fetch_live_prices", return_value={}):
            with client.websocket_connect("/api/ws/prices") as ws:
                ws.receive_json()
                ws.send_json({"symbols": ["XAUUSD", "USDJPY"]})
                message = ws.receive_json()

        assert message["symbols"] == ["USDJPY"]

    def test_authenticated_connection_passes_the_tenant(self, client):
        """トークン付き接続ではテナント ID を価格取得へ渡すこと"""
        token = create_access_token(1, 7, "a@example.com", "owner")
        with patch("src.api.prices.fetch_live_prices", return_value={}) as fetch:
            with client.websocket_connect(f"/api/ws/prices?token={token}") as ws:
                ws.receive_json()

        assert fetch.call_args[0][1] == 7

    def test_malformed_messages_are_ignored(self, client):
        """不正な JSON を受け取っても切断しないこと"""
        with patch("src.api.prices.fetch_live_prices", return_value={}):
            with client.websocket_connect("/api/ws/prices") as ws:
                ws.receive_json()
                ws.send_text("not json")
                assert ws.receive_json()["type"] == "prices"
