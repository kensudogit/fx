"""認証・課金の API ルーター — src.auth.router のテスト

FastAPI の TestClient で実際にエンドポイントを叩き、
サービス層・Stripe・DB はモックへ差し替えて HTTP 層の責務を検証する。
"""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from pydantic import ValidationError

from src.auth.router import (
    ApiKeyBody,
    CheckoutBody,
    LoginBody,
    PlanUpgradeBody,
    RegisterBody,
    _current_tenant_id,
    _current_user_id,
    _require_owner,
    router,
)
from src.auth.service import TenantContext
from src.db.database import get_db


def make_request(tenant=None) -> Request:
    """request.state.tenant だけを持つ最小の Request を作る。"""
    req = Request({"type": "http", "method": "GET", "path": "/", "headers": []})
    if tenant is not None:
        req.state.tenant = tenant
    return req


@pytest.fixture
def db_session():
    """DB セッションのモック。"""
    return MagicMock()


@pytest.fixture
def client(db_session):
    """ルーターのみを載せたテストアプリ。テナントはヘッダーで注入する。"""
    app = FastAPI()

    @app.middleware("http")
    async def inject_tenant(request: Request, call_next):
        # テスト用に X-Test-Tenant ヘッダーからテナントコンテキストを組み立てる
        raw = request.headers.get("X-Test-Tenant")
        if raw:
            tenant_id, user_id, role, auth_via = raw.split(",")
            request.state.tenant = TenantContext(
                tenant_id=int(tenant_id),
                tenant_slug="acme",
                plan="free",
                user_id=int(user_id) if user_id else None,
                email="a@example.com",
                role=role or None,
                auth_via=auth_via,
            )
        return await call_next(request)

    app.include_router(router)
    app.dependency_overrides[get_db] = lambda: db_session
    return TestClient(app, raise_server_exceptions=False)


def as_owner(tenant_id: int = 1, user_id: int = 10) -> dict:
    """オーナー（JWT 認証）のヘッダー。"""
    return {"X-Test-Tenant": f"{tenant_id},{user_id},owner,jwt"}


def as_member(tenant_id: int = 1, user_id: int = 11) -> dict:
    """オーナー以外のメンバーのヘッダー。"""
    return {"X-Test-Tenant": f"{tenant_id},{user_id},member,jwt"}


def as_api_key(tenant_id: int = 1) -> dict:
    """API キー認証（ユーザー情報なし）のヘッダー。"""
    return {"X-Test-Tenant": f"{tenant_id},,,api_key"}


class TestRequestBodies:
    """Pydantic リクエストボディのバリデーションテスト"""

    def test_register_requires_valid_email(self):
        """メール形式でない値を弾くこと"""
        with pytest.raises(ValidationError):
            RegisterBody(email="not-an-email", password="password1", org_name="Acme")

    @pytest.mark.parametrize("password", ["short", "1234567"])
    def test_register_enforces_min_password_length(self, password):
        """パスワードは 8 文字以上であること"""
        with pytest.raises(ValidationError):
            RegisterBody(email="a@example.com", password=password, org_name="Acme")

    def test_register_rejects_overlong_password(self):
        """パスワードは 128 文字以下であること"""
        with pytest.raises(ValidationError):
            RegisterBody(email="a@example.com", password="x" * 129, org_name="Acme")

    def test_register_requires_org_name_length(self):
        """組織名は 2〜120 文字であること"""
        with pytest.raises(ValidationError):
            RegisterBody(email="a@example.com", password="password1", org_name="A")

    def test_register_accepts_valid_input(self):
        """妥当な入力は受け付けること"""
        body = RegisterBody(email="a@example.com", password="password1", org_name="Acme")
        assert body.org_name == "Acme"

    def test_login_password_has_no_length_limit(self):
        """ログイン時はパスワード長を制限しないこと（既存ユーザーを締め出さない）"""
        assert LoginBody(email="a@example.com", password="x").password == "x"

    def test_api_key_name_defaults(self):
        """API キー名の既定値があること"""
        assert ApiKeyBody().name == "API Key"

    def test_api_key_name_is_length_limited(self):
        """API キー名は 80 文字以下であること"""
        with pytest.raises(ValidationError):
            ApiKeyBody(name="x" * 81)

    @pytest.mark.parametrize("plan", ["free", "pro", "enterprise"])
    def test_upgrade_accepts_known_plans(self, plan):
        """既知のプランを受け付けること"""
        assert PlanUpgradeBody(plan=plan).plan == plan

    @pytest.mark.parametrize("plan", ["trial", "PRO", "", "gold"])
    def test_upgrade_rejects_unknown_plans(self, plan):
        """未知のプランは弾くこと"""
        with pytest.raises(ValidationError):
            PlanUpgradeBody(plan=plan)

    def test_checkout_rejects_free_plan(self):
        """課金不要の free は Checkout 対象外であること"""
        with pytest.raises(ValidationError):
            CheckoutBody(plan="free")

    def test_checkout_urls_are_optional(self):
        """リダイレクト URL は省略可能であること"""
        body = CheckoutBody(plan="pro")
        assert body.success_url is None and body.cancel_url is None


