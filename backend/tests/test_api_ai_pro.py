"""AI Pro API — src.api.ai_pro のテスト

サービス層はモックへ差し替え、HTTP 層（検証・テナント解決・応答形）を検証する。
"""

from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from pydantic import ValidationError

from src.api.ai_pro import AccountBody, ChatBody, _tenant_user, _validate_symbol, router
from src.auth.service import TenantContext


def make_request(tenant=None) -> Request:
    """request.state.tenant だけを持つ最小の Request。"""
    req = Request({"type": "http", "method": "GET", "path": "/", "headers": []})
    if tenant is not None:
        req.state.tenant = tenant
    return req


@pytest.fixture
def client():
    """AI Pro ルーターのみを載せたテストアプリ。"""
    app = FastAPI()

    @app.middleware("http")
    async def inject_tenant(request: Request, call_next):
        raw = request.headers.get("X-Test-Tenant")
        if raw:
            tenant_id, user_id = raw.split(",")
            request.state.tenant = TenantContext(
                tenant_id=int(tenant_id), tenant_slug="acme", plan="pro",
                user_id=int(user_id) if user_id else None)
        return await call_next(request)

    app.include_router(router)
    return TestClient(app, raise_server_exceptions=False)


def as_tenant(tenant_id: int = 1, user_id: int = 10) -> dict:
    """テナント認証済みのヘッダー。"""
    return {"X-Test-Tenant": f"{tenant_id},{user_id}"}


class TestValidateSymbol:
    """_validate_symbol() のテスト"""

    def test_uppercases_known_symbols(self):
        """対応シンボルは大文字化して返すこと"""
        assert _validate_symbol("eurusd") == "EURUSD"

    def test_unknown_symbol_raises_404(self):
        """未対応シンボルは 404 にすること"""
        with pytest.raises(Exception) as exc:
            _validate_symbol("XAUUSD")
        assert exc.value.status_code == 404


class TestTenantUser:
    """_tenant_user() のテスト"""

    def test_returns_tenant_and_user(self):
        """テナント ID とユーザー ID を返すこと"""
        ctx = TenantContext(tenant_id=5, tenant_slug="a", plan="pro", user_id=7)
        assert _tenant_user(make_request(ctx)) == (5, 7)

    def test_falls_back_without_a_request_tenant(self):
        """リクエストにテナントが無ければコンテキストから取り、ユーザーは None にすること"""
        with patch("src.api.ai_pro.get_tenant_id", return_value=9):
            assert _tenant_user(make_request()) == (9, None)


class TestRequestBodies:
    """リクエストボディのバリデーションテスト"""

    def test_chat_message_is_required(self):
        """チャットのメッセージは必須であること"""
        with pytest.raises(ValidationError):
            ChatBody(message="")

    def test_chat_message_has_a_length_limit(self):
        """メッセージは 4000 文字以下であること"""
        with pytest.raises(ValidationError):
            ChatBody(message="x" * 4001)

    def test_chat_defaults(self):
        """既定の通貨ペアと新規セッションの扱い"""
        body = ChatBody(message="質問")
        assert body.symbol == "USDJPY"
        assert body.session_id is None

    def test_account_name_is_required(self):
        """口座名は必須であること"""
        with pytest.raises(ValidationError):
            AccountBody(name="")

    def test_account_defaults(self):
        """既定はペーパー口座・残高 10,000 であること"""
        body = AccountBody(name="メイン")
        assert body.broker == "paper"
        assert body.balance == 10_000
        assert body.is_default is False

    def test_account_balance_cannot_be_negative(self):
        """残高は 0 以上であること"""
        with pytest.raises(ValidationError):
            AccountBody(name="メイン", balance=-1)


class TestSignalsEndpoint:
    """GET /api/pro/signals/{symbol} のテスト"""

    def test_returns_signals(self, client):
        """AI シグナルを返すこと"""
        with patch("src.api.ai_pro.generate_ai_signals",
                   new=AsyncMock(return_value={"action": "buy", "confidence": 70})):
            body = client.get("/api/pro/signals/USDJPY").json()

        assert body["action"] == "buy"

    def test_unknown_symbol_returns_404(self, client):
        """未対応シンボルは 404 にすること"""
        assert client.get("/api/pro/signals/XAUUSD").status_code == 404

    @pytest.mark.parametrize("days", [30, 900])
    def test_days_is_range_checked(self, client, days):
        """期間の範囲外指定は 422 にすること"""
        assert client.get(f"/api/pro/signals/USDJPY?days={days}").status_code == 422

    def test_days_is_forwarded(self, client):
        """指定した期間をサービス層へ渡すこと"""
        with patch("src.api.ai_pro.generate_ai_signals",
                   new=AsyncMock(return_value={})) as generate:
            client.get("/api/pro/signals/USDJPY?days=120")

        assert generate.await_args[0][1] == 120


