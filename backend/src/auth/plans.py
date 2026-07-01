"""
SaaS プラン定義モジュール。

このシステムは 3 段階のサブスクリプションプランを提供する:
  - Free  : 無料プラン（基本機能のみ、100 回/日）
  - Pro   : 有料プラン（$49/月、AI 分析・自動取引含む、2,000 回/日）
  - Enterprise: 大口向け（$199/月、全機能・50,000 回/日）

各プランはフィーチャーフラグ（機能の有効/無効）と利用上限で構成される。
ミドルウェアはこのモジュールの定数・関数を参照してアクセス制御を行う。
"""

# ─── プラン定義辞書 ──────────────────────────────────────────────────────
# キー: プランID（"free" / "pro" / "enterprise"）
# 値:   プラン名・月額料金（USD）・1日の API 上限・フィーチャーフラグ辞書
PLANS = {
    "free": {
        "name": "Free",
        "price_monthly_usd": 0,          # 月額料金（USD）: 無料
        "daily_api_limit": 100,          # 1日の API 呼び出し上限: 100 回
        "features": {
            "technical": True,            # テクニカル分析（移動平均・RSI 等）: 利用可
            "fundamental": True,          # ファンダメンタル分析（経済指標等）: 利用可
            "analysis_basic": True,       # 基本分析機能: 利用可
            "analysis_intelligence": False,  # 統合インテリジェンス分析: 利用不可（Pro 以上）
            "ai": True,                   # AI 分析（基本）: 利用可
            "ai_pro": False,              # AI Pro 機能（高度なプロンプト）: 利用不可（Pro 以上）
            "oanda_orders": False,        # OANDA 注文発注: 利用不可（Pro 以上）
            "autotrade": False,           # 自動取引機能: 利用不可（Pro 以上）
            "api_keys": 1,                # 発行可能な API キーの最大数: 1 本
            "tradingview_webhook": True,  # TradingView Webhook 受信: 利用可
        },
    },
    "pro": {
        "name": "Pro",
        "price_monthly_usd": 49,         # 月額料金（USD）: $49
        "daily_api_limit": 2000,         # 1日の API 呼び出し上限: 2,000 回
        "features": {
            "technical": True,
            "fundamental": True,
            "analysis_basic": True,
            "analysis_intelligence": True,   # 統合インテリジェンス分析: 利用可
            "ai": True,
            "ai_pro": True,                  # AI Pro 機能: 利用可
            "oanda_orders": True,            # OANDA 注文発注: 利用可
            "autotrade": True,               # 自動取引機能: 利用可
            "api_keys": 5,                   # 発行可能な API キーの最大数: 5 本
            "tradingview_webhook": True,
        },
    },
    "enterprise": {
        "name": "Enterprise",
        "price_monthly_usd": 199,        # 月額料金（USD）: $199
        "daily_api_limit": 50000,        # 1日の API 呼び出し上限: 50,000 回
        "features": {
            "technical": True,
            "fundamental": True,
            "analysis_basic": True,
            "analysis_intelligence": True,
            "ai": True,
            "ai_pro": True,
            "oanda_orders": True,
            "autotrade": True,
            "api_keys": 50,              # 発行可能な API キーの最大数: 50 本（大規模チーム向け）
            "tradingview_webhook": True,
        },
    },
}

# プレミアム（有料プラン限定）API パスのプレフィックスリスト。
# このプレフィックスで始まるパスは、ミドルウェアがフィーチャーゲートを適用する。
PREMIUM_PATH_PREFIXES = (
    "/api/ai/",                        # AI 分析エンドポイント全般
    "/api/pro/",                       # AI Pro 機能エンドポイント
    "/api/analysis/intelligence/",     # 統合インテリジェンス分析エンドポイント
    "/api/autotrade/",                 # 自動取引エンドポイント
)

# メソッドとパスの完全一致でプレミアム判定するエンドポイントのセット。
# タプル (HTTP メソッド, パス) の形式で管理する。
PREMIUM_PATH_EXACT = {
    ("POST", "/api/oanda/orders"),    # OANDA 注文作成（POST のみ制限、照会 GET は別途管理）
}


def plan_features(plan: str) -> dict:
    """
    指定プランのフィーチャーフラグ辞書を返す。

    不明なプラン名が渡された場合は、最も制限の多い "free" プランの
    フィーチャーをフォールバックとして返す（安全側に倒す設計）。

    Args:
        plan: プラン識別子（"free" / "pro" / "enterprise"）。

    Returns:
        dict: フィーチャーフラグ辞書。各キーが機能名、値が bool または int。
              例: {"ai": True, "api_keys": 5, ...}
    """
    # 未知のプラン名は "free" にフォールバック（不正なプランで機能解放を防ぐ）
    return PLANS.get(plan, PLANS["free"])["features"]


def daily_limit(plan: str) -> int:
    """
    指定プランの 1 日あたり API 呼び出し上限数を返す。

    不明なプラン名が渡された場合は "free" の上限（100 回）を返す。

    Args:
        plan: プラン識別子（"free" / "pro" / "enterprise"）。

    Returns:
        int: 1 日の API 呼び出し上限回数。
             free=100, pro=2000, enterprise=50000。
    """
    # 未知のプラン名は "free" にフォールバック（最小上限で安全側）
    return PLANS.get(plan, PLANS["free"])["daily_api_limit"]


def list_plans_public() -> list[dict]:
    """
    公開用のプラン一覧を返す。

    フロントエンドのプラン選択 UI や /api/billing/plans エンドポイントで使用する。
    内部管理用フィールドは含めず、ユーザーに見せる情報だけを返す。

    Returns:
        list[dict]: 各プランの公開情報リスト。
                    フィールド: id, name, price_monthly_usd, daily_api_limit, features。
    """
    return [
        {
            "id": pid,                                    # プラン識別子（"free" 等）
            "name": p["name"],                            # 表示名（"Free" 等）
            "price_monthly_usd": p["price_monthly_usd"],  # 月額料金（USD）
            "daily_api_limit": p["daily_api_limit"],      # 1日の API 上限
            "features": p["features"],                    # フィーチャーフラグ辞書
        }
        for pid, p in PLANS.items()
    ]