class TestAuthHelpers:
    """_current_user_id / _current_tenant_id / _require_owner のテスト"""

    def test_current_user_id_returns_id(self):
        """JWT 認証ならユーザー ID を返すこと"""
        ctx = TenantContext(tenant_id=1, tenant_slug="a", plan="free", user_id=7)
        assert _current_user_id(make_request(ctx)) == 7

    def test_current_user_id_rejects_unauthenticated(self):
        """未認証では 401 になること"""
        with pytest.raises(Exception) as exc:
            _current_user_id(make_request())
        assert exc.value.status_code == 401

    def test_current_user_id_rejects_api_key_auth(self):
        """API キー認証（user_id なし）では 401 になること"""
        ctx = TenantContext(tenant_id=1, tenant_slug="a", plan="free",
                            user_id=None, auth_via="api_key")
        with pytest.raises(Exception) as exc:
            _current_user_id(make_request(ctx))
        assert exc.value.status_code == 401
        assert "JWT ログインが必要です" in exc.value.detail

    def test_current_tenant_id_works_for_api_key(self):
        """API キー認証でもテナント ID は取得できること"""
        ctx = TenantContext(tenant_id=5, tenant_slug="a", plan="pro", auth_via="api_key")
        assert _current_tenant_id(make_request(ctx)) == 5

    def test_current_tenant_id_rejects_unauthenticated(self):
        """未認証では 401 になること"""
        with pytest.raises(Exception) as exc:
            _current_tenant_id(make_request())
        assert exc.value.status_code == 401

    def test_require_owner_allows_owner(self):
        """オーナーは通過すること"""
        ctx = TenantContext(tenant_id=1, tenant_slug="a", plan="free", role="owner")
        assert _require_owner(make_request(ctx)) is None

    def test_require_owner_blocks_member(self):
        """オーナー以外の JWT ユーザーは 403 になること"""
        ctx = TenantContext(tenant_id=1, tenant_slug="a", plan="free", role="member")
        with pytest.raises(Exception) as exc:
            _require_owner(make_request(ctx))
        assert exc.value.status_code == 403

    def test_require_owner_skips_check_for_api_key(self):
        """API キー認証はロールを持たないため確認をスキップすること"""
        ctx = TenantContext(tenant_id=1, tenant_slug="a", plan="pro",
                            role=None, auth_via="api_key")
        assert _require_owner(make_request(ctx)) is None


class TestRegisterEndpoint:
    """POST /api/auth/register のテスト"""

    BODY = {"email": "a@example.com", "password": "password1", "org_name": "Acme"}

    def test_returns_token_on_success(self, client):
        """登録に成功するとサービス層の結果をそのまま返すこと"""
        payload = {"access_token": "t", "token_type": "bearer", "user": {}, "tenant": {}}
        with patch("src.auth.router.register_tenant", return_value=payload):
            res = client.post("/api/auth/register", json=self.BODY)

        assert res.status_code == 200
        assert res.json() == payload

    def test_duplicate_email_returns_400(self, client):
        """重複メールは 400 とメッセージを返すこと"""
        with patch("src.auth.router.register_tenant",
                   side_effect=ValueError("このメールアドレスは既に登録されています")):
            res = client.post("/api/auth/register", json=self.BODY)

        assert res.status_code == 400
        assert res.json()["detail"] == "このメールアドレスは既に登録されています"

    def test_saas_disabled_returns_503(self, client, override_settings):
        """SaaS 無効時は 503 を返すこと"""
        override_settings(saas_enabled=False)
        assert client.post("/api/auth/register", json=self.BODY).status_code == 503

    def test_missing_table_gives_actionable_message(self, client, db_session):
        """テーブル未作成のエラーは再起動を促すメッセージに変換すること"""
        with patch("src.auth.router.register_tenant",
                   side_effect=RuntimeError('relation "tenants" does not exist')):
            res = client.post("/api/auth/register", json=self.BODY)

        assert res.status_code == 500
        assert "認証テーブルが未作成です" in res.json()["detail"]
        db_session.rollback.assert_called_once()

    def test_missing_dependency_gives_actionable_message(self, client):
        """依存不足のエラーは再デプロイを促すメッセージに変換すること"""
        with patch("src.auth.router.register_tenant",
                   side_effect=ImportError("No module named 'bcrypt'")):
            res = client.post("/api/auth/register", json=self.BODY)

        assert res.status_code == 500
        assert "サーバー依存関係が不足しています" in res.json()["detail"]

    def test_unknown_error_gives_generic_message(self, client):
        """想定外のエラーは汎用メッセージにすること（内部情報を漏らさない）"""
        with patch("src.auth.router.register_tenant", side_effect=RuntimeError("secret detail")):
            res = client.post("/api/auth/register", json=self.BODY)

        assert res.status_code == 500
        assert "secret detail" not in res.json()["detail"]

    def test_invalid_body_returns_422(self, client):
        """バリデーションエラーは 422 になること"""
        assert client.post("/api/auth/register", json={"email": "x"}).status_code == 422


