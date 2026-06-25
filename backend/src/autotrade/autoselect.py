"""オートセレクト — 3 問アンケートで最適プリセットを提案（トライオートFX 相当）"""

from src.autotrade.presets import STRATEGY_PRESETS, apply_preset
from src.data.sample_data import SYMBOL_BASE_PRICES

CAPITAL_MAP = {
    "small": 5000,
    "medium": 20000,
    "large": 100000,
}

HORIZON_MAP = {
    "short": {"cooldown_minutes": 30, "max_daily_trades": 4, "scheduler_interval_minutes": 10},
    "medium": {"cooldown_minutes": 60, "max_daily_trades": 3, "scheduler_interval_minutes": 15},
    "long": {"cooldown_minutes": 120, "max_daily_trades": 2, "scheduler_interval_minutes": 30},
}

RISK_PRESET = {
    "low": "conservative",
    "medium": "balanced",
    "high": "aggressive",
}

STYLE_PRESET = {
    "range": "range_repeat",
    "trend": "trend_follow",
    "auto": None,
}


def autoselect(
    capital: str = "medium",
    horizon: str = "medium",
    risk_appetite: str = "medium",
    style: str = "auto",
    preferred_symbols: list[str] | None = None,
) -> dict:
    """
    運用金額・運用期間・リスク許容度の 3 軸 (+ 任意スタイル) から設定を生成。
    """
    capital = capital if capital in CAPITAL_MAP else "medium"
    horizon = horizon if horizon in HORIZON_MAP else "medium"
    risk_appetite = risk_appetite if risk_appetite in RISK_PRESET else "medium"
    style = style if style in STYLE_PRESET else "auto"

    if style != "auto" and STYLE_PRESET[style]:
        preset_id = STYLE_PRESET[style]
    else:
        preset_id = RISK_PRESET[risk_appetite]

    config = apply_preset(preset_id)
    config["account_balance"] = CAPITAL_MAP[capital]
    config.update(HORIZON_MAP[horizon])

    symbols = preferred_symbols or ["USDJPY"]
    config["symbols"] = [s.upper() for s in symbols if s.upper() in SYMBOL_BASE_PRICES][:3]
    if not config["symbols"]:
        config["symbols"] = ["USDJPY"]

    preset = STRATEGY_PRESETS[preset_id]
    return {
        "recommended_preset": preset_id,
        "preset_label": preset["label"],
        "config": config,
        "rationale": _rationale(capital, horizon, risk_appetite, style, preset_id),
        "questions_answered": {
            "capital": capital,
            "horizon": horizon,
            "risk_appetite": risk_appetite,
            "style": style,
        },
    }


def _rationale(capital, horizon, risk, style, preset_id) -> str:
    cap_ja = {"small": "小額", "medium": "中程度", "large": "大額"}.get(capital, capital)
    hor_ja = {"short": "短期", "medium": "中期", "long": "長期"}.get(horizon, horizon)
    risk_ja = {"low": "低リスク", "medium": "標準", "high": "高リスク"}.get(risk, risk)
    preset = STRATEGY_PRESETS[preset_id]
    return (
        f"運用資金「{cap_ja}」· 期間「{hor_ja}」· リスク「{risk_ja}」に基づき、"
        f"「{preset['label']}」({preset['description'][:40]}…) を推奨します。"
    )
