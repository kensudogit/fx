"""Stripe 課金連携 — src.billing.stripe_service のテスト

Stripe SDK はモックへ差し替え、設定判定・Checkout / Portal 生成・
Webhook によるプラン反映を検証する。
"""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from src.billing.stripe_service import (
    PLAN_PRICE_ENV,
    _price_id_for_plan,
    billing_status,
    create_checkout_session,
    create_portal_session,
    handle_stripe_webhook,
    stripe_configured,
)


def tenant(**kwargs):
    """Tenant 相当のスタブ。"""
    defaults = dict(id=1, name="Example", slug="example", plan="free",
                    stripe_customer_id=None, stripe_subscription_id=None)
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


@pytest.fixture
def stripe_enabled(override_settings):
    """Stripe を設定済みにする。"""
    override_settings(stripe_secret_key="sk_test_123",
                      stripe_price_pro="price_pro",
                      stripe_price_enterprise="price_ent",
                      stripe_webhook_secret="whsec_test")


class TestStripeConfigured:
    """stripe_configured() のテスト"""

    def test_true_with_a_secret_key(self, override_settings):
        """シークレットキーがあれば有効と判定すること"""
        override_settings(stripe_secret_key="sk_test_123")
        assert stripe_configured() is True

    def test_false_without_a_key(self, override_settings):
        """未設定なら無効と判定すること"""
        override_settings(stripe_secret_key="")
        assert stripe_configured() is False


class TestPriceIdForPlan:
    """_price_id_for_plan() のテスト"""

    def test_maps_paid_plans(self, stripe_enabled):
        """有料プランの Price ID を返すこと"""
        assert _price_id_for_plan("pro") == "price_pro"
        assert _price_id_for_plan("enterprise") == "price_ent"

    def test_free_plan_has_no_price(self):
        """無料プランには Price ID が無いこと"""
        assert _price_id_for_plan("free") is None

    def test_unknown_plan_has_no_price(self):
        """未知のプランには Price ID が無いこと"""
        assert _price_id_for_plan("gold") is None

    def test_unset_price_returns_none(self, override_settings):
        """Price ID が未設定なら None を返すこと"""
        override_settings(stripe_price_pro="")
        assert _price_id_for_plan("pro") is None

    def test_only_paid_plans_are_mapped(self):
        """マッピング対象は有料プランのみであること"""
        assert set(PLAN_PRICE_ENV) == {"pro", "enterprise"}


class TestCreateCheckoutSession:
    """create_checkout_session() のテスト"""

    def _stripe(self, url="https://checkout.stripe.com/s/1"):
        session = MagicMock()
        session.url = url
        module = MagicMock()
        module.checkout.Session.create.return_value = session
        return module

    @pytest.mark.parametrize("plan", ["free", "gold", ""])
    def test_rejects_non_paid_plans(self, plan, stripe_enabled):
        """有料プラン以外は ValueError にすること"""
        with pytest.raises(ValueError, match="pro / enterprise"):
            create_checkout_session(MagicMock(), tenant(), plan, "s", "c")

    def test_requires_stripe_configuration(self, override_settings):
        """Stripe 未設定なら ValueError にすること"""
        override_settings(stripe_secret_key="")
        with pytest.raises(ValueError, match="STRIPE_SECRET_KEY"):
            create_checkout_session(MagicMock(), tenant(), "pro", "s", "c")

    def test_requires_a_price_id(self, override_settings):
        """Price ID 未設定なら ValueError にすること"""
        override_settings(stripe_secret_key="sk_test", stripe_price_pro="")
        with pytest.raises(ValueError, match="Price ID"):
            create_checkout_session(MagicMock(), tenant(), "pro", "s", "c")

    def test_returns_the_checkout_url(self, stripe_enabled):
        """Checkout の URL を返すこと"""
        with patch("src.billing.stripe_service.stripe", self._stripe()):
            url = create_checkout_session(MagicMock(), tenant(), "pro", "s", "c")
        assert url == "https://checkout.stripe.com/s/1"

    def test_sends_tenant_metadata(self, stripe_enabled):
        """Webhook でテナントを特定できるようメタデータを付けること"""
        module = self._stripe()
        with patch("src.billing.stripe_service.stripe", module):
            create_checkout_session(MagicMock(), tenant(id=42), "pro", "s", "c")

        params = module.checkout.Session.create.call_args.kwargs
        assert params["metadata"] == {"tenant_id": "42", "plan": "pro"}
        assert params["subscription_data"]["metadata"]["tenant_id"] == "42"

    def test_reuses_an_existing_customer(self, stripe_enabled):
        """既存の Stripe 顧客があれば再利用すること"""
        module = self._stripe()
        with patch("src.billing.stripe_service.stripe", module):
            create_checkout_session(MagicMock(), tenant(stripe_customer_id="cus_1"),
                                    "pro", "s", "c", customer_email="a@example.com")

        params = module.checkout.Session.create.call_args.kwargs
        assert params["customer"] == "cus_1"
        assert "customer_email" not in params

    def test_uses_the_email_for_new_customers(self, stripe_enabled):
        """顧客未作成ならメールアドレスを渡すこと"""
        module = self._stripe()
        with patch("src.billing.stripe_service.stripe", module):
            create_checkout_session(MagicMock(), tenant(), "pro", "s", "c",
                                    customer_email="a@example.com")

        assert module.checkout.Session.create.call_args.kwargs["customer_email"] == "a@example.com"

    def test_passes_redirect_urls(self, stripe_enabled):
        """成功・キャンセル時のリダイレクト先を渡すこと"""
        module = self._stripe()
        with patch("src.billing.stripe_service.stripe", module):
            create_checkout_session(MagicMock(), tenant(), "pro",
                                    "https://a/ok", "https://a/ng")

        params = module.checkout.Session.create.call_args.kwargs
        assert params["success_url"] == "https://a/ok"
        assert params["cancel_url"] == "https://a/ng"

    def test_missing_url_raises(self, stripe_enabled):
        """Stripe が URL を返さなければ ValueError にすること"""
        with patch("src.billing.stripe_service.stripe", self._stripe(url=None)):
            with pytest.raises(ValueError, match="Checkout URL"):
                create_checkout_session(MagicMock(), tenant(), "pro", "s", "c")