class TestLoginEndpoint:
    """POST /api/auth/login のテスト"""

    BODY = {"email": "a@example.com", "password": "password1"}

    def test_returns_token_on_success(self, client):
        """認証成功でトークンを返すこと"""
        with patch("src.auth.router.login_user", return_value={"access_token": "t"}):
            res = client.post("/api/auth/login", json=self.BODY)
        assert res.json()["access_token"] == "t"

    def test_invalid_credentials_return_401(self, client):
        """資格情報の誤りは 401 になること（404 ではない）"""
        with patch("src.auth.router.login_user",
                   side_effect=ValueError("メールアドレスまたはパスワードが正しくありません")):
            res = client.post("/api/auth/login", json=self.BODY)

        assert res.status_code == 401

    def test_saas_disabled_returns_503(self, client, override_settings):
        """SaaS 無効時は 503 を返すこと"""
        override_settings(saas_enabled=False)
        assert client.post("/api/auth/login", json=self.BODY).status_code == 503

    def test_unexpected_error_returns_500(self, client, db_session):
        """想定外エラーは 500 にしてロールバックすること"""
        with patch("src.auth.router.login_user", side_effect=RuntimeError("boom")):
            res = client.post("/api/auth/login", json=self.BODY)

        assert res.status_code == 500
        db_session.rollback.assert_called_once()


class TestMeEndpoint:
    """GET /api/auth/me のテスト"""

    def test_requires_jwt(self, client):
        """未認証では 401 になること"""
        assert client.get("/api/auth/me").status_code == 401

    def test_api_key_auth_is_rejected(self, client):
        """API キー認証では利用できないこと"""
        assert client.get("/api/auth/me", headers=as_api_key()).status_code == 401

    def test_returns_session(self, client):
        """認証済みならセッション情報を返すこと"""
        with patch("src.auth.router.get_me", return_value={"user": {"id": 10}}) as get_me:
            res = client.get("/api/auth/me", headers=as_owner(user_id=10))

        assert res.json()["user"]["id"] == 10
        assert get_me.call_args[0][1] == 10

    def test_missing_user_returns_404(self, client):
        """ユーザーが見つからない場合は 404 になること"""
        with patch("src.auth.router.get_me", side_effect=ValueError("User not found")):
            assert client.get("/api/auth/me", headers=as_owner()).status_code == 404


class TestApiKeyEndpoints:
    """API キーの一覧・発行エンドポイントのテスト"""

    def test_list_requires_authentication(self, client):
        """未認証では 401 になること"""
        assert client.get("/api/auth/api-keys").status_code == 401

    def test_list_returns_keys(self, client):
        """キー一覧を返すこと"""
        with patch("src.auth.router.list_api_keys", return_value=[{"id": 1}]):
            res = client.get("/api/auth/api-keys", headers=as_owner())
        assert res.json() == {"keys": [{"id": 1}]}

    def test_list_is_scoped_to_the_tenant(self, client):
        """自テナントのキーのみを引くこと"""
        with patch("src.auth.router.list_api_keys", return_value=[]) as list_keys:
            client.get("/api/auth/api-keys", headers=as_owner(tenant_id=42))
        assert list_keys.call_args[0][1] == 42

    def test_api_key_auth_can_list(self, client):
        """API キー認証でも一覧を取得できること"""
        with patch("src.auth.router.list_api_keys", return_value=[]):
            assert client.get("/api/auth/api-keys", headers=as_api_key()).status_code == 200

    def test_create_returns_raw_key(self, client):
        """発行結果（生のキーを含む）を返すこと"""
        with patch("src.auth.router.create_api_key", return_value={"api_key": "fx_secret"}):
            res = client.post("/api/auth/api-keys", json={"name": "CI"}, headers=as_owner())
        assert res.json()["api_key"] == "fx_secret"

    def test_create_quota_error_returns_400(self, client):
        """上限到達は 400 とメッセージを返すこと"""
        with patch("src.auth.router.create_api_key",
                   side_effect=ValueError("APIキー上限 (1) に達しています。")):
            res = client.post("/api/auth/api-keys", json={"name": "CI"}, headers=as_owner())

        assert res.status_code == 400
        assert "上限" in res.json()["detail"]


