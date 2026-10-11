"""SaaS 認証・認可ミドルウェア — src.auth.middleware のテスト

ヘルパー関数は直接、dispatch は最小構成の FastAPI アプリに組み込んで検証する。
DB アクセス（テナント取得・利用集計・実績記録）はすべてモックへ差し替える。
"""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from src.auth.middleware import (
    PUBLIC_API_PATHS,
    SaaSAuthMiddleware,
    _is_public_api,
    _requires_premium,
    _resolve_tenant,
)
from src.auth.security import create_access_token
from src.auth.service import TenantContext


def make_request(headers: dict | None = None, path: str = "/api/dashboard") -> Request:
    """ヘッダーだけを持つ最小の Request を組み立てる。"""
    raw = [(k.lower().encode(), v.encode()) for k, v in (headers or {}).items()]
    return Request({"type": "http", "method": "GET", "path": path, "headers": raw})


class TestIsPublicApi:
    """_is_public_api() のテスト"""

    @pytest.mark.parametrize("path", sorted(PUBLIC_API_PATHS))
    def test_declared_public_paths(self, path):
        """公開パス一覧のエンドポイントは認証不要であること"""
        assert _is_public_api(path, "GET") is True

    def test_login_and_register_are_public(self):
        """ログイン・登録は認証前に叩けること（そうでないと登録できない）"""
        assert _is_public_api("/api/auth/register", "POST") is True
        assert _is_public_api("/api/auth/login", "POST") is True

    def test_plan_list_is_public(self):
        """料金プラン一覧は未ログインでも見られること"""
        assert _is_public_api("/api/billing/plans", "GET") is True

    def test_symbols_prefix_is_public(self):
        """/api/symbols 配下は前方一致で公開であること"""
        assert _is_public_api("/api/symbols", "GET") is True
        assert _is_public_api("/api/symbols/USDJPY", "GET") is True

    def test_tradingview_webhook_is_public_only_for_post(self):
        """TradingView Webhook は POST のみ公開であること"""
        assert _is_public_api("/api/tradingview/webhook", "POST") is True
        assert _is_public_api("/api/tradingview/webhook", "GET") is False

    @pytest.mark.parametrize("path", [
        "/api/dashboard", "/api/auth/me", "/api/autotrade/config", "/api/billing/status",
    ])
    def test_protected_paths_are_not_public(self, path):
        """保護対象のパスは公開扱いにならないこと"""
        assert _is_public_api(path, "GET") is False


class TestRequiresPremium:
    """_requires_premium() のテスト"""

    @pytest.mark.parametrize("path", [
        "/api/ai/report/USDJPY",
        "/api/pro/signals/USDJPY",
        "/api/analysis/intelligence/USDJPY",
        "/api/autotrade/config",
    ])
    def test_premium_prefixes(self, path):
        """有料機能のプレフィックスは制限対象であること"""
        assert _requires_premium(path, "GET") is True

    def test_ai_status_is_exempt(self):
        """AI の設定状態確認は無料で叩けること（UI のバッジ表示に使う）"""
        assert _requires_premium("/api/ai/status", "GET") is False

    def test_oanda_orders_restricted_for_post_only(self):
        """OANDA の発注は POST のみ制限、照会は制限しないこと"""
        assert _requires_premium("/api/oanda/orders", "POST") is True
        assert _requires_premium("/api/oanda/orders", "GET") is False

    @pytest.mark.parametrize("path", ["/api/dashboard", "/api/technical/USDJPY", "/api/auth/me"])
    def test_free_paths_are_not_premium(self, path):
        """無料機能は制限対象にならないこと"""
        assert _requires_premium(path, "GET") is False