class TestCreatePortalSession:
    """create_portal_session() のテスト"""

    def _stripe(self, url="https://billing.stripe.com/p/1"):
        session = MagicMock()
        session.url = url
        module = MagicMock()
        module.billing_portal.Session.create.return_value = session
        return module

    def test_requires_stripe_configuration(self, override_settings):
        """Stripe 未設定なら ValueError にすること"""
        override_settings(stripe_secret_key="")
        with pytest.raises(ValueError, match="STRIPE_SECRET_KEY"):
            create_portal_session(tenant(stripe_customer_id="cus_1"), "https://a")

    def test_requires_a_customer(self, stripe_enabled):
        """Stripe 顧客が未作成なら分かりやすいエラーにすること"""
        with pytest.raises(ValueError, match="Stripe 顧客 ID がありません"):
            create_portal_session(tenant(), "https://a")

    def test_returns_the_portal_url(self, stripe_enabled):
        """ポータル URL を返すこと"""
        with patch("src.billing.stripe_service.stripe", self._stripe()):
            url = create_portal_session(tenant(stripe_customer_id="cus_1"), "https://a")
        assert url == "https://billing.stripe.com/p/1"

    def test_passes_the_return_url(self, stripe_enabled):
        """戻り先 URL を渡すこと"""
        module = self._stripe()
        with patch("src.billing.stripe_service.stripe", module):
            create_portal_session(tenant(stripe_customer_id="cus_1"), "https://a/settings")

        assert module.billing_portal.Session.create.call_args.kwargs["return_url"] \
            == "https://a/settings"

    def test_missing_url_raises(self, stripe_enabled):
        """URL が返らなければ ValueError にすること"""
        with patch("src.billing.stripe_service.stripe", self._stripe(url=None)):
            with pytest.raises(ValueError, match="ポータル URL"):
                create_portal_session(tenant(stripe_customer_id="cus_1"), "https://a")


