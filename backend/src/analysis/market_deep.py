"""相場深度分析（レジーム・水準・相関・モメンタム）"""

from datetime import datetime, timezone

import pandas as pd

from src.analysis.multi_timeframe import analyze_multi_timeframe
from src.analysis.fundamental import get_event_alerts
from src.analysis.technical import compute_all_indicators
from src.analysis.volatility import calc_atr
from src.data.market_data import get_ohlcv_data
from src.data.sample_data import SYMBOL_BASE_PRICES


def _atr_series(df: pd.DataFrame, period: int = 14) -> pd.Series:
    high = df["high"]
    low = df["low"]
    close = df["close"]
    tr = pd.concat(
        [high - low, (high - close.shift()).abs(), (low - close.shift()).abs()],
        axis=1,
    ).max(axis=1)
    return tr.rolling(period).mean()


def classify_market_regime(result_df: pd.DataFrame) -> dict:
    close = result_df["close"]
    price = float(close.iloc[-1])
    sma20 = float(result_df["sma_20"].iloc[-1]) if pd.notna(result_df["sma_20"].iloc[-1]) else price
    sma50 = float(result_df["sma_50"].iloc[-1]) if pd.notna(result_df["sma_50"].iloc[-1]) else price

    atr_now = calc_atr(result_df)
    atr_hist = _atr_series(result_df).dropna()
    atr_pctile = 50.0
    if len(atr_hist) >= 10:
        atr_pctile = float((atr_hist <= atr_now).sum() / len(atr_hist) * 100)

    bb_upper = float(result_df["bb_upper"].iloc[-1]) if pd.notna(result_df["bb_upper"].iloc[-1]) else price
    bb_lower = float(result_df["bb_lower"].iloc[-1]) if pd.notna(result_df["bb_lower"].iloc[-1]) else price
    bb_width_pct = (bb_upper - bb_lower) / price * 100 if price else 0

    ma_spread_pct = abs(sma20 - sma50) / price * 100 if price else 0
    slope_20 = float((close.iloc[-1] - close.iloc[-21]) / close.iloc[-21] * 100) if len(close) > 21 else 0

    aligned = (price > sma20 > sma50) or (price < sma20 < sma50)

    if atr_pctile >= 75 or bb_width_pct > 2.5:
        regime = "volatile"
        label = "高ボラ（不安定）"
        strength = min(100, int(atr_pctile))
    elif ma_spread_pct >= 0.25 and aligned and abs(slope_20) >= 0.5:
        regime = "trending"
        label = "トレンド相場"
        strength = min(100, int(ma_spread_pct * 80 + abs(slope_20) * 10))
    else:
        regime = "ranging"
        label = "レンジ相場"
        strength = max(0, 100 - int(ma_spread_pct * 100))

    trend_bias = "neutral"
    trend_label = "方向感なし"
    if price > sma20 > sma50:
        trend_bias, trend_label = "bullish", "上昇トレンド"
    elif price < sma20 < sma50:
        trend_bias, trend_label = "bearish", "下降トレンド"
    elif price > sma50:
        trend_bias, trend_label = "bullish", "上昇寄り"
    elif price < sma50:
        trend_bias, trend_label = "bearish", "下降寄り"

    return {
        "regime": regime,
        "label": label,
        "strength": strength,
        "trend_bias": trend_bias,
        "trend_label": trend_label,
        "atr_percentile": round(atr_pctile, 1),
        "bb_width_pct": round(bb_width_pct, 3),
        "ma_spread_pct": round(ma_spread_pct, 3),
        "slope_20d_pct": round(slope_20, 2),
    }


def find_key_levels(result_df: pd.DataFrame, symbol: str, lookback: int = 60, window: int = 5) -> dict:
    df = result_df.tail(lookback)
    highs = df["high"].values
    lows = df["low"].values
    price = float(df["close"].iloc[-1])

    resistances: list[float] = []
    supports: list[float] = []

    for i in range(window, len(df) - window):
        h = highs[i]
        l = lows[i]
        if h == max(highs[i - window : i + window + 1]):
            resistances.append(float(h))
        if l == min(lows[i - window : i + window + 1]):
            supports.append(float(l))

    def _cluster(levels: list[float], tol_pct: float = 0.15) -> list[float]:
        if not levels:
            return []
        levels = sorted(levels, reverse=True)
        clusters: list[list[float]] = [[levels[0]]]
        for lv in levels[1:]:
            ref = clusters[-1][0]
            if ref and abs(lv - ref) / ref * 100 <= tol_pct:
                clusters[-1].append(lv)
            else:
                clusters.append([lv])
        return [round(sum(c) / len(c), 4) for c in clusters]

    resistances = _cluster(resistances)[:4]
    supports = _cluster(supports)[:4]
    supports.sort()

    nearest_support = max([s for s in supports if s <= price], default=None)
    nearest_resistance = min([r for r in resistances if r >= price], default=None)

    return {
        "current_price": round(price, 4),
        "supports": supports,
        "resistances": resistances,
        "nearest_support": nearest_support,
        "nearest_resistance": nearest_resistance,
        "distance_to_support_pips": _price_distance_pips(price, nearest_support, symbol),
        "distance_to_resistance_pips": _price_distance_pips(price, nearest_resistance, symbol),
    }


