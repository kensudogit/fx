"""SaaS プラン定義"""

PLANS = {
    "free": {
        "name": "Free",
        "price_monthly_usd": 0,
        "daily_api_limit": 100,
        "features": {
            "technical": True,
            "fundamental": True,
            "analysis_basic": True,
            "analysis_intelligence": False,
            "ai": True,
            "ai_pro": False,
            "oanda_orders": False,
            "autotrade": False,
            "api_keys": 1,
            "tradingview_webhook": True,
        },
    },
    "pro": {
        "name": "Pro",
        "price_monthly_usd": 49,
        "daily_api_limit": 2000,
        "features": {
            "technical": True,
            "fundamental": True,
            "analysis_basic": True,
            "analysis_intelligence": True,
            "ai": True,
            "ai_pro": True,
            "oanda_orders": True,
            "autotrade": True,
            "api_keys": 5,
            "tradingview_webhook": True,
        },
    },
    "enterprise": {
        "name": "Enterprise",
        "price_monthly_usd": 199,
        "daily_api_limit": 50000,
        "features": {
            "technical": True,
            "fundamental": True,
            "analysis_basic": True,
            "analysis_intelligence": True,
            "ai": True,
            "ai_pro": True,
            "oanda_orders": True,
            "autotrade": True,
            "api_keys": 50,
            "tradingview_webhook": True,
        },
    },
}

PREMIUM_PATH_PREFIXES = (
    "/api/ai/",
    "/api/pro/",
    "/api/analysis/intelligence/",
    "/api/autotrade/",
)

PREMIUM_PATH_EXACT = {
    ("POST", "/api/oanda/orders"),
}


def plan_features(plan: str) -> dict:
    return PLANS.get(plan, PLANS["free"])["features"]


def daily_limit(plan: str) -> int:
    return PLANS.get(plan, PLANS["free"])["daily_api_limit"]


def list_plans_public() -> list[dict]:
    return [
        {
            "id": pid,
            "name": p["name"],
            "price_monthly_usd": p["price_monthly_usd"],
            "daily_api_limit": p["daily_api_limit"],
            "features": p["features"],
        }
        for pid, p in PLANS.items()
    ]