class TestHandleStripeWebhook:
    """handle_stripe_webhook() のテスト"""

    def _stripe(self, event):
        module = MagicMock()
        module.Webhook.construct_event.return_value = event
        return module

    def _db(self, tenant_row=None):
        db = MagicMock()
        db.get.return_value = tenant_row
        return db

    def test_requires_the_webhook_secret(self, override_settings):
        """Webhook シークレット未設定なら ValueError にすること"""
        override_settings(stripe_webhook_secret="")
        with pytest.raises(ValueError, match="STRIPE_WEBHOOK_SECRET"):
            handle_stripe_webhook(b"{}", "sig", MagicMock())

    def test_requires_the_api_key(self, override_settings):
        """API キー未設定なら ValueError にすること"""
        override_settings(stripe_webhook_secret="whsec", stripe_secret_key="")
        with pytest.raises(ValueError, match="STRIPE_SECRET_KEY"):
            handle_stripe_webhook(b"{}", "sig", MagicMock())

    def test_verifies_the_signature(self, stripe_enabled):
        """署名検証を行うこと"""
        module = self._stripe({"type": "unknown", "data": {"object": {}}})
        with patch("src.billing.stripe_service.stripe", module):
            handle_stripe_webhook(b'{"id":"evt"}', "sig-header", MagicMock())

        args = module.Webhook.construct_event.call_args[0]
        assert args[0] == b'{"id":"evt"}'
        assert args[1] == "sig-header"

    def test_unknown_events_are_ignored(self, stripe_enabled):
        """未対応イベントは handled=False で返すこと"""
        module = self._stripe({"type": "invoice.paid", "data": {"object": {}}})
        with patch("src.billing.stripe_service.stripe", module):
            result = handle_stripe_webhook(b"{}", "sig", MagicMock())

        assert result == {"handled": False, "type": "invoice.paid"}

    def test_checkout_completed_upgrades_the_tenant(self, stripe_enabled):
        """決済完了でプランと Stripe ID を反映すること"""
        row = tenant(id=42)
        db = self._db(row)
        event = {"type": "checkout.session.completed", "data": {"object": {
            "metadata": {"tenant_id": "42", "plan": "pro"},
            "customer": "cus_1", "subscription": "sub_1",
        }}}
        with patch("src.billing.stripe_service.stripe", self._stripe(event)):
            result = handle_stripe_webhook(b"{}", "sig", db)

        assert result["handled"] is True
        assert row.plan == "pro"
        assert row.stripe_customer_id == "cus_1"
        assert row.stripe_subscription_id == "sub_1"
        db.commit.assert_called_once()

    def test_checkout_for_unknown_tenant_is_ignored(self, stripe_enabled):
        """存在しないテナントのイベントは無視すること"""
        event = {"type": "checkout.session.completed", "data": {"object": {
            "metadata": {"tenant_id": "999", "plan": "pro"},
        }}}
        with patch("src.billing.stripe_service.stripe", self._stripe(event)):
            result = handle_stripe_webhook(b"{}", "sig", self._db(None))

        assert result == {"handled": False, "reason": "tenant_not_found"}

    @pytest.mark.parametrize("status", ["active", "trialing"])
    def test_active_subscription_sets_the_plan(self, stripe_enabled, status):
        """有効なサブスクリプションでプランを設定すること"""
        row = tenant(id=1)
        event = {"type": "customer.subscription.updated", "data": {"object": {
            "metadata": {"tenant_id": "1", "plan": "enterprise"},
            "status": status, "id": "sub_1", "customer": "cus_1",
        }}}
        with patch("src.billing.stripe_service.stripe", self._stripe(event)):
            result = handle_stripe_webhook(b"{}", "sig", self._db(row))

        assert result["plan"] == "enterprise"
        assert row.plan == "enterprise"

    @pytest.mark.parametrize("status", ["canceled", "unpaid", "past_due"])
    def test_failed_subscription_downgrades_to_free(self, stripe_enabled, status):
        """支払い不能・解約ではフリープランへ降格すること"""
        row = tenant(id=1, plan="pro")
        event = {"type": "customer.subscription.updated", "data": {"object": {
            "metadata": {"tenant_id": "1", "plan": "pro"}, "status": status,
        }}}
        with patch("src.billing.stripe_service.stripe", self._stripe(event)):
            result = handle_stripe_webhook(b"{}", "sig", self._db(row))

        assert result["plan"] == "free"
        assert row.plan == "free"

    def test_other_statuses_are_not_handled(self, stripe_enabled):
        """その他のステータスは変更しないこと"""
        row = tenant(id=1, plan="pro")
        event = {"type": "customer.subscription.updated", "data": {"object": {
            "metadata": {"tenant_id": "1", "plan": "pro"}, "status": "incomplete",
        }}}
        with patch("src.billing.stripe_service.stripe", self._stripe(event)):
            result = handle_stripe_webhook(b"{}", "sig", self._db(row))

        assert result["handled"] is False
        assert row.plan == "pro"

    def test_deleted_subscription_clears_the_plan(self, stripe_enabled):
        """サブスクリプション削除でフリーへ戻し ID を消すこと"""
        row = tenant(id=1, plan="pro", stripe_subscription_id="sub_1")
        event = {"type": "customer.subscription.deleted", "data": {"object": {
            "metadata": {"tenant_id": "1"},
        }}}
        with patch("src.billing.stripe_service.stripe", self._stripe(event)):
            result = handle_stripe_webhook(b"{}", "sig", self._db(row))

        assert result["plan"] == "free"
        assert row.plan == "free"
        assert row.stripe_subscription_id is None


class TestBillingStatus:
    """billing_status() のテスト"""

    def test_reports_the_current_plan(self):
        """現在のプラン情報を返すこと"""
        status = billing_status(tenant(plan="pro"))

        assert status["plan"] == "pro"
        assert status["plan_name"] == "Pro"
        assert status["daily_api_limit"] == 2000

    def test_unknown_plan_falls_back_to_free(self):
        """未知のプランは free として扱うこと"""
        assert billing_status(tenant(plan="gold"))["plan"] == "free"

    def test_subscription_flag(self):
        """サブスクリプションの有無を真偽値で返すこと"""
        assert billing_status(tenant(stripe_subscription_id="sub_1"))[
            "has_active_subscription"] is True
        assert billing_status(tenant())["has_active_subscription"] is False

    def test_includes_the_stripe_flag(self, stripe_enabled):
        """Stripe の有効状態を含めること"""
        assert billing_status(tenant())["stripe_enabled"] is True
