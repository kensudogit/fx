"""高度リスク管理（ドローダウン・資金配分・損切り提案）"""

import pandas as pd

from src.analysis.market_deep import assess_event_risk, build_market_analysis
from src.analysis.multi_timeframe import analyze_multi_timeframe
from src.analysis.position_sizing import calculate_position_size, pip_size
from src.analysis.technical import compute_all_indicators
from src.analysis.volatility import calc_atr, calc_volatility_stats
from src.data.market_data import get_ohlcv_data
from src.data.sample_data import SYMBOL_BASE_PRICES


def _max_drawdown(close: pd.Series) -> dict:
    rolling_max = close.expanding().max()
    drawdown = (close - rolling_max) / rolling_max * 100
    mdd = float(drawdown.min())
    current_dd = float(drawdown.iloc[-1])
    return {
        "max_drawdown_pct": round(mdd, 2),
        "current_drawdown_pct": round(current_dd, 2),
        "peak_price": round(float(rolling_max.iloc[-1]), 4),
    }


def assess_advanced_risk(
    symbol: str,
    account_balance: float = 10000,
    risk_percent: float = 1.0,
    days: int = 200,
) -> dict:
    df, source = get_ohlcv_data(symbol, days)
    result_df = compute_all_indicators(df)
    close = result_df["close"]
    price = float(close.iloc[-1])
    atr = calc_atr(result_df)
    vol = calc_volatility_stats(result_df)
    dd = _max_drawdown(close)

    position = calculate_position_size(
        symbol, price, account_balance, risk_percent, atr=atr
    )

    stop_price = price - atr * 1.5 if symbol.endswith("JPY") else price - atr * 1.5
    if symbol.endswith("JPY"):
        stop_price = round(price - atr * 1.5, 3)
    else:
        stop_price = round(price - atr * 1.5, 5)
    tp_price = round(price + (price - stop_price) * 2, 5 if not symbol.endswith("JPY") else 3)

    # 複数通貨への資金配分（ボラ逆数ウェイト）
    allocations = []
    total_inv_vol = 0
    for sym in SYMBOL_BASE_PRICES:
        s_df, _ = get_ohlcv_data(sym, 60)
        s_vol = float(s_df["close"].pct_change().std() or 0.01)
        inv = 1 / max(s_vol, 0.0001)
        total_inv_vol += inv
        allocations.append({"symbol": sym, "inverse_vol": round(inv, 2)})

    for a in allocations:
        a["weight_pct"] = round(a["inverse_vol"] / total_inv_vol * 100, 1)
        a["allocated_usd"] = round(account_balance * a["weight_pct"] / 100, 2)

    daily_risk_budget = account_balance * risk_percent / 100
    max_concurrent_risk = account_balance * 0.05

    return {
        "symbol": symbol.upper(),
        "source": source,
        "account_balance": account_balance,
        "current_price": price,
        "volatility": vol,
        "drawdown": dd,
        "position_sizing": position,
        "stop_loss": {
            "price": stop_price,
            "pips": position["stop_pips"],
            "atr_multiple": 1.5,
            "max_loss_usd": position["max_loss_usd"],
        },
        "take_profit": {
            "price": tp_price,
            "pips": position["suggested_take_profit_pips"],
            "risk_reward": 2.0,
        },
        "capital_allocation": {
            "method": "inverse_volatility",
            "pairs": allocations,
        },
        "risk_budget": {
            "per_trade_usd": round(daily_risk_budget, 2),
            "max_concurrent_exposure_usd": round(max_concurrent_risk, 2),
            "max_open_positions_suggested": max(1, int(max_concurrent_risk / max(daily_risk_budget, 1))),
        },
        "recommendations": _risk_recommendations(dd, vol, risk_percent),
    }


