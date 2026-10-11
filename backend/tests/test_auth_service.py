"""認証・テナント管理のサービス層 — src.auth.service のテスト

DB へは接続せず、SQLAlchemy の Session をモックに差し替えて
ビジネスロジック（スラグ生成・重複検知・上限判定・ペイロード整形）を検証する。
"""

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from src.auth.service import (
    TenantContext,
    _slugify,
    _tenant_payload,
    _user_payload,
    create_api_key,
    get_me,
    list_api_keys,
    login_user,
    register_tenant,
    resolve_api_key,
    upgrade_plan,
)
from src.auth.security import hash_api_key, hash_password


def fake_tenant(**kwargs):
    """Tenant 相当のスタブを作る。"""
    defaults = dict(id=1, name="Example", slug="example", plan="free",
                    stripe_customer_id=None, stripe_subscription_id=None)
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


def fake_user(**kwargs):
    """User 相当のスタブを作る。"""
    defaults = dict(id=10, tenant_id=1, email="a@example.com",
                    password_hash=hash_password("password1"), role="owner")
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


def scalar_session(scalar_one=None, scalars_all=None, first=None, get_map=None):
    """execute() の戻り値を制御するモックセッションを作る。"""
    session = MagicMock()
    result = session.execute.return_value
    result.scalar_one_or_none.return_value = scalar_one
    result.scalars.return_value.all.return_value = scalars_all or []
    result.first.return_value = first
    if get_map is not None:
        session.get.side_effect = lambda model, pk: get_map.get(pk)
    return session


@pytest.fixture(autouse=True)
def no_table_init():
    """テーブル初期化は DB に触れるため無効化する。"""
    with patch("src.auth.service.init_auth_tables"):
        yield


class TestSlugify:
    """_slugify() のテスト"""

    def test_lowercases_and_hyphenates(self):
        """小文字化しつつ空白をハイフンにすること"""
        assert _slugify("My Company") == "my-company"

    def test_collapses_non_alphanumeric_runs(self):
        """英数字以外の連続はハイフン 1 つにまとめること"""
        assert _slugify("A!!!  B___C") == "a-b-c"

    def test_strips_leading_and_trailing_hyphens(self):
        """先頭・末尾のハイフンを除去すること"""
        assert _slugify("  !Example!  ") == "example"

    def test_truncates_to_60_chars(self):
        """60 文字に切り詰めること"""
        assert len(_slugify("a" * 200)) == 60

    def test_falls_back_for_non_ascii_names(self):
        """日本語のみの組織名は workspace にフォールバックすること"""
        assert _slugify("株式会社テスト") == "workspace"

    def test_falls_back_for_empty_name(self):
        """空文字・記号のみでも必ずスラグを返すこと"""
        assert _slugify("") == "workspace"
        assert _slugify("!!!") == "workspace"

    def test_keeps_digits(self):
        """数字は保持すること"""
        assert _slugify("Team 2026") == "team-2026"