class TestResolveTenant:
    """_resolve_tenant() のテスト"""

    def test_returns_none_without_credentials(self):
        """認証情報が無ければ None を返すこと"""
        assert _resolve_tenant(make_request()) is None

    def test_resolves_from_jwt(self):
        """Bearer トークンからテナントコンテキストを組み立てること"""
        token = create_access_token(7, 42, "a@example.com", "owner")
        ctx = _resolve_tenant(make_request({"Authorization": f"Bearer {token}"}))

        assert ctx.tenant_id == 42
        assert ctx.user_id == 7
        assert ctx.email == "a@example.com"
        assert ctx.role == "owner"

    def test_bearer_scheme_is_case_insensitive(self):
        """bearer / BEARER のどちらでも認識すること"""
        token = create_access_token(1, 1, "a@example.com", "owner")
        assert _resolve_tenant(make_request({"Authorization": f"bearer {token}"})) is not None
        assert _resolve_tenant(make_request({"Authorization": f"BEARER {token}"})) is not None

    def test_invalid_jwt_falls_through(self):
        """不正なトークンでは None になること"""
        assert _resolve_tenant(make_request({"Authorization": "Bearer not-a-token"})) is None

    def test_resolves_from_api_key(self):
        """X-API-Key ヘッダーから解決できること"""
        expected = TenantContext(tenant_id=5, tenant_slug="acme", plan="pro", auth_via="api_key")
        with patch("src.auth.middleware.SessionLocal") as session_local, \
             patch("src.auth.middleware.resolve_api_key", return_value=expected) as resolve:
            ctx = _resolve_tenant(make_request({"X-API-Key": "fx_secret"}))

        assert ctx is expected
        assert resolve.call_args[0][1] == "fx_secret"
        session_local.return_value.close.assert_called_once()

    def test_jwt_takes_precedence_over_api_key(self):
        """両方あれば JWT を優先すること"""
        token = create_access_token(1, 99, "a@example.com", "owner")
        with patch("src.auth.middleware.resolve_api_key") as resolve:
            ctx = _resolve_tenant(make_request({
                "Authorization": f"Bearer {token}", "X-API-Key": "fx_secret",
            }))

        assert ctx.tenant_id == 99
        resolve.assert_not_called()

    def test_closes_session_even_when_key_is_invalid(self):
        """API キーが無効でもセッションを閉じること"""
        with patch("src.auth.middleware.SessionLocal") as session_local, \
             patch("src.auth.middleware.resolve_api_key", return_value=None):
            assert _resolve_tenant(make_request({"X-API-Key": "fx_bad"})) is None
        session_local.return_value.close.assert_called_once()


@pytest.fixture
def client_factory():
    """ミドルウェアを組み込んだテスト用アプリの生成関数を返す。"""

    def _make():
        app = FastAPI()
        app.add_middleware(SaaSAuthMiddleware)

        @app.get("/api/dashboard")
        def dashboard():
            return {"ok": True}

        @app.get("/api/symbols")
        def symbols():
            return {"symbols": []}

        @app.get("/api/ai/report/USDJPY")
        def ai_report():
            return {"ok": True}

        @app.get("/api/autotrade/config")
        def autotrade_config():
            return {"ok": True}

        @app.get("/api/pro/signals/USDJPY")
        def pro_signals():
            return {"ok": True}

        @app.get("/api/prices/live")
        def live_prices():
            return {"prices": {}}

        @app.get("/health")
        def health():
            return {"status": "ok"}

        @app.get("/api/boom")
        def boom():
            raise RuntimeError("failure")

        return TestClient(app, raise_server_exceptions=False)

    return _make


@pytest.fixture
def tenant_db():
    """テナント取得・利用集計・実績記録をモックするヘルパー。"""

    class Harness:
        def __init__(self):
            self.usage = 0
            self.plan = "free"
            self.recorded = []

        def __enter__(self):
            session = MagicMock()
            session.get.side_effect = lambda model, pk: SimpleNamespace(
                plan=self.plan, slug="acme") if pk else None
            self._patches = [
                patch("src.auth.middleware.SessionLocal", return_value=session),
                patch("src.auth.models.count_daily_usage", side_effect=lambda t: self.usage),
                patch("src.auth.middleware.record_usage",
                      side_effect=lambda t, p: self.recorded.append((t, p))),
            ]
            for p in self._patches:
                p.start()
            return self

        def __exit__(self, *exc):
            for p in self._patches:
                p.stop()

    return Harness


def auth_header(tenant_id: int = 1) -> dict:
    """有効な JWT を持つ Authorization ヘッダーを作る。"""
    return {"Authorization": f"Bearer {create_access_token(1, tenant_id, 'a@example.com', 'owner')}"}


class TestDispatchRouting:
    """dispatch() のルーティング判定テスト"""

    def test_non_api_paths_bypass_auth(self, client_factory):
        """/api/ 以外（ヘルスチェック等）は素通しすること"""
        assert client_factory().get("/health").status_code == 200

    def test_public_api_bypasses_auth(self, client_factory):
        """公開 API は認証なしで通ること"""
        assert client_factory().get("/api/symbols").status_code == 200

    def test_live_prices_bypasses_auth(self, client_factory):
        """ライブ価格のポーリングは認証なしで通ること"""
        assert client_factory().get("/api/prices/live").status_code == 200

    def test_protected_api_requires_credentials(self, client_factory):
        """保護 API は認証なしだと 401 になること"""
        res = client_factory().get("/api/dashboard")
        assert res.status_code == 401
        assert "認証が必要です" in res.json()["detail"]

    def test_saas_disabled_bypasses_everything(self, client_factory, override_settings):
        """SaaS モードが無効なら全リクエストを素通しすること"""
        override_settings(saas_enabled=False)
        assert client_factory().get("/api/dashboard").status_code == 200