def _risk_recommendations(dd: dict, vol: dict, risk_pct: float) -> list[str]:
    recs = []
    if dd["max_drawdown_pct"] < -10:
        recs.append(f"直近最大DD {dd['max_drawdown_pct']}% — ポジションサイズ縮小を検討")
    if vol["atr_percent"] > 1.5:
        recs.append("高ボラ環境 — ストップ幅をATR×2に拡大")
    if risk_pct > 2:
        recs.append("1トレードリスク2%超 — 1%以下への引き下げを推奨")
    if not recs:
        recs.append("現状のリスク水準は許容範囲 — ルール遵守を継続")
    return recs


def _historical_var(close: pd.Series, account_balance: float, confidence: float = 0.95) -> dict:
    returns = close.pct_change().dropna()
    if len(returns) < 20:
        return {
            "confidence": confidence,
            "daily_var_pct": 0.0,
            "daily_var_usd": 0.0,
            "observations": len(returns),
        }
    var_pct = float(returns.quantile(1 - confidence) * 100)
    var_usd = round(account_balance * abs(var_pct) / 100, 2)
    return {
        "confidence": confidence,
        "daily_var_pct": round(var_pct, 3),
        "daily_var_usd": var_usd,
        "observations": len(returns),
    }


def _scenario_analysis(symbol: str, price: float, atr: float) -> dict:
    sym = symbol.upper()
    decimals = 3 if sym.endswith("JPY") else 5
    bull = round(price + atr, decimals)
    base = round(price, decimals)
    bear = round(price - atr, decimals)
    pip = pip_size(sym)
    move_pips = round(atr / pip, 1) if pip else 0
    return {
        "horizon": "1日（ATRベース）",
        "bull": {"price": bull, "change_pips": move_pips, "label": "上振れシナリオ"},
        "base": {"price": base, "change_pips": 0, "label": "現状維持"},
        "bear": {"price": bear, "change_pips": -move_pips, "label": "下振れシナリオ"},
    }


def _stress_test(account_balance: float, risk_percent: float, consecutive_losses: int = 3) -> dict:
    per_trade = account_balance * risk_percent / 100
    total_loss = round(per_trade * consecutive_losses, 2)
    remaining = round(account_balance - total_loss, 2)
    remaining_pct = round(remaining / account_balance * 100, 1) if account_balance else 0
    return {
        "consecutive_losses": consecutive_losses,
        "loss_per_trade_usd": round(per_trade, 2),
        "total_loss_usd": total_loss,
        "remaining_balance_usd": remaining,
        "remaining_pct": remaining_pct,
        "interpretation": (
            f"{consecutive_losses}連敗で口座の{100 - remaining_pct:.1f}%を失う想定"
            if remaining_pct < 100
            else "ストレスシナリオなし"
        ),
    }


def _compute_risk_score(
    dd: dict,
    vol: dict,
    risk_pct: float,
    event_level: str,
    regime: str,
) -> dict:
    score = 100
    if dd["current_drawdown_pct"] < -5:
        score -= 15
    if dd["max_drawdown_pct"] < -15:
        score -= 20
    if vol["atr_percent"] > 2.0:
        score -= 20
    elif vol["atr_percent"] > 1.5:
        score -= 10
    if risk_pct > 2:
        score -= 25
    elif risk_pct > 1.5:
        score -= 10
    if event_level == "high":
        score -= 25
    elif event_level == "medium":
        score -= 10
    if regime == "volatile":
        score -= 15
    score = max(0, min(100, score))

    if score >= 75:
        level, label = "low", "リスク低 — 計画通りのエントリー可"
    elif score >= 50:
        level, label = "medium", "リスク中 — サイズ縮小・待機を検討"
    else:
        level, label = "high", "リスク高 — 新規エントリーは慎重に"
    return {"score": score, "level": level, "label": label}


