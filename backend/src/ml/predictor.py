"""機械学習モジュール - 価格予測・特徴量エンジニアリング"""

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestRegressor
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import StandardScaler

from src.analysis.market_context import MarketContext
from src.infra.analysis_cache import cache_get, cache_key, cache_put


def prepare_features(df: pd.DataFrame, lookback: int = 5) -> tuple[np.ndarray, np.ndarray]:
    """テクニカル指標を特徴量として準備"""
    feature_cols = [
        "sma_20", "sma_50", "rsi", "macd", "macd_signal",
        "stoch_k", "stoch_d", "bb_upper", "bb_lower",
    ]
    available = [c for c in feature_cols if c in df.columns]
    if not available:
        return np.array([]), np.array([])

    features_df = df[available].dropna()
    if len(features_df) < lookback + 10:
        return np.array([]), np.array([])

    X, y = [], []
    values = features_df.values
    close_values = df.loc[features_df.index, "close"].values

    for i in range(lookback, len(values)):
        X.append(values[i - lookback : i].flatten())
        y.append(close_values[i])

    return np.array(X), np.array(y)


def train_price_predictor(df: pd.DataFrame) -> dict:
    """RandomForest による価格予測モデルを学習"""
    X, y = prepare_features(df)
    if len(X) < 20:
        return {"status": "insufficient_data", "message": "データが不足しています"}

    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, shuffle=False
    )

    scaler = StandardScaler()
    X_train_scaled = scaler.fit_transform(X_train)
    X_test_scaled = scaler.transform(X_test)

    model = RandomForestRegressor(n_estimators=100, random_state=42, n_jobs=-1)
    model.fit(X_train_scaled, y_train)

    train_score = model.score(X_train_scaled, y_train)
    test_score = model.score(X_test_scaled, y_test)

    last_features = X[-1].reshape(1, -1)
    prediction = float(model.predict(scaler.transform(last_features))[0])

    return {
        "status": "success",
        "prediction": round(prediction, 4),
        "current_price": round(float(df["close"].iloc[-1]), 4),
        "train_r2": round(train_score, 4),
        "test_r2": round(test_score, 4),
        "model": "RandomForestRegressor",
    }


def predict_price(symbol: str, days: int = 200) -> dict:
    """価格予測（キャッシュ付き）"""
    key = cache_key("ml:price", symbol, days=days)
    cached = cache_get(key)
    if cached is not None:
        return cached

    ctx = MarketContext.load(symbol, days)
    prediction = train_price_predictor(ctx.result_df)
    result = {"symbol": symbol.upper(), "source": ctx.source, **prediction}
    cache_put(key, result)
    return result
