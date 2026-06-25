"""トレンド予測（機械学習 + テクニカルルール）"""

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import train_test_split

from src.analysis.multi_timeframe import analyze_multi_timeframe
from src.analysis.technical import compute_all_indicators
from src.data.market_data import get_ohlcv_data


def _rule_trend(latest: pd.Series) -> tuple[str, list[str]]:
    reasons: list[str] = []
    score = 0

    if pd.notna(latest.get("sma_20")) and pd.notna(latest.get("sma_50")):
        if latest["sma_20"] > latest["sma_50"]:
            score += 1
            reasons.append("SMA20 > SMA50（短期上昇トレンド）")
        elif latest["sma_20"] < latest["sma_50"]:
            score -= 1
            reasons.append("SMA20 < SMA50（短期下降トレンド）")

    if pd.notna(latest.get("close")) and pd.notna(latest.get("sma_20")):
        if latest["close"] > latest["sma_20"]:
            score += 1
            reasons.append("終値がSMA20上")
        else:
            score -= 1
            reasons.append("終値がSMA20下")

    rsi = latest.get("rsi")
    if pd.notna(rsi):
        if rsi > 55:
            score += 1
            reasons.append(f"RSI {rsi:.1f}（買い圧力）")
        elif rsi < 45:
            score -= 1
            reasons.append(f"RSI {rsi:.1f}（売り圧力）")

    if pd.notna(latest.get("macd")) and pd.notna(latest.get("macd_signal")):
        if latest["macd"] > latest["macd_signal"]:
            score += 1
            reasons.append("MACD > シグナル")
        else:
            score -= 1
            reasons.append("MACD < シグナル")

    if score >= 2:
        return "bullish", reasons
    if score <= -2:
        return "bearish", reasons
    return "neutral", reasons


def _build_trend_dataset(df: pd.DataFrame, horizon: int = 5, lookback: int = 5) -> tuple[np.ndarray, np.ndarray]:
    cols = ["sma_20", "sma_50", "rsi", "macd", "macd_signal", "stoch_k", "close"]
    available = [c for c in cols if c in df.columns]
    work = df[available].dropna().copy()
    if len(work) < lookback + horizon + 20:
        return np.array([]), np.array([])

    close = df.loc[work.index, "close"]
    X, y = [], []
    values = work.values
    for i in range(lookback, len(work) - horizon):
        future_ret = close.iloc[i + horizon] / close.iloc[i] - 1
        label = 1 if future_ret > 0.001 else (0 if future_ret < -0.001 else 2)
        X.append(values[i - lookback : i].flatten())
        y.append(label)

    return np.array(X), np.array(y)


def predict_trend(symbol: str, days: int = 200, horizon: int = 5) -> dict:
    df, source = get_ohlcv_data(symbol, days)
    result_df = compute_all_indicators(df)
    latest = result_df.iloc[-1]
    price = float(latest["close"])

    rule_trend, reasons = _rule_trend(latest)
    mtf = analyze_multi_timeframe(symbol)

    X, y = _build_trend_dataset(result_df, horizon=horizon)
    ml_result: dict = {"status": "insufficient_data"}

    if len(X) >= 40:
        X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, shuffle=False)
        model = RandomForestClassifier(n_estimators=80, random_state=42, n_jobs=-1)
        model.fit(X_train, y_train)
        acc = float(model.score(X_test, y_test))
        pred = int(model.predict(X[-1].reshape(1, -1))[0])
        proba = model.predict_proba(X[-1].reshape(1, -1))[0]
        trend_map = {1: "bullish", 0: "bearish", 2: "neutral"}
        ml_trend = trend_map.get(pred, "neutral")
        confidence = round(float(max(proba)) * 100, 1)
        ml_result = {
            "status": "success",
            "trend": ml_trend,
            "confidence": confidence,
            "horizon_days": horizon,
            "test_accuracy": round(acc * 100, 1),
            "model": "RandomForestClassifier",
        }
    else:
        ml_trend = rule_trend
        confidence = 50.0

    # ルール + ML + MTF を統合
    votes = [rule_trend, ml_result.get("trend", rule_trend), mtf.get("alignment", "neutral")]
    bull = votes.count("bullish")
    bear = votes.count("bearish")
    if bull > bear and bull >= 2:
        combined = "bullish"
        label = "上昇トレンド"
    elif bear > bull and bear >= 2:
        combined = "bearish"
        label = "下降トレンド"
    else:
        combined = "neutral"
        label = "レンジ / 方向感なし"

    return {
        "symbol": symbol.upper(),
        "source": source,
        "current_price": round(price, 4),
        "trend": combined,
        "trend_label": label,
        "confidence": ml_result.get("confidence", 50.0),
        "horizon_days": horizon,
        "rule_based": {"trend": rule_trend, "reasons": reasons},
        "ml": ml_result,
        "multi_timeframe": {
            "alignment": mtf.get("alignment"),
            "alignment_label": mtf.get("alignment_label"),
        },
    }
