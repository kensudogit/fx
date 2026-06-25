"""高度リスク管理（ドローダウン・資金配分・損切り提案）"""

import pandas as pd

from src.analysis.position_sizing import calculate_position_size
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