def _build_checklist(
    mtf: dict,
    event_risk: dict,
    dd: dict,
    vol: dict,
    risk_pct: float,
    regime: str,
) -> list[dict]:
    items: list[dict] = []

    aligned = mtf.get("alignment") in ("bullish", "bearish", "bullish_bias", "bearish_bias")
    items.append({
        "item": "マルチTF整合",
        "status": "pass" if aligned else "warn",
        "detail": mtf.get("alignment_label", "—"),
    })

    ev = event_risk.get("level", "low")
    items.append({
        "item": "イベントリスク",
        "status": "fail" if ev == "high" else ("warn" if ev == "medium" else "pass"),
        "detail": event_risk.get("label", "—"),
    })

    items.append({
        "item": "ドローダウン",
        "status": "fail" if dd["current_drawdown_pct"] < -8 else ("warn" if dd["current_drawdown_pct"] < -4 else "pass"),
        "detail": f"現在DD {dd['current_drawdown_pct']}% / 最大 {dd['max_drawdown_pct']}%",
    })

    items.append({
        "item": "ボラティリティ",
        "status": "fail" if vol["atr_percent"] > 2 else ("warn" if vol["atr_percent"] > 1.5 else "pass"),
        "detail": f"ATR {vol['atr_percent']}%",
    })

    items.append({
        "item": "1トレードリスク",
        "status": "fail" if risk_pct > 2 else ("warn" if risk_pct > 1 else "pass"),
        "detail": f"{risk_pct}% / 推奨1%以下",
    })

    items.append({
        "item": "相場レジーム",
        "status": "warn" if regime == "volatile" else ("pass" if regime == "trending" else "warn"),
        "detail": {"trending": "トレンド相場", "ranging": "レンジ相場", "volatile": "高ボラ相場"}.get(regime, regime),
    })

    return items


def _trade_readiness(checklist: list[dict]) -> tuple[str, str]:
    statuses = [c["status"] for c in checklist]
    if "fail" in statuses:
        return "red", "エントリー非推奨 — リスク要因を解消してから"
    if statuses.count("warn") >= 2:
        return "yellow", "条件付き — サイズ半減または待機を推奨"
    if "warn" in statuses:
        return "yellow", "注意 — ルールを厳守して限定エントリー"
    return "green", "条件良好 — 事前定義ルールに従ってエントリー可"


def build_risk_report(
    symbol: str,
    account_balance: float = 10000,
    risk_percent: float = 1.0,
    days: int = 200,
) -> dict:
    base = assess_advanced_risk(symbol, account_balance, risk_percent, days)
    df, _ = get_ohlcv_data(symbol, days)
    result_df = compute_all_indicators(df)
    close = result_df["close"]
    price = float(close.iloc[-1])
    atr = calc_atr(result_df)

    market = build_market_analysis(symbol, days)
    mtf = analyze_multi_timeframe(symbol.upper())
    event_risk = assess_event_risk(48)
    regime = market["regime"]["regime"]

    var = _historical_var(close, account_balance)
    scenarios = _scenario_analysis(symbol, price, atr)
    stress = _stress_test(account_balance, risk_percent)
    risk_score = _compute_risk_score(
        base["drawdown"], base["volatility"], risk_percent, event_risk["level"], regime
    )
    checklist = _build_checklist(
        mtf, event_risk, base["drawdown"], base["volatility"], risk_percent, regime
    )
    readiness, readiness_label = _trade_readiness(checklist)

    recs = list(base["recommendations"])
    if event_risk["level"] == "high":
        recs.insert(0, "48時間以内に高影響イベント — ポジション保有・新規エントリーを控える")
    if regime == "volatile":
        recs.append("高ボラレジーム — 指値・ストップのスリッページを想定")
    if var["daily_var_usd"] > base["risk_budget"]["per_trade_usd"] * 2:
        recs.append(f"1日VaR ${var['daily_var_usd']} — 1トレードリスク上限を超えないよう注意")

    return {
        **base,
        "value_at_risk": var,
        "scenarios": scenarios,
        "stress_test": stress,
        "risk_score": risk_score,
        "event_risk": event_risk,
        "market_regime": market["regime"],
        "checklist": checklist,
        "trade_readiness": readiness,
        "trade_readiness_label": readiness_label,
        "recommendations": recs,
    }
