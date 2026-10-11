"""自動売買 API — src.api.autotrade のテスト

サービス層はモックへ差し替え、HTTP 層（検証・テナント解決・応答形）を検証する。
"""

from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from src.api.autotrade import _tenant, _validate_symbol, router
from src.auth.service import TenantContext
from src.autotrade.models import DEFAULT_CONFIG


def make_request(tenant=None) -> Request:
    """request.state.tenant だけを持つ最小の Request。"""
    req = Request({"type": "http", "method": "GET", "path": "/", "headers": []})
    if tenant is not None:
        req.state.tenant = tenant
    return req


@pytest.fixture
def client():
    """自動売買ルーターのみを載せたテストアプリ。"""
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


class TestValidateSymbol:
    """_validate_symbol() のテスト"""

    def test_uppercases_known_symbols(self):
        """対応シンボルは大文字化して返すこと"""
        assert _validate_symbol("usdjpy") == "USDJPY"

    def test_unknown_symbol_raises_404(self):
        """未対応シンボルは 404 にすること"""
        with pytest.raises(Exception) as exc:
            _validate_symbol("XAUUSD")

        assert exc.value.status_code == 404
        assert "XAUUSD" in exc.value.detail


class TestTenantResolution:
    """_tenant() のテスト"""

    def test_uses_the_request_state(self):
        """リクエストのテナント情報を優先すること"""
        ctx = TenantContext(tenant_id=5, tenant_slug="a", plan="pro")
        assert _tenant(make_request(ctx)) == 5

    def test_falls_back_to_the_context_var(self):
        """リクエストに無ければコンテキスト変数から取ること"""
        with patch("src.api.autotrade.get_tenant_id", return_value=9):
            assert _tenant(make_request()) == 9

    def test_returns_none_when_unauthenticated(self):
        """未認証環境では None を返すこと（SaaS 無効時の単体運用）"""
        with patch("src.api.autotrade.get_tenant_id", return_value=None):
            assert _tenant(make_request()) is None


class TestPresetsEndpoint:
    """GET /api/autotrade/presets のテスト"""

    def test_returns_the_preset_list(self, client):
        """プリセット一覧を返すこと"""
        body = client.get("/api/autotrade/presets").json()

        assert "presets" in body
        assert len(body["presets"]) >= 1
        assert {"id", "label", "description"} <= set(body["presets"][0])


class TestApplyPresetEndpoint:
    """POST /api/autotrade/presets/apply のテスト"""

    def test_applies_a_preset(self, client):
        """プリセットを適用して設定を返すこと"""
        with patch("src.api.autotrade.get_config", return_value=dict(DEFAULT_CONFIG)), \
             patch("src.api.autotrade.save_config",
                   side_effect=lambda cfg, tid: cfg):
            body = client.post("/api/autotrade/presets/apply", headers=as_tenant(),
                               json={"preset_id": "aggressive"}).json()

        assert body["config"]["strategy_preset"] == "aggressive"

    def test_unknown_preset_returns_400(self, client):
        """未知のプリセット ID は 400 にすること"""
        with patch("src.api.autotrade.get_config", return_value=dict(DEFAULT_CONFIG)):
            res = client.post("/api/autotrade/presets/apply", headers=as_tenant(),
                              json={"preset_id": "nope"})

        assert res.status_code == 400


class TestAutoselectEndpoint:
    """POST /api/autotrade/autoselect のテスト"""

    def test_returns_a_recommendation(self, client):
        """推奨プリセットと理由を返すこと"""
        with patch("src.api.autotrade.save_config", side_effect=lambda cfg, tid: cfg):
            body = client.post("/api/autotrade/autoselect", headers=as_tenant(),
                               json={"risk_appetite": "low"}).json()

        assert body["recommended_preset"] == "conservative"
        assert body["rationale"]

    def test_apply_persists_the_config(self, client):
        """apply=true なら設定を保存すること"""
        with patch("src.api.autotrade.save_config", side_effect=lambda cfg, tid: cfg) as save:
            client.post("/api/autotrade/autoselect", headers=as_tenant(),
                        json={"risk_appetite": "low", "apply": True})

        save.assert_called_once()

    def test_without_apply_nothing_is_saved(self, client):
        """apply が無ければ設定を書き換えないこと（提案のみ）"""
        with patch("src.api.autotrade.save_config") as save:
            client.post("/api/autotrade/autoselect", headers=as_tenant(),
                        json={"risk_appetite": "low"})

        save.assert_not_called()


