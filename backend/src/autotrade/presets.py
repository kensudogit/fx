"""プリセット戦略（トライオートFX セレクト相当）"""

STRATEGY_PRESETS: dict[str, dict] = {
    "conservative": {
        "id": "conservative",
        "label": "安定型",
        "description": "低リスク・高信頼度。初心者向け。MTF一致とイベント回避を厳格化。",
        "style": "trend",
        "min_confidence": 75,
        "risk_percent": 0.5,
        "max_daily_trades": 2,
        "cooldown_minutes": 120,
        "require_mtf_alignment": True,
        "event_blackout_hours": 8,
        "sources": ["ai", "technical", "mtf"],
        "risk_reward": 2.0,
        "auto_exit_on_reverse": True,
        "min_units": 1000,
    },
    "balanced": {
        "id": "balanced",
        "label": "バランス型",
        "description": "AI + テクニカル + 統合分析の標準構成。中程度のリスク。",
        "style": "trend",
        "min_confidence": 65,
        "risk_percent": 1.0,
        "max_daily_trades": 3,
        "cooldown_minutes": 60,
        "require_mtf_alignment": True,
        "event_blackout_hours": 4,
        "sources": ["ai", "technical", "intelligence", "mtf"],
        "risk_reward": 2.0,
        "auto_exit_on_reverse": True,
        "min_units": 1000,
    },
    "aggressive": {
        "id": "aggressive",
        "label": "積極型",
        "description": "信頼度閾値を下げ取引頻度を上げる。上級者向け。",
        "style": "trend",
        "min_confidence": 55,
        "risk_percent": 1.5,
        "max_daily_trades": 5,
        "cooldown_minutes": 30,
        "require_mtf_alignment": False,
        "event_blackout_hours": 2,
        "sources": ["ai", "technical", "intelligence", "mtf", "tradingview"],
        "risk_reward": 1.5,
        "auto_exit_on_reverse": True,
        "min_units": 1000,
    },
    "range_repeat": {
        "id": "range_repeat",
        "label": "レンジリピート型",
        "description": "ボリンジャーバンド中心のレンジ売買。トライオートFX リピート系に近い構成。",
        "style": "range",
        "min_confidence": 50,
        "risk_percent": 0.8,
        "max_daily_trades": 6,
        "cooldown_minutes": 20,
        "require_mtf_alignment": False,
        "event_blackout_hours": 4,
        "sources": ["technical"],
        "risk_reward": 1.2,
        "auto_exit_on_reverse": False,
        "min_units": 1000,
    },
    "trend_follow": {
        "id": "trend_follow",
        "label": "トレンドフォロー型",
        "description": "MTF + ML トレンドに沿った順張り。テクニカルビルダー相当。",
        "style": "trend",
        "min_confidence": 60,
        "risk_percent": 1.0,
        "max_daily_trades": 4,
        "cooldown_minutes": 45,
        "require_mtf_alignment": True,
        "event_blackout_hours": 4,
        "sources": ["technical", "mtf", "ai"],
        "risk_reward": 2.5,
        "auto_exit_on_reverse": True,
        "min_units": 1000,
    },
}


def list_presets() -> list[dict]:
    return [
        {
            "id": p["id"],
            "label": p["label"],
            "description": p["description"],
            "style": p["style"],
            "min_confidence": p["min_confidence"],
            "risk_percent": p["risk_percent"],
            "risk_reward": p["risk_reward"],
        }
        for p in STRATEGY_PRESETS.values()
    ]


def apply_preset(preset_id: str, config: dict | None = None) -> dict:
    preset = STRATEGY_PRESETS.get(preset_id)
    if not preset:
        raise ValueError(f"Unknown preset: {preset_id}")
    base = {**(config or {})}
    for key, val in preset.items():
        if key not in ("id", "label", "description", "style"):
            base[key] = val
    base["strategy_preset"] = preset_id
    return base