class TestDispatchAuthentication:
    """認証済みリクエストの処理テスト"""

    def test_valid_jwt_passes(self, client_factory, tenant_db):
        """有効な JWT なら通過すること"""
        with tenant_db():
            assert client_factory().get("/api/dashboard", headers=auth_header()).status_code == 200

    def test_unknown_tenant_is_rejected(self, client_factory, tenant_db):
        """JWT は有効でもテナントが存在しなければ 401 になること"""
        with tenant_db():
            with patch("src.auth.middleware.SessionLocal") as session_local:
                session_local.return_value.get.return_value = None
                res = client_factory().get("/api/dashboard", headers=auth_header())

        assert res.status_code == 401
        assert res.json()["detail"] == "テナントが見つかりません"

    def test_plan_is_loaded_from_database(self, client_factory, tenant_db):
        """プランは JWT ではなく DB の値を使うこと（改ざん対策）"""
        with tenant_db() as h:
            h.plan = "pro"
            # free では 403 になる AI 分析が、DB 上 pro なら通る
            assert client_factory().get("/api/ai/report/USDJPY",
                                        headers=auth_header()).status_code == 200


class TestDispatchRateLimit:
    """1 日の利用上限チェックのテスト"""

    def test_allows_request_below_limit(self, client_factory, tenant_db):
        """上限未満なら通過すること"""
        with tenant_db() as h:
            h.usage = 99
            assert client_factory().get("/api/dashboard", headers=auth_header()).status_code == 200

    def test_blocks_request_at_limit(self, client_factory, tenant_db):
        """上限に達したら 429 を返すこと"""
        with tenant_db() as h:
            h.usage = 100
            res = client_factory().get("/api/dashboard", headers=auth_header())

        assert res.status_code == 429
        body = res.json()
        assert body["usage"] == 100
        assert body["limit"] == 100
        assert body["plan"] == "free"

    def test_free_plan_gets_upgrade_hint(self, client_factory, tenant_db):
        """Free プランには Pro への案内を添えること"""
        with tenant_db() as h:
            h.usage = 100
            res = client_factory().get("/api/dashboard", headers=auth_header())
        assert "Pro プラン" in res.json()["detail"]

    def test_paid_plan_limit_is_higher(self, client_factory, tenant_db):
        """Pro プランでは free の上限を超えても通ること"""
        with tenant_db() as h:
            h.plan = "pro"
            h.usage = 500
            assert client_factory().get("/api/dashboard", headers=auth_header()).status_code == 200


class TestDispatchFeatureGate:
    """プラン別フィーチャーゲートのテスト"""

    def test_free_plan_is_blocked_from_autotrade(self, client_factory, tenant_db):
        """Free プランは自動取引で 403 になること"""
        with tenant_db():
            res = client_factory().get("/api/autotrade/config", headers=auth_header())

        assert res.status_code == 403
        assert res.json()["detail"] == "自動取引は Pro プラン以上で利用できます"

    def test_free_plan_can_use_basic_ai(self, client_factory, tenant_db):
        """Free プランでも基本 AI 分析は使えること（plans.py で ai=True のため）

        制限対象パスではあるが、フィーチャーフラグ `ai` が全プランで有効なので
        実際にブロックされるのは `ai_pro` を要求する /api/pro/ 配下のみ。
        """
        with tenant_db():
            res = client_factory().get("/api/ai/report/USDJPY", headers=auth_header())

        assert res.status_code == 200

    def test_free_plan_is_blocked_from_ai_pro(self, client_factory, tenant_db):
        """Free プランは AI Pro 機能で 403 になること"""
        with tenant_db():
            res = client_factory().get("/api/pro/signals/USDJPY", headers=auth_header())

        assert res.status_code == 403
        assert res.json()["detail"] == "AI Pro 機能は Pro プラン以上で利用できます"

    def test_pro_plan_reaches_premium_endpoints(self, client_factory, tenant_db):
        """Pro プランは有料機能を利用できること"""
        with tenant_db() as h:
            h.plan = "pro"
            assert client_factory().get("/api/autotrade/config",
                                        headers=auth_header()).status_code == 200


class TestDispatchUsageRecording:
    """利用実績の記録テスト"""

    def test_records_usage_on_success(self, client_factory, tenant_db):
        """成功したリクエストは利用実績に記録されること"""
        with tenant_db() as h:
            client_factory().get("/api/dashboard", headers=auth_header(tenant_id=42))
            assert h.recorded == [(42, "/api/dashboard")]

    def test_does_not_record_failed_requests(self, client_factory, tenant_db):
        """4xx / 5xx のリクエストは課金対象にしないこと"""
        with tenant_db() as h:
            client_factory().get("/api/boom", headers=auth_header())
            assert h.recorded == []

    def test_does_not_record_unauthenticated_requests(self, client_factory, tenant_db):
        """未認証リクエストは記録されないこと"""
        with tenant_db() as h:
            client_factory().get("/api/dashboard")
            assert h.recorded == []