class TestConfigEndpoints:
    """GET / PUT /api/autotrade/config のテスト"""

    def test_get_returns_config_and_defaults(self, client):
        """現在値と既定値の両方を返すこと"""
        with patch("src.api.autotrade.get_config", return_value=dict(DEFAULT_CONFIG)):
            body = client.get("/api/autotrade/config", headers=as_tenant()).json()

        assert body["config"]["mode"] == "paper"
        assert body["defaults"] == DEFAULT_CONFIG

    def test_put_merges_updates(self, client):
        """指定した項目のみ更新すること"""
        with patch("src.api.autotrade.get_config", return_value=dict(DEFAULT_CONFIG)), \
             patch("src.api.autotrade.save_config", side_effect=lambda cfg, tid: cfg):
            body = client.put("/api/autotrade/config", headers=as_tenant(),
                              json={"min_confidence": 80}).json()

        assert body["config"]["min_confidence"] == 80
        assert body["config"]["mode"] == DEFAULT_CONFIG["mode"]

    def test_put_validates_symbols(self, client):
        """対応外の通貨ペアは 404 で弾くこと"""
        with patch("src.api.autotrade.get_config", return_value=dict(DEFAULT_CONFIG)), \
             patch("src.api.autotrade.save_config", side_effect=lambda cfg, tid: cfg):
            res = client.put("/api/autotrade/config", headers=as_tenant(),
                             json={"symbols": ["XAUUSD"]})

        assert res.status_code == 404

    def test_put_accepts_known_symbols(self, client):
        """対応通貨ペアなら更新できること"""
        with patch("src.api.autotrade.get_config", return_value=dict(DEFAULT_CONFIG)), \
             patch("src.api.autotrade.save_config", side_effect=lambda cfg, tid: cfg):
            res = client.put("/api/autotrade/config", headers=as_tenant(),
                             json={"symbols": ["EURUSD"]})

        assert res.status_code == 200


class TestSimulateEndpoint:
    """GET /api/autotrade/simulate/{symbol} のテスト"""

    def test_returns_the_simulation(self, client):
        """シミュレーション結果を返すこと"""
        with patch("src.api.autotrade.get_config", return_value=dict(DEFAULT_CONFIG)), \
             patch("src.api.autotrade.simulate_strategy",
                   return_value={"assessment": {"grade": "B"}}):
            body = client.get("/api/autotrade/simulate/USDJPY", headers=as_tenant()).json()

        assert body["assessment"]["grade"] == "B"

    def test_unknown_symbol_returns_404(self, client):
        """未対応シンボルは 404 にすること"""
        res = client.get("/api/autotrade/simulate/XAUUSD", headers=as_tenant())
        assert res.status_code == 404


class TestPerformanceEndpoint:
    """GET /api/autotrade/performance のテスト"""

    def test_returns_performance(self, client):
        """パフォーマンス集計を返すこと"""
        with patch("src.api.autotrade.build_performance",
                   return_value={"summary": {"executed": 3}}):
            body = client.get("/api/autotrade/performance", headers=as_tenant()).json()

        assert body["summary"]["executed"] == 3

    def test_limit_is_capped(self, client):
        """件数上限（200）を超える指定は弾くこと"""
        res = client.get("/api/autotrade/performance?limit=500", headers=as_tenant())
        assert res.status_code == 422


class TestPositionsEndpoint:
    """GET /api/autotrade/positions のテスト"""

    def test_returns_open_positions(self, client):
        """建玉一覧を返すこと"""
        with patch("src.api.autotrade.list_open_positions",
                   return_value=[{"symbol": "USDJPY", "side": "buy"}]):
            body = client.get("/api/autotrade/positions", headers=as_tenant()).json()

        assert body["positions"][0]["symbol"] == "USDJPY"

    def test_symbol_filter_is_validated(self, client):
        """フィルタに未対応シンボルを指定したら 404 にすること"""
        res = client.get("/api/autotrade/positions?symbol=XAUUSD", headers=as_tenant())
        assert res.status_code == 404

    def test_is_scoped_to_the_tenant(self, client):
        """自テナントの建玉のみを引くこと"""
        with patch("src.api.autotrade.list_open_positions", return_value=[]) as list_positions:
            client.get("/api/autotrade/positions", headers=as_tenant(42))

        assert list_positions.call_args[0][0] == 42