class TestRegisterTenant:
    """register_tenant() のテスト"""

    def _session_for_registration(self, existing_user=None, taken_slugs=()):
        """登録用のモックセッション。slug 重複は taken_slugs で再現する。"""
        session = MagicMock()
        calls = {"n": 0}

        def execute(stmt):
            result = MagicMock()
            calls["n"] += 1
            if calls["n"] == 1:
                # 1 回目: メールアドレスの重複チェック
                result.scalar_one_or_none.return_value = existing_user
            else:
                # 2 回目以降: スラグの重複チェック
                slug_index = calls["n"] - 2
                candidates = ["example"] + [f"example-{i}" for i in range(1, 10)]
                candidate = candidates[slug_index] if slug_index < len(candidates) else None
                result.scalar_one_or_none.return_value = (
                    fake_tenant(slug=candidate) if candidate in taken_slugs else None
                )
            return result

        session.execute.side_effect = execute
        return session

    def test_rejects_duplicate_email(self):
        """登録済みメールアドレスは ValueError になること"""
        session = self._session_for_registration(existing_user=fake_user())
        with pytest.raises(ValueError, match="既に登録されています"):
            register_tenant(session, "a@example.com", "password1", "Example")

    def test_email_is_normalized_before_duplicate_check(self):
        """大文字・前後空白を正規化してから重複判定すること"""
        session = self._session_for_registration(existing_user=fake_user())
        with pytest.raises(ValueError):
            register_tenant(session, "  A@Example.COM  ", "password1", "Example")

    def test_creates_tenant_and_owner_user(self):
        """テナントとオーナーユーザーを作成しトークンを返すこと"""
        session = self._session_for_registration()
        with patch("src.auth.service.create_access_token", return_value="jwt-token"):
            result = register_tenant(session, "a@example.com", "password1", "Example Inc")

        tenant, user = session.add.call_args_list[0][0][0], session.add.call_args_list[1][0][0]
        assert tenant.name == "Example Inc"
        assert tenant.slug == "example-inc"
        assert user.role == "owner"
        assert user.email == "a@example.com"
        assert result["access_token"] == "jwt-token"
        assert result["token_type"] == "bearer"

    def test_password_is_hashed_not_stored_raw(self):
        """パスワードはハッシュ化して保存すること"""
        session = self._session_for_registration()
        with patch("src.auth.service.create_access_token", return_value="t"):
            register_tenant(session, "a@example.com", "password1", "Example")

        user = session.add.call_args_list[1][0][0]
        assert user.password_hash != "password1"
        assert user.password_hash.startswith("$2b$")

    def test_appends_suffix_when_slug_is_taken(self):
        """スラグが衝突したら連番サフィックスを付けること"""
        session = self._session_for_registration(taken_slugs={"example", "example-1"})
        with patch("src.auth.service.create_access_token", return_value="t"):
            register_tenant(session, "a@example.com", "password1", "Example")

        assert session.add.call_args_list[0][0][0].slug == "example-2"

    def test_uses_default_plan_from_settings(self, override_settings):
        """新規テナントは設定の既定プランになること"""
        override_settings(saas_default_plan="pro")
        session = self._session_for_registration()
        with patch("src.auth.service.create_access_token", return_value="t"):
            register_tenant(session, "a@example.com", "password1", "Example")

        assert session.add.call_args_list[0][0][0].plan == "pro"

    def test_commits_once_for_atomicity(self):
        """テナントとユーザーを 1 トランザクションでコミットすること"""
        session = self._session_for_registration()
        with patch("src.auth.service.create_access_token", return_value="t"):
            register_tenant(session, "a@example.com", "password1", "Example")
        session.commit.assert_called_once()


class TestLoginUser:
    """login_user() のテスト"""

    def test_returns_token_on_success(self):
        """正しい資格情報でトークンを返すこと"""
        user = fake_user()
        session = scalar_session(scalar_one=user, get_map={1: fake_tenant()})
        with patch("src.auth.service.create_access_token", return_value="jwt-token"):
            result = login_user(session, "a@example.com", "password1")

        assert result["access_token"] == "jwt-token"
        assert result["user"]["email"] == "a@example.com"
        assert result["tenant"]["slug"] == "example"

    def test_unknown_email_and_wrong_password_share_one_message(self):
        """ユーザー列挙攻撃を防ぐため、両者のエラーメッセージが同一であること"""
        no_user = scalar_session(scalar_one=None)
        with pytest.raises(ValueError) as unknown:
            login_user(no_user, "nobody@example.com", "password1")

        bad_pwd = scalar_session(scalar_one=fake_user(), get_map={1: fake_tenant()})
        with pytest.raises(ValueError) as wrong:
            login_user(bad_pwd, "a@example.com", "wrong-password")

        assert str(unknown.value) == str(wrong.value)
        assert "正しくありません" in str(unknown.value)

    def test_email_is_normalized(self):
        """大文字・空白を正規化してから照合すること"""
        session = scalar_session(scalar_one=fake_user(), get_map={1: fake_tenant()})
        with patch("src.auth.service.create_access_token", return_value="t"):
            assert login_user(session, "  A@Example.COM ", "password1")["token_type"] == "bearer"