def _price_distance_pips(
    from_price: float | None, to_price: float | None, symbol: str
) -> float | None:
    if from_price is None or to_price is None:
        return None
    from src.analysis.position_sizing import pip_size

    pip = pip_size(symbol)
    return round(abs(to_price - from_price) / pip, 1) if pip else None


def compute_momentum(result_df: pd.DataFrame) -> dict:
    close = result_df["close"]
    price = float(close.iloc[-1])
    rsi_val = float(result_df["rsi"].iloc[-1]) if pd.notna(result_df["rsi"].iloc[-1]) else 50.0
    macd_hist = (
        float(result_df["macd_histogram"].iloc[-1])
        if pd.notna(result_df["macd_histogram"].iloc[-1])
        else 0.0
    )
    roc_5 = float((close.iloc[-1] - close.iloc[-6]) / close.iloc[-6] * 100) if len(close) > 6 else 0.0
    roc_20 = float((close.iloc[-1] - close.iloc[-21]) / close.iloc[-21] * 100) if len(close) > 21 else 0.0

    score = 0
    if rsi_val > 60:
        score += 25
    elif rsi_val < 40:
        score -= 25
    if macd_hist > 0:
        score += 20
    elif macd_hist < 0:
        score -= 20
    score += max(-30, min(30, roc_5 * 5))
    score += max(-25, min(25, roc_20 * 2))
    score = max(-100, min(100, score))

    if score > 30:
        bias, label = "bullish", "強い上昇モメンタム"
    elif score < -30:
        bias, label = "bearish", "強い下降モメンタム"
    elif score > 10:
        bias, label = "bullish", "上昇モメンタム"
    elif score < -10:
        bias, label = "bearish", "下降モメンタム"
    else:
        bias, label = "neutral", "中立"

    return {
        "score": score,
        "bias": bias,
        "label": label,
        "rsi": round(rsi_val, 1),
        "macd_histogram": round(macd_hist, 6),
        "roc_5d_pct": round(roc_5, 2),
        "roc_20d_pct": round(roc_20, 2),
    }


def calc_pair_correlation(days: int = 60) -> dict:
    returns: dict[str, pd.Series] = {}
    for sym in SYMBOL_BASE_PRICES:
        df, _ = get_ohlcv_data(sym, days)
        returns[sym] = df["close"].pct_change().dropna()

    aligned = pd.DataFrame(returns).dropna()
    if aligned.empty or len(aligned) < 10:
        pairs = list(SYMBOL_BASE_PRICES.keys())
        matrix = {a: {b: 1.0 if a == b else 0.0 for b in pairs} for a in pairs}
        return {"pairs": pairs, "matrix": matrix, "days": days, "observations": 0}

    corr = aligned.corr()
    pairs = list(corr.columns)
    matrix = {
        a: {b: round(float(corr.loc[a, b]), 3) for b in pairs}
        for a in pairs
    }
    return {"pairs": pairs, "matrix": matrix, "days": days, "observations": len(aligned)}


def fx_session_context() -> dict:
    hour_utc = datetime.now(timezone.utc).hour
    if 0 <= hour_utc < 7:
        return {"session": "asia", "label": "アジア時間帯", "note": "レンジ形成・クロス円の動きに注意"}
    if 7 <= hour_utc < 13:
        return {"session": "london", "label": "ロンドン時間帯", "note": "トレンド発生・EUR/GBP絡みのボラ拡大"}
    if 13 <= hour_utc < 21:
        return {"session": "overlap", "label": "ロンドン×NY重複", "note": "最も流動性が高く方向性が出やすい"}
    return {"session": "new_york", "label": "NY時間帯", "note": "米指標前後で急変動に注意"}


def assess_event_risk(within_hours: int = 48) -> dict:
    alerts = get_event_alerts(within_hours)
    if len(alerts) >= 2:
        level, label = "high", "高 — 複数の高影響イベントが近接"
    elif len(alerts) == 1:
        level, label = "medium", "中 — 高影響イベントが48時間以内"
    else:
        level, label = "low", "低 — 直近48時間に高影響イベントなし"
    return {"level": level, "label": label, "within_hours": within_hours, "alerts": alerts}


def build_market_analysis(symbol: str, days: int = 200) -> dict:
    df, source = get_ohlcv_data(symbol, days)
    result_df = compute_all_indicators(df)
    sym = symbol.upper()

    return {
        "symbol": sym,
        "source": source,
        "days": days,
        "regime": classify_market_regime(result_df),
        "key_levels": find_key_levels(result_df, sym),
        "momentum": compute_momentum(result_df),
        "multi_timeframe": analyze_multi_timeframe(sym),
        "correlation": calc_pair_correlation(min(days, 90)),
        "session": fx_session_context(),
        "event_risk": assess_event_risk(48),
    }
