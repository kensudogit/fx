"""SaaS プラン定義 — src.auth.plans のテスト"""

import pytest

from src.auth.plans import (
    PLANS,
    PREMIUM_PATH_EXACT,
    PREMIUM_PATH_PREFIXES,
    daily_limit,
    list_plans_public,
    plan_features,
)

# 全プランが共通して持つべきフィーチャーキー
FEATURE_KEYS = {
    "technical", "fundamental", "analysis_basic", "analysis_intelligence",
    "ai", "ai_pro", "oanda_orders", "autotrade", "api_keys", "tradingview_webhook",
}


class TestPlanCatalog:
    """PLANS 定数の構造テスト"""

    def test_three_plans_are_defined(self):
        """free / pro / enterprise の 3 プランが定義されていること"""
        assert set(PLANS) == {"free", "pro", "enterprise"}

    @pytest.mark.parametrize("plan_id", ["free", "pro", "enterprise"])
    def test_plan_has_required_fields(self, plan_id):
        """各プランが名前・価格・上限・機能を持つこと"""
        plan = PLANS[plan_id]
        assert set(plan) == {"name", "price_monthly_usd", "daily_api_limit", "features"}

    @pytest.mark.parametrize("plan_id", ["free", "pro", "enterprise"])
    def test_all_plans_share_the_same_feature_keys(self, plan_id):
        """プラン間でフィーチャーキーが揃っていること（キーの取りこぼし防止）"""
        assert set(PLANS[plan_id]["features"]) == FEATURE_KEYS

    def test_price_increases_with_tier(self):
        """上位プランほど月額が高いこと"""
        prices = [PLANS[p]["price_monthly_usd"] for p in ("free", "pro", "enterprise")]
        assert prices == sorted(prices)
        assert prices[0] == 0

    def test_daily_limit_increases_with_tier(self):
        """上位プランほど 1 日の API 上限が大きいこと"""
        limits = [PLANS[p]["daily_api_limit"] for p in ("free", "pro", "enterprise")]
        assert limits == sorted(limits)

    def test_api_key_quota_increases_with_tier(self):
        """上位プランほど発行できる API キー本数が多いこと"""
        quotas = [PLANS[p]["features"]["api_keys"] for p in ("free", "pro", "enterprise")]
        assert quotas == sorted(quotas)

    def test_features_are_monotonic_across_tiers(self):
        """下位プランで有効な機能は上位プランでも必ず有効であること"""
        free = PLANS["free"]["features"]
        pro = PLANS["pro"]["features"]
        ent = PLANS["enterprise"]["features"]
        for key in FEATURE_KEYS:
            if isinstance(free[key], bool):
                assert not (free[key] and not pro[key]), f"{key} が pro で失われている"
                assert not (pro[key] and not ent[key]), f"{key} が enterprise で失われている"


class TestFreePlanRestrictions:
    """Free プランの制限が意図どおりであることのテスト"""

    def test_basic_analysis_is_available(self):
        """テクニカル・ファンダ・基本 AI は無料で使えること"""
        f = plan_features("free")
        assert f["technical"] is True
        assert f["fundamental"] is True
        assert f["ai"] is True

    def test_premium_features_are_blocked(self):
        """AI Pro・自動取引・OANDA 発注・統合分析は使えないこと"""
        f = plan_features("free")
        assert f["ai_pro"] is False
        assert f["autotrade"] is False
        assert f["oanda_orders"] is False
        assert f["analysis_intelligence"] is False

    def test_daily_limit_is_100(self):
        """1 日 100 回が上限であること"""
        assert daily_limit("free") == 100


class TestPlanLookup:
    """plan_features() / daily_limit() のフォールバック挙動テスト"""

    @pytest.mark.parametrize("plan_id,limit", [("free", 100), ("pro", 2000), ("enterprise", 50000)])
    def test_daily_limit_per_plan(self, plan_id, limit):
        """各プランの上限を返すこと"""
        assert daily_limit(plan_id) == limit

    @pytest.mark.parametrize("unknown", ["", "trial", "PRO", "gold", "  pro  "])
    def test_unknown_plan_falls_back_to_free(self, unknown):
        """未知のプラン名は安全側（free）へフォールバックすること"""
        assert daily_limit(unknown) == daily_limit("free")
        assert plan_features(unknown) == plan_features("free")

    def test_none_plan_falls_back_to_free(self):
        """None が渡されても例外にならず free 扱いになること"""
        assert daily_limit(None) == 100

    def test_lookup_is_case_sensitive(self):
        """プラン名は大文字小文字を区別すること（保存値の正規化漏れを検知できる）"""
        assert daily_limit("PRO") != daily_limit("pro")


class TestPremiumPaths:
    """有料機能のパス定義テスト"""

    def test_premium_prefixes_cover_paid_areas(self):
        """AI・Pro・統合分析・自動取引が制限対象であること"""
        assert "/api/ai/" in PREMIUM_PATH_PREFIXES
        assert "/api/pro/" in PREMIUM_PATH_PREFIXES
        assert "/api/analysis/intelligence/" in PREMIUM_PATH_PREFIXES
        assert "/api/autotrade/" in PREMIUM_PATH_PREFIXES

    def test_prefixes_end_with_slash(self):
        """前方一致で誤検知しないよう、各プレフィックスは / で終わること"""
        assert all(p.endswith("/") for p in PREMIUM_PATH_PREFIXES)

    def test_oanda_order_creation_is_restricted_by_method(self):
        """OANDA の発注は POST のみ制限対象であること（照会は対象外）"""
        assert ("POST", "/api/oanda/orders") in PREMIUM_PATH_EXACT
        assert ("GET", "/api/oanda/orders") not in PREMIUM_PATH_EXACT


class TestListPlansPublic:
    """list_plans_public() のテスト"""

    def test_returns_all_plans(self):
        """全プランを返すこと"""
        assert len(list_plans_public()) == len(PLANS)

    def test_each_entry_exposes_public_fields_only(self):
        """公開用フィールドのみを含むこと"""
        for entry in list_plans_public():
            assert set(entry) == {"id", "name", "price_monthly_usd", "daily_api_limit", "features"}

    def test_ids_match_plan_keys(self):
        """id が PLANS のキーと一致すること"""
        assert [e["id"] for e in list_plans_public()] == list(PLANS)

    def test_free_plan_is_listed_first(self):
        """無料プランが先頭に来ること（UI の並び順を固定する）"""
        assert list_plans_public()[0]["id"] == "free"