class TestGetMe:
    """get_me() のテスト"""

    def _call(self, usage: int, plan: str = "free", **tenant_kwargs):
        user = fake_user()
        tenant = fake_tenant(plan=plan, **tenant_kwargs)
        session = MagicMock()
        session.get.side_effect = lambda model, pk: user if pk == 10 else tenant
        with patch("src.auth.service.count_daily_usage", return_value=usage):
            return get_me(session, 10)

    def test_raises_for_unknown_user(self):
        """存在しないユーザーは ValueError になること"""
        session = MagicMock()
        session.get.return_value = None
        with pytest.raises(ValueError, match="User not found"):
            get_me(session, 999)

    def test_reports_usage_counts(self):
        """利用回数・上限・残回数を返すこと（free は 100 回）"""
        usage = self._call(40)["usage"]
        assert usage["daily_calls"] == 40
        assert usage["daily_limit"] == 100
        assert usage["remaining"] == 60
        assert usage["usage_percent"] == 40.0

    def test_remaining_never_goes_negative(self):
        """上限超過しても残回数は 0 止まりであること"""
        assert self._call(150)["usage"]["remaining"] == 0

    @pytest.mark.parametrize("usage,level", [
        (0, "ok"),
        (74, "ok"),
        (75, "warning"),
        (89, "warning"),
        (90, "critical"),
        (99, "critical"),
        (100, "exhausted"),
        (500, "exhausted"),
    ])
    def test_usage_level_thresholds(self, usage, level):
        """利用率に応じた警告レベルを返すこと"""
        assert self._call(usage)["usage"]["usage_level"] == level

    def test_features_follow_the_plan(self):
        """プランに応じたフィーチャーフラグを返すこと"""
        assert self._call(0, plan="free")["features"]["autotrade"] is False
        assert self._call(0, plan="pro")["features"]["autotrade"] is True

    def test_limit_follows_the_plan(self):
        """上限はプランに連動すること"""
        assert self._call(0, plan="pro")["usage"]["daily_limit"] == 2000

    def test_billing_flags_are_booleans(self):
        """Stripe 連携状態は真偽値で返すこと（ID 値は露出しない）"""
        billing = self._call(0, stripe_customer_id="cus_1", stripe_subscription_id="sub_1")["billing"]
        assert billing == {"stripe_customer": True, "stripe_subscription": True}

    def test_billing_flags_false_when_not_linked(self):
        """未連携なら両方 False になること"""
        assert self._call(0)["billing"] == {"stripe_customer": False, "stripe_subscription": False}


class TestResolveApiKey:
    """resolve_api_key() のテスト"""

    def test_rejects_keys_without_prefix(self):
        """fx_ で始まらないキーは DB を引かずに拒否すること"""
        session = MagicMock()
        assert resolve_api_key(session, "bearer-token") is None
        session.execute.assert_not_called()

    def test_returns_none_for_unknown_key(self):
        """一致するキーが無ければ None を返すこと"""
        assert resolve_api_key(scalar_session(first=None), "fx_unknown") is None

    def test_returns_tenant_context_for_valid_key(self):
        """有効なキーならテナントコンテキストを返すこと"""
        row = SimpleNamespace(last_used_at=None)
        tenant = fake_tenant(id=5, slug="acme", plan="pro")
        ctx = resolve_api_key(scalar_session(first=(row, tenant)), "fx_valid")

        assert isinstance(ctx, TenantContext)
        assert (ctx.tenant_id, ctx.tenant_slug, ctx.plan) == (5, "acme", "pro")

    def test_updates_last_used_timestamp(self):
        """最終使用日時を更新してコミットすること"""
        row = SimpleNamespace(last_used_at=None)
        session = scalar_session(first=(row, fake_tenant()))
        resolve_api_key(session, "fx_valid")

        assert isinstance(row.last_used_at, datetime)
        assert row.last_used_at.tzinfo is timezone.utc
        session.commit.assert_called_once()

    def test_looks_up_by_hash_not_raw_key(self):
        """生のキーではなく SHA-256 ハッシュで検索すること"""
        session = scalar_session(first=None)
        resolve_api_key(session, "fx_secret")

        compiled = str(session.execute.call_args[0][0].compile(
            compile_kwargs={"literal_binds": True}))
        assert hash_api_key("fx_secret") in compiled
        assert "fx_secret" not in compiled


class TestCreateApiKey:
    """create_api_key() のテスト"""

    def _session(self, plan="free", existing=0):
        session = MagicMock()
        session.get.return_value = fake_tenant(plan=plan)
        session.execute.return_value.scalars.return_value.all.return_value = [object()] * existing

        def refresh(row):
            row.id = 1
            row.created_at = datetime(2026, 1, 1, tzinfo=timezone.utc)

        session.refresh.side_effect = refresh
        return session

    def test_raises_for_unknown_tenant(self):
        """存在しないテナントは ValueError になること"""
        session = MagicMock()
        session.get.return_value = None
        with pytest.raises(ValueError, match="Tenant not found"):
            create_api_key(session, 999, "key")

    def test_returns_raw_key_once(self):
        """生のキーは返り値に 1 度だけ含まれること"""
        result = create_api_key(self._session(), 1, "Webhook")
        assert result["api_key"].startswith("fx_")
        assert result["key_prefix"].endswith("...")

    def test_stores_only_the_hash(self):
        """DB には生のキーではなくハッシュを保存すること"""
        session = self._session()
        result = create_api_key(session, 1, "Webhook")

        row = session.add.call_args[0][0]
        assert row.key_hash == hash_api_key(result["api_key"])
        assert not hasattr(row, "raw_key")

    def test_blank_name_falls_back_to_default(self):
        """名前が空なら既定名を使うこと"""
        session = self._session()
        create_api_key(session, 1, "   ")
        assert session.add.call_args[0][0].name == "API Key"

    @pytest.mark.parametrize("plan,quota", [("free", 1), ("pro", 5), ("enterprise", 50)])
    def test_enforces_plan_quota(self, plan, quota):
        """プランごとの発行上限に達したら ValueError になること"""
        with pytest.raises(ValueError, match=f"上限 \\({quota}\\)"):
            create_api_key(self._session(plan=plan, existing=quota), 1, "key")

    def test_allows_creation_below_quota(self):
        """上限未満なら発行できること"""
        assert create_api_key(self._session(plan="pro", existing=4), 1, "key")["api_key"]


