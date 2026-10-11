"""ブローカー設定 API — src.api.broker のテスト"""

from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from pydantic import ValidationError

from src.api.broker import OandaSettingsBody, _tenant, router
from src.auth.service import TenantContext


def make_request(tenant=None) -> Request:
    """request.state.tenant だけを持つ最小の Request。"""
    req = Request({"type": "http", "method": "GET", "path": "/", "headers": []})
    if tenant is not None:
        req.state.tenant = tenant
    return req


@pytest.fixture
def client():
    """ブローカールーターのみを載せたテストアプリ。"""
    app = FastAPI()

    @app.middleware("http")
    async def inject_tenant(request: Request, call_next):
        raw = request.headers.get("X-Test-Tenant")
        if raw:
            request.state.tenant = TenantContext(
                tenant_id=int(raw), tenant_slug="acme", plan="pro")
        return await call_next(request)

    app.include_router(router)
    return TestClient(app, raise_server_exceptions=False)


def as_tenant(tenant_id: int = 1) -> dict:
    """テナント認証済みのヘッダー。"""
    return {"X-Test-Tenant": str(tenant_id)}


class TestOandaSettingsBody:
    """リクエストボディのバリデーションテスト"""

    def test_all_fields_are_optional(self):
        """全項目が省略可能であること（部分更新を許容）"""
        body = OandaSettingsBody()
        assert body.api_token is None
        assert body.account_id is None
        assert body.clear_token is False

    @pytest.mark.parametrize("environment", ["practice", "live"])
    def test_accepts_known_environments(self, environment):
        """practice / live を受け付けること"""
        assert OandaSettingsBody(environment=environment).environment == environment

    @pytest.mark.parametrize("environment", ["demo", "production", "LIVE", ""])
    def test_rejects_unknown_environments(self, environment):
        """未知の環境名は弾くこと（誤って本番へ接続しないため）"""
        with pytest.raises(ValidationError):
            OandaSettingsBody(environment=environment)

    def test_clear_token_flag(self):
        """トークン削除フラグを指定できること"""
        assert OandaSettingsBody(clear_token=True).clear_token is True


class TestTenantResolution:
    """_tenant() のテスト"""

    def test_uses_the_request_state(self):
        """リクエストのテナント情報を使うこと"""
        ctx = TenantContext(tenant_id=5, tenant_slug="a", plan="pro")
        assert _tenant(make_request(ctx)) == 5

    def test_falls_back_to_the_context_var(self):
        """リクエストに無ければコンテキスト変数から取ること"""
        with patch("src.api.broker.get_tenant_id", return_value=9):
            assert _tenant(make_request()) == 9

    def test_unauthenticated_raises_401(self):
        """テナントが特定できなければ 401 にすること"""
        with patch("src.api.broker.get_tenant_id", return_value=None):
            with pytest.raises(Exception) as exc:
                _tenant(make_request())

        assert exc.value.status_code == 401


class TestGetOandaSettings:
    """GET /api/broker/oanda/settings のテスト"""

    def test_requires_authentication(self, client):
        """未認証では 401 になること"""
        with patch("src.api.broker.get_tenant_id", return_value=None):
            assert client.get("/api/broker/oanda/settings").status_code == 401

    def test_returns_settings_and_summary(self, client):
        """保存済み設定と口座サマリーを返すこと"""
        with patch("src.api.broker.get_tenant_oanda_settings",
                   return_value={"account_id": "101-001", "environment": "practice"}), \
             patch("src.api.broker.get_account_summary",
                   return_value={"configured": True, "balance": 25_000}):
            body = client.get("/api/broker/oanda/settings", headers=as_tenant()).json()

        assert body["settings"]["account_id"] == "101-001"
        assert body["account_summary"]["balance"] == 25_000

    def test_is_scoped_to_the_tenant(self, client):
        """自テナントの設定のみを引くこと"""
        with patch("src.api.broker.get_tenant_oanda_settings", return_value={}) as get_settings, \
             patch("src.api.broker.get_account_summary", return_value={}):
            client.get("/api/broker/oanda/settings", headers=as_tenant(42))

        assert get_settings.call_args[0][0] == 42


class TestUpdateOandaSettings:
    """PUT /api/broker/oanda/settings のテスト"""

    def test_saves_the_settings(self, client):
        """設定を保存して結果を返すこと"""
        with patch("src.api.broker.save_tenant_oanda_settings",
                   return_value={"account_id": "101-001"}) as save:
            body = client.put("/api/broker/oanda/settings", headers=as_tenant(),
                              json={"account_id": "101-001", "environment": "live"}).json()

        assert body["settings"]["account_id"] == "101-001"
        assert save.call_args.kwargs["account_id"] == "101-001"
        assert save.call_args.kwargs["environment"] == "live"

    def test_clear_token_is_forwarded(self, client):
        """トークン削除フラグを保存処理へ渡すこと"""
        with patch("src.api.broker.save_tenant_oanda_settings", return_value={}) as save:
            client.put("/api/broker/oanda/settings", headers=as_tenant(),
                       json={"clear_token": True})

        assert save.call_args.kwargs["clear_token"] is True

    def test_validation_errors_return_400(self, client):
        """保存時の検証エラーは 400 にすること"""
        with patch("src.api.broker.save_tenant_oanda_settings",
                   side_effect=ValueError("アカウント ID の形式が不正です")):
            res = client.put("/api/broker/oanda/settings", headers=as_tenant(),
                             json={"account_id": "bad"})

        assert res.status_code == 400
        assert "形式が不正" in res.json()["detail"]

    def test_invalid_environment_returns_422(self, client):
        """未知の環境名はスキーマ検証で弾くこと"""
        res = client.put("/api/broker/oanda/settings", headers=as_tenant(),
                         json={"environment": "production"})
        assert res.status_code == 422

    def test_requires_authentication(self, client):
        """未認証では 401 になること"""
        with patch("src.api.broker.get_tenant_id", return_value=None):
            assert client.put("/api/broker/oanda/settings", json={}).status_code == 401

    def test_partial_update_is_allowed(self, client):
        """一部項目のみの更新ができること"""
        with patch("src.api.broker.save_tenant_oanda_settings", return_value={}) as save:
            client.put("/api/broker/oanda/settings", headers=as_tenant(),
                       json={"environment": "practice"})

        assert save.call_args.kwargs["api_token"] is None
        assert save.call_args.kwargs["account_id"] is None
