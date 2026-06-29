"""マルチタイムフレームトレンド分析"""

import pandas as pd

from src.analysis.signals import aggregate_bias, signals_from_row
from src.analysis.technical import compute_all_indicators
from src.config import settings
from src.data.market_data import get_ohlcv_data
from src.infra.analysis_cache import cache_get, cache_key, cache_put


def _trend_from_df(df: pd.DataFrame) -> dict:
    result = compute_all_indicators(df)
    latest = result.iloc[-1]
    close = float(latest["close"])
    sma20 = float(latest["sma_20"]) if pd.notna(latest["sma_20"]) else close
    sma50 = float(latest["sma_50"]) if pd.notna(latest["sma_50"]) else close

    if close > sma20 > sma50:
        trend = "bullish"
        label = "上昇"
    elif close < sma20 < sma50:
        trend = "bearish"
        label = "下降"
    elif close > sma50:
        trend = "bullish"
        label = "上昇寄り"
    elif close < sma50:
        trend = "bearish"
        label = "下降寄り"
    else:
        trend = "neutral"
        label = "中立"

    signals = signals_from_row(latest)
    return {
        "trend": trend,
        "label": label,
        "close": round(close, 4),
        "sma_20": round(sma20, 4),
        "sma_50": round(sma50, 4),
        "rsi": round(float(latest["rsi"]), 1) if pd.notna(latest["rsi"]) else None,
        "signal_bias": aggregate_bias(signals),
        "bars": len(result),
    }


def analyze_multi_timeframe(symbol: str) -> dict:
    key = cache_key("mtf", symbol)
    cached = cache_get(key)
    if cached is not None:
        return cached

    daily_df, daily_src = get_ohlcv_data(symbol, days=200, timeframe="1d")
    h4_df, h4_src = get_ohlcv_data(symbol, days=60, timeframe="4h")

    daily = _trend_from_df(daily_df)
    h4 = _trend_from_df(h4_df)

    alignment = "mixed"
    alignment_label = "ミックス"
    if daily["trend"] == h4["trend"] and daily["trend"] != "neutral":
        alignment = daily["trend"]
        alignment_label = "日足・4H 一致（" + daily["label"] + "）"
    elif daily["trend"] == "bullish" and h4["trend"] != "bearish":
        alignment = "bullish_bias"
        alignment_label = "日足上昇バイアス"
    elif daily["trend"] == "bearish" and h4["trend"] != "bullish":
        alignment = "bearish_bias"
        alignment_label = "日足下降バイアス"

    result = {
        "symbol": symbol.upper(),
        "alignment": alignment,
        "alignment_label": alignment_label,
        "timeframes": {
            "1d": {**daily, "timeframe": "1d", "source": daily_src},
            "4h": {**h4, "timeframe": "4h", "source": h4_src},
        },
    }
    cache_put(key, result, ttl_seconds=settings.mtf_cache_ttl_seconds)
    return result