class TestListApiKeys:
    """list_api_keys() のテスト"""

    def test_returns_empty_list_when_none(self):
        """キーが無ければ空リストを返すこと"""
        assert list_api_keys(scalar_session(scalars_all=[]), 1) == []

    def test_never_exposes_raw_or_hashed_key(self):
        """一覧には生のキーもハッシュも含めないこと"""
        row = SimpleNamespace(id=1, name="k", key_prefix="fx_abc...",
                              key_hash="deadbeef", last_used_at=None, created_at=None)
        entry = list_api_keys(scalar_session(scalars_all=[row]), 1)[0]

        assert set(entry) == {"id", "name", "key_prefix", "last_used_at", "created_at"}
        assert "deadbeef" not in str(entry)

    def test_formats_timestamps_as_iso(self):
        """日時は ISO 8601 文字列で返すこと"""
        ts = datetime(2026, 1, 2, 3, 4, 5, tzinfo=timezone.utc)
        row = SimpleNamespace(id=1, name="k", key_prefix="p", last_used_at=ts, created_at=ts)
        entry = list_api_keys(scalar_session(scalars_all=[row]), 1)[0]

        assert entry["created_at"] == ts.isoformat()
        assert entry["last_used_at"] == ts.isoformat()

    def test_null_timestamps_become_none(self):
        """未使用キーの最終使用日時は None のままにすること"""
        row = SimpleNamespace(id=1, name="k", key_prefix="p", last_used_at=None, created_at=None)
        assert list_api_keys(scalar_session(scalars_all=[row]), 1)[0]["last_used_at"] is None


class TestUpgradePlan:
    """upgrade_plan() のテスト"""

    @pytest.mark.parametrize("plan", ["free", "pro", "enterprise"])
    def test_accepts_known_plans(self, plan):
        """既知のプランへ変更できること"""
        tenant = fake_tenant()
        session = MagicMock()
        session.get.return_value = tenant

        assert upgrade_plan(session, 1, plan)["plan"] == plan
        assert tenant.plan == plan
        session.commit.assert_called_once()

    @pytest.mark.parametrize("plan", ["", "trial", "PRO", "gold"])
    def test_rejects_unknown_plans(self, plan):
        """未知のプランは ValueError になること"""
        with pytest.raises(ValueError, match="Invalid plan"):
            upgrade_plan(MagicMock(), 1, plan)

    def test_rejects_unknown_tenant(self):
        """存在しないテナントは ValueError になること"""
        session = MagicMock()
        session.get.return_value = None
        with pytest.raises(ValueError, match="Tenant not found"):
            upgrade_plan(session, 999, "pro")


class TestPayloads:
    """_user_payload() / _tenant_payload() のテスト"""

    def test_user_payload_excludes_password_hash(self):
        """ユーザーのペイロードにパスワードハッシュを含めないこと"""
        payload = _user_payload(fake_user())
        assert set(payload) == {"id", "email", "role", "tenant_id"}
        assert "password_hash" not in payload

    def test_tenant_payload_hides_subscription_id(self):
        """サブスクリプション ID は真偽値に丸めて返すこと"""
        payload = _tenant_payload(fake_tenant(stripe_subscription_id="sub_secret"))
        assert payload["has_stripe_subscription"] is True
        assert "sub_secret" not in str(payload)

    def test_tenant_payload_fields(self):
        """テナントのペイロードが想定どおりのキーを持つこと"""
        assert set(_tenant_payload(fake_tenant())) == {
            "id", "name", "slug", "plan", "stripe_customer_id", "has_stripe_subscription",
        }


class TestTenantContextDataclass:
    """TenantContext データクラスのテスト"""

    def test_defaults_to_jwt_auth(self):
        """既定の認証方式は JWT であること"""
        ctx = TenantContext(tenant_id=1, tenant_slug="x", plan="free")
        assert ctx.auth_via == "jwt"
        assert ctx.user_id is None

    def test_api_key_context_has_no_user(self):
        """API キー認証ではユーザー情報を持たないこと"""
        ctx = TenantContext(tenant_id=1, tenant_slug="x", plan="pro", auth_via="api_key")
        assert (ctx.user_id, ctx.email, ctx.role) == (None, None, None)
