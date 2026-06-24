"""ATR・ボラティリティ計算"""

import pandas as pd


def calc_atr(df: pd.DataFrame, period: int = 14) -> float:
    high = df["high"]
    low = df["low"]
    close = df["close"]
    tr = pd.concat(
        [high - low, (high - close.shift()).abs(), (low - close.shift()).abs()],
        axis=1,
    ).max(axis=1)
    atr = tr.rolling(period).mean().iloc[-1]
    return float(atr) if pd.notna(atr) else 0.0


def calc_volatility_stats(df: pd.DataFrame, period: int = 14) -> dict:
    atr_val = calc_atr(df, period)
    close_val = float(df["close"].iloc[-1])
    daily_returns = df["close"].pct_change().dropna()
    return {
        "atr": round(atr_val, 4),
        "atr_percent": round(atr_val / close_val * 100, 3) if close_val else 0,
        "daily_volatility": round(float(daily_returns.std() * 100), 3) if len(daily_returns) else 0,
    }
