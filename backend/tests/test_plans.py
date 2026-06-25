"""SaaS プラン定義のテスト"""

from src.auth.plans import PLANS, daily_limit, plan_features


def test_free_plan_limits_autotrade():
    features = plan_features("free")
    assert features["autotrade"] is False
    assert features["ai_pro"] is False
    assert features["ai"] is True
    assert daily_limit("free") == 100


def test_pro_plan_includes_autotrade():
    features = plan_features("pro")
    assert features["autotrade"] is True
    assert features["ai_pro"] is True
    assert features["oanda_orders"] is True
    assert daily_limit("pro") == 2000


def test_unknown_plan_falls_back_to_free():
    assert daily_limit("unknown") == 100
    assert plan_features("unknown") == PLANS["free"]["features"]