class TestBillingPlansEndpoint:
    """GET /api/billing/plans のテスト"""

    def test_is_public(self, client):
        """未認証でもプラン一覧を取得できること"""
        with patch("src.auth.router.stripe_configured", return_value=False):
            res = client.get("/api/billing/plans")

        assert res.status_code == 200
        assert len(res.json()["plans"]) == 3

    def test_reports_saas_and_stripe_flags(self, client):
        """SaaS / Stripe の有効状態を返すこと"""
        with patch("src.auth.router.stripe_configured", return_value=True):
            body = client.get("/api/billing/plans").json()

        assert body["stripe_enabled"] is True
        assert body["saas_enabled"] is True


class TestBillingStatusEndpoint:
    """GET /api/billing/status のテスト"""

    def test_requires_authentication(self, client):
        """未認証では 401 になること"""
        assert client.get("/api/billing/status").status_code == 401

    def test_missing_tenant_returns_404(self, client, db_session):
        """テナントが見つからない場合は 404 になること"""
        db_session.get.return_value = None
        assert client.get("/api/billing/status", headers=as_owner()).status_code == 404

    def test_includes_usage_summary(self, client, db_session):
        """利用状況（回数・上限・使用率）を付加すること"""
        db_session.get.return_value = SimpleNamespace(plan="free")
        with patch("src.auth.router.billing_status", return_value={"plan": "free"}), \
             patch("src.auth.models.count_daily_usage", return_value=25):
            body = client.get("/api/billing/status", headers=as_owner()).json()

        assert body["usage"] == {
            "daily_calls": 25, "daily_limit": 100, "remaining": 75, "usage_percent": 25.0,
        }


class TestBillingCheckoutEndpoint:
    """POST /api/billing/checkout のテスト"""

    def test_requires_owner(self, client, db_session):
        """オーナー以外は 403 になること"""
        res = client.post("/api/billing/checkout", json={"plan": "pro"}, headers=as_member())
        assert res.status_code == 403

    def test_returns_checkout_url(self, client, db_session):
        """Stripe の Checkout URL を返すこと"""
        db_session.get.return_value = SimpleNamespace(plan="free")
        with patch("src.auth.router.create_checkout_session", return_value="https://stripe/x"):
            res = client.post("/api/billing/checkout", json={"plan": "pro"}, headers=as_owner())

        assert res.json() == {"checkout_url": "https://stripe/x"}

    def test_defaults_redirect_urls_from_public_url(self, client, db_session, override_settings):
        """リダイレクト URL 未指定なら公開 URL から組み立てること"""
        override_settings(app_public_url="https://fx.example.com/")
        db_session.get.return_value = SimpleNamespace(plan="free")
        with patch("src.auth.router.create_checkout_session", return_value="u") as create:
            client.post("/api/billing/checkout", json={"plan": "pro"}, headers=as_owner())

        _, _, _, success, cancel, _ = create.call_args[0]
        assert success == "https://fx.example.com/settings?checkout=success"
        assert cancel == "https://fx.example.com/settings?checkout=cancel"

    def test_custom_redirect_urls_are_used(self, client, db_session):
        """指定されたリダイレクト URL を優先すること"""
        db_session.get.return_value = SimpleNamespace(plan="free")
        with patch("src.auth.router.create_checkout_session", return_value="u") as create:
            client.post("/api/billing/checkout", headers=as_owner(), json={
                "plan": "pro", "success_url": "https://a/ok", "cancel_url": "https://a/ng",
            })

        assert create.call_args[0][3] == "https://a/ok"
        assert create.call_args[0][4] == "https://a/ng"

    def test_stripe_error_returns_400(self, client, db_session):
        """Stripe 側の設定不備は 400 になること"""
        db_session.get.return_value = SimpleNamespace(plan="free")
        with patch("src.auth.router.create_checkout_session",
                   side_effect=ValueError("価格 ID が未設定です")):
            res = client.post("/api/billing/checkout", json={"plan": "pro"}, headers=as_owner())

        assert res.status_code == 400


