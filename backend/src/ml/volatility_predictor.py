"""ボラティリティ予測（ATR・履歴ボラ + ML）"""

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestRegressor
from sklearn.model_selection import train_test_split

from src.analysis.volatility import calc_atr, calc_volatility_stats
from src.analysis.technical import compute_all_indicators
from src.data.market_data import get_ohlcv_data


def _atr_series(df: pd.DataFrame, period: int = 14) -> pd.Series:
    high, low, close = df["high"], df["low"], df["close"]
    tr = pd.concat(
        [high - low, (high - close.shift()).abs(), (low - close.shift()).abs()],
        axis=1,
    ).max(axis=1)
    return tr.rolling(period).mean()


def _ewma_forecast(series: pd.Series, span: int = 10, steps: int = 5) -> float:
    if series.dropna().empty:
        return 0.0
    ewma = series.ewm(span=span).mean()
    last = float(ewma.dropna().iloc[-1])
    return last


def _vol_regime(atr_pct: float) -> tuple[str, str]:
    if atr_pct < 0.5:
        return "low", "低ボラ（レンジ相場想定）"
    if atr_pct < 1.2:
        return "medium", "中ボラ（通常）"
    return "high", "高ボラ（急変動注意）"


def predict_volatility(symbol: str, days: int = 200, forecast_days: int = 5) -> dict:
    df, source = get_ohlcv_data(symbol, days)
    result_df = compute_all_indicators(df)
    close = float(result_df["close"].iloc[-1])

    current = calc_volatility_stats(result_df)
    atr_s = _atr_series(result_df)
    daily_vol = result_df["close"].pct_change().rolling(20).std() * 100

    ewma_atr = _ewma_forecast(atr_s, span=10, steps=forecast_days)
    ewma_vol = _ewma_forecast(daily_vol, span=10, steps=forecast_days)

    # ML: 将来 ATR を回帰
    ml_forecast = None
    lookback = 5
    feat_df = pd.DataFrame({
        "atr": atr_s,
        "vol20": daily_vol,
        "rsi": result_df["rsi"],
        "range_pct": (result_df["high"] - result_df["low"]) / result_df["close"] * 100,
    }).dropna()

    if len(feat_df) >= lookback + forecast_days + 30:
        X, y = [], []
        vals = feat_df.values
        target = atr_s.loc[feat_df.index].shift(-forecast_days)
        for i in range(lookback, len(feat_df) - forecast_days):
            if pd.isna(target.iloc[i]):
                continue
            X.append(vals[i - lookback : i].flatten())
            y.append(float(target.iloc[i]))
        if len(X) >= 30:
            X_arr, y_arr = np.array(X), np.array(y)
            X_train, X_test, y_train, y_test = train_test_split(
                X_arr, y_arr, test_size=0.2, shuffle=False
            )
            model = RandomForestRegressor(n_estimators=60, random_state=42, n_jobs=-1)
            model.fit(X_train, y_train)
            ml_forecast = float(model.predict(X_arr[-1].reshape(1, -1))[0])
            test_r2 = float(model.score(X_test, y_test))

    predicted_atr = ml_forecast if ml_forecast else ewma_atr
    predicted_atr_pct = predicted_atr / close * 100 if close else 0
    regime, regime_label = _vol_regime(predicted_atr_pct)

    # トレンド: 直近20日 vs 予測
    recent_atr_pct = current["atr_percent"]
    vol_change = round((predicted_atr_pct - recent_atr_pct) / max(recent_atr_pct, 0.01) * 100, 1)
    if vol_change > 10:
        vol_trend = "expanding"
        vol_trend_label = "ボラ拡大見込み"
    elif vol_change < -10:
        vol_trend = "contracting"
        vol_trend_label = "ボラ収縮見込み"
    else:
        vol_trend = "stable"
        vol_trend_label = "ボラ横ばい見込み"

    return {
        "symbol": symbol.upper(),
        "source": source,
        "current_price": round(close, 4),
        "forecast_days": forecast_days,
        "current": current,
        "forecast": {
            "atr": round(predicted_atr, 4),
            "atr_percent": round(predicted_atr_pct, 3),
            "daily_volatility_pct": round(float(ewma_vol), 3),
            "regime": regime,
            "regime_label": regime_label,
            "vol_trend": vol_trend,
            "vol_trend_label": vol_trend_label,
            "change_vs_current_pct": vol_change,
        },
        "ml": {
            "status": "success" if ml_forecast else "ewma_fallback",
            "model": "RandomForestRegressor" if ml_forecast else "EWMA",
            "predicted_atr": round(predicted_atr, 4),
        },
        "interpretation": (
            f"今後{forecast_days}日のATR予測: {predicted_atr:.4f} "
            f"({predicted_atr_pct:.2f}%) — {regime_label}、{vol_trend_label}"
        ),
    }