class TestMarketBriefEndpoint:
    """GET /api/pro/market-brief/{symbol} のテスト"""

    def test_returns_the_brief(self, client):
        """市場ブリーフを返すこと"""
        with patch("src.api.ai_pro.build_market_brief",
                   new=AsyncMock(return_value={"symbol": "USDJPY"})):
            assert client.get("/api/pro/market-brief/USDJPY").json()["symbol"] == "USDJPY"

    def test_unknown_symbol_returns_404(self, client):
        """未対応シンボルは 404 にすること"""
        assert client.get("/api/pro/market-brief/XAUUSD").status_code == 404


class TestCoachingEndpoint:
    """GET /api/pro/coaching/{symbol} のテスト"""

    def test_returns_coaching(self, client):
        """コーチング結果を返すこと"""
        with patch("src.api.ai_pro.generate_coaching",
                   new=AsyncMock(return_value={"coaching": {"next_focus": "損切り"}})):
            body = client.get("/api/pro/coaching/USDJPY", headers=as_tenant()).json()

        assert body["coaching"]["next_focus"] == "損切り"

    def test_is_scoped_to_the_tenant(self, client):
        """自テナントの取引履歴で分析すること"""
        with patch("src.api.ai_pro.generate_coaching",
                   new=AsyncMock(return_value={})) as coaching:
            client.get("/api/pro/coaching/USDJPY", headers=as_tenant(42))

        assert coaching.await_args[0][1] == 42


class TestRiskEndpoint:
    """GET /api/pro/risk/{symbol} のテスト"""

    def test_returns_the_risk_assessment(self, client):
        """リスク評価を返すこと"""
        with patch("src.api.ai_pro.assess_advanced_risk",
                   return_value={"risk_score": {"level": "medium"}}):
            body = client.get("/api/pro/risk/USDJPY").json()

        assert body["risk_score"]["level"] == "medium"

    def test_unknown_symbol_returns_404(self, client):
        """未対応シンボルは 404 にすること"""
        assert client.get("/api/pro/risk/XAUUSD").status_code == 404


class TestChatEndpoint:
    """POST /api/pro/chat のテスト"""

    def test_forwards_the_message(self, client):
        """メッセージとセッション情報を委譲すること"""
        with patch("src.api.ai_pro.chat",
                   new=AsyncMock(return_value={"reply": "回答", "session_id": 1})) as chat:
            body = client.post("/api/pro/chat", headers=as_tenant(42, 7),
                               json={"message": "USDJPY の戦略は？"}).json()

        assert body["reply"] == "回答"
        # chat(message, symbol, session_id, tenant_id, user_id) の位置引数で渡される
        assert chat.await_args[0][3] == 42
        assert chat.await_args[0][4] == 7

    def test_empty_message_returns_422(self, client):
        """空メッセージは 422 にすること"""
        res = client.post("/api/pro/chat", headers=as_tenant(), json={"message": ""})
        assert res.status_code == 422

    def test_session_id_is_forwarded(self, client):
        """会話継続のためセッション ID を渡すこと"""
        with patch("src.api.ai_pro.chat", new=AsyncMock(return_value={})) as chat:
            client.post("/api/pro/chat", headers=as_tenant(),
                        json={"message": "続き", "session_id": 5})

        assert chat.await_args[0][2] == 5


class TestPortfolioEndpoint:
    """GET /api/pro/portfolio のテスト"""

    def test_returns_the_portfolio(self, client):
        """ポートフォリオ概要を返すこと"""
        with patch("src.api.ai_pro.build_portfolio_overview",
                   return_value={"total_balance": 25_000}):
            body = client.get("/api/pro/portfolio", headers=as_tenant()).json()

        assert body["total_balance"] == 25_000


class TestBacktestEndpoint:
    """GET /api/pro/backtest/{symbol} のテスト"""

    def test_unknown_symbol_returns_404(self, client):
        """未対応シンボルは 404 にすること"""
        assert client.get("/api/pro/backtest/XAUUSD").status_code == 404

    @pytest.mark.parametrize("days", [30, 900])
    def test_days_is_range_checked(self, client, days):
        """期間の範囲外指定は 422 にすること"""
        assert client.get(f"/api/pro/backtest/USDJPY?days={days}").status_code == 422