class TestBillingPortalEndpoint:
    """POST /api/billing/portal のテスト"""

    def test_requires_owner(self, client):
        """オーナー以外は 403 になること"""
        assert client.post("/api/billing/portal", json={}, headers=as_member()).status_code == 403

    def test_returns_portal_url(self, client, db_session):
        """ポータル URL を返すこと"""
        db_session.get.return_value = SimpleNamespace(plan="pro")
        with patch("src.auth.router.create_portal_session", return_value="https://stripe/p"):
            res = client.post("/api/billing/portal", json={}, headers=as_owner())

        assert res.json() == {"portal_url": "https://stripe/p"}

    def test_missing_customer_returns_400(self, client, db_session):
        """Stripe 顧客が未作成なら 400 になること"""
        db_session.get.return_value = SimpleNamespace(plan="pro")
        with patch("src.auth.router.create_portal_session",
                   side_effect=ValueError("Stripe 顧客が未作成です")):
            assert client.post("/api/billing/portal", json={},
                               headers=as_owner()).status_code == 400


class TestBillingUpgradeEndpoint:
    """POST /api/billing/upgrade のテスト"""

    def test_requires_owner(self, client):
        """オーナー以外は 403 になること"""
        res = client.post("/api/billing/upgrade", json={"plan": "pro"}, headers=as_member())
        assert res.status_code == 403

    def test_direct_upgrade_when_stripe_is_disabled(self, client):
        """Stripe 未設定なら直接プラン変更できること"""
        with patch("src.auth.router.stripe_configured", return_value=False), \
             patch("src.auth.router.upgrade_plan", return_value={"plan": "pro"}):
            res = client.post("/api/billing/upgrade", json={"plan": "pro"}, headers=as_owner())

        assert res.status_code == 200
        assert res.json()["tenant"]["plan"] == "pro"

    @pytest.mark.parametrize("plan", ["pro", "enterprise"])
    def test_paid_upgrade_is_blocked_when_stripe_is_enabled(self, client, plan):
        """Stripe 設定済みなら有料プランへの直接変更を拒否すること"""
        with patch("src.auth.router.stripe_configured", return_value=True):
            res = client.post("/api/billing/upgrade", json={"plan": plan}, headers=as_owner())

        assert res.status_code == 400
        assert "Stripe Checkout" in res.json()["detail"]

    def test_downgrade_to_free_is_always_allowed(self, client):
        """free へのダウングレードは Stripe 設定済みでも許可すること"""
        with patch("src.auth.router.stripe_configured", return_value=True), \
             patch("src.auth.router.upgrade_plan", return_value={"plan": "free"}):
            res = client.post("/api/billing/upgrade", json={"plan": "free"}, headers=as_owner())

        assert res.status_code == 200


class TestStripeWebhookEndpoint:
    """POST /api/billing/webhook のテスト"""

    def test_noop_when_secret_is_missing(self, client, override_settings):
        """Webhook シークレット未設定ならノーオペで 200 を返すこと"""
        override_settings(stripe_webhook_secret="")
        body = client.post("/api/billing/webhook", content=b"{}").json()

        assert body["received"] is True
        assert "未設定" in body["note"]

    def test_delegates_to_handler(self, client, override_settings):
        """署名とペイロードをハンドラーへ渡すこと"""
        override_settings(stripe_webhook_secret="whsec_test")
        with patch("src.auth.router.handle_stripe_webhook",
                   return_value={"handled": "checkout.session.completed"}) as handler:
            res = client.post("/api/billing/webhook", content=b'{"id":"evt_1"}',
                              headers={"Stripe-Signature": "sig"})

        assert res.json() == {"received": True, "handled": "checkout.session.completed"}
        assert handler.call_args[0][0] == b'{"id":"evt_1"}'
        assert handler.call_args[0][1] == "sig"

    def test_invalid_signature_returns_400(self, client, override_settings):
        """署名検証に失敗したら 400 を返すこと"""
        override_settings(stripe_webhook_secret="whsec_test")
        with patch("src.auth.router.handle_stripe_webhook",
                   side_effect=ValueError("Invalid signature")):
            assert client.post("/api/billing/webhook", content=b"{}").status_code == 400

    def test_unexpected_error_returns_400_without_details(self, client, override_settings):
        """想定外エラーでも内部情報を返さないこと"""
        override_settings(stripe_webhook_secret="whsec_test")
        with patch("src.auth.router.handle_stripe_webhook", side_effect=RuntimeError("internal")):
            res = client.post("/api/billing/webhook", content=b"{}")

        assert res.status_code == 400
        assert "internal" not in res.json()["detail"]
