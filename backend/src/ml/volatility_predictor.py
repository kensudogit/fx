"""
ボラティリティ予測モジュール（ATR・履歴ボラ + ML）

FX 相場の今後 forecast_days 日のボラティリティを予測するモジュール。
ATR（Average True Range）を主要指標として、ML と EWMA（指数加重移動平均）を
組み合わせて予測する。

予測指標:
    - ATR（予測値）: forecast_days 日後の平均真の値幅
    - ATR%: ATR を現在価格で割った比率（価格水準に依存しない相対指標）
    - 日次ボラティリティ%: 終値リターンの標準偏差

ボラティリティレジーム分類:
    - low（低ボラ）: ATR% < 0.5% → レンジ相場想定
    - medium（中ボラ）: 0.5% ≤ ATR% < 1.2% → 通常相場
    - high（高ボラ）: ATR% ≥ 1.2% → 急変動・イベント相場

ML モデル:
    - RandomForestRegressor で future ATR を回帰予測
    - 特徴量: ATR, 20日ボラ, RSI, 高低幅%（直近 lookback ステップ）
    - データ不足時は EWMA フォールバック

キャッシュ:
    analysis_cache でキャッシュ（result_df が外部から渡された場合は無効）
"""

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestRegressor
from sklearn.model_selection import train_test_split

from src.analysis.volatility import calc_atr, calc_volatility_stats
from src.analysis.technical import compute_all_indicators
from src.data.market_data import get_ohlcv_data
from src.infra.analysis_cache import cache_get, cache_key, cache_put
from src.ml.model_store import load_or_train, model_file


def _atr_series(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """データフレームから ATR（平均真の値幅）の時系列を計算する。

    True Range（TR）は以下の3値の最大値として定義される:
        - 高値 - 安値（当日の値幅）
        - |高値 - 前日終値|（ギャップアップ時の値幅）
        - |安値 - 前日終値|（ギャップダウン時の値幅）

    ATR = TR の period 期間単純移動平均

    Args:
        df: OHLCV データを含む DataFrame（high, low, close カラムが必要）
        period: ATR の計算期間（デフォルト: 14日）

    Returns:
        ATR の時系列（pd.Series）
    """
    high, low, close = df["high"], df["low"], df["close"]
    # 3つの True Range 成分を計算して列方向で結合
    tr = pd.concat(
        [high - low, (high - close.shift()).abs(), (low - close.shift()).abs()],
        axis=1,
    ).max(axis=1)  # 各行の最大値が True Range
    return tr.rolling(period).mean()


def _ewma_forecast(series: pd.Series, span: int = 10, steps: int = 5) -> float:
    """EWMA（指数加重移動平均）で将来値を予測する。

    ML モデルが使えない場合（データ不足等）のフォールバックとして使用。
    EWMA の最終値を予測値として返す（定数予測）。

    Args:
        series: 予測する時系列データ（例: ATR の時系列）
        span: EWMA のスパン（大きいほど過去データの影響が大きい）
        steps: 予測ステップ数（現在は使用せず、将来の拡張用）

    Returns:
        EWMA の最新値（float）。データが空の場合は 0.0 を返す。
    """
    if series.dropna().empty:
        return 0.0
    ewma = series.ewm(span=span).mean()
    # 最後の有効な値を将来の予測値として返す
    last = float(ewma.dropna().iloc[-1])
    return last


def _vol_regime(atr_pct: float) -> tuple[str, str]:
    """ATR% からボラティリティレジームを判定する。

    ボラティリティの水準に応じて取引戦略を変えるために使用:
        - 低ボラ時: レンジ売買・小ロット
        - 高ボラ時: SL 幅を広げる・ポジションサイズを縮小

    Args:
        atr_pct: ATR を現在価格で割った比率（%）

    Returns:
        タプル（レジームコード, 日本語ラベル）:
            - ("low", "低ボラ（レンジ相場想定）")
            - ("medium", "中ボラ（通常）")
            - ("high", "高ボラ（急変動注意）")
    """
    if atr_pct < 0.5:
        return "low", "低ボラ（レンジ相場想定）"
    if atr_pct < 1.2:
        return "medium", "中ボラ（通常）"
    return "high", "高ボラ（急変動注意）"


def predict_volatility(
    symbol: str,
    days: int = 200,
    forecast_days: int = 5,
    *,
    result_df: pd.DataFrame | None = None,
    source: str | None = None,
) -> dict:
    """ボラティリティを ML + EWMA で予測する。

    予測フロー:
        1. ATR と 20 日ボラの時系列を計算
        2. EWMA でベースライン予測を算出
        3. データが十分な場合は ML（RandomForestRegressor）で future ATR を予測
        4. ML 予測が成功した場合は EWMA に優先して使用
        5. 予測 ATR% からボラレジームとトレンドを判定

    ML 特徴量:
        - atr: ATR 時系列（14期間）
        - vol20: 20日ボラ（終値リターンの標準偏差 × 100）
        - rsi: RSI（市場の過熱・冷却状態）
        - range_pct: 高安値幅 / 終値 × 100（当日のボラの直接指標）

    Args:
        symbol: 通貨ペアコード（例: "USDJPY"）
        days: データ取得期間（日数）
        forecast_days: 予測する日数（例: 5 = 5日後の ATR を予測）
        result_df: テクニカル指標付き DataFrame（None の場合は内部で取得）
        source: データソース名（result_df を外部から渡す場合に使用）

    Returns:
        ボラティリティ予測結果の辞書:
            - symbol, source, current_price, forecast_days
            - current: 現在のボラティリティ統計（calc_volatility_stats の結果）
            - forecast: 予測ボラティリティ（ATR, ATR%, レジーム, トレンド等）
            - ml: ML モデルの詳細（ステータス, モデル名, R², 推論方法）
            - interpretation: 予測結果の日本語解釈文
    """
    key = cache_key("ml:vol", symbol, days=days, forecast=forecast_days)
    if result_df is None:
        cached = cache_get(key)
        if cached is not None:
            return cached

    if result_df is None:
        df, source = get_ohlcv_data(symbol, days)
        result_df = compute_all_indicators(df)
    else:
        source = source or "shared"

    close = float(result_df["close"].iloc[-1])

    # 現在のボラティリティ統計を計算（ATR%, 標準偏差等）
    current = calc_volatility_stats(result_df)
    # ATR の時系列（ML 特徴量・EWMA フォールバックに使用）
    atr_s = _atr_series(result_df)
    # 20日ボラ: 終値の日次リターンの標準偏差 × 100（%表示）
    daily_vol = result_df["close"].pct_change().rolling(20).std() * 100

    # EWMA によるベースライン予測（ML 失敗時のフォールバック）
    ewma_atr = _ewma_forecast(atr_s, span=10, steps=forecast_days)
    ewma_vol = _ewma_forecast(daily_vol, span=10, steps=forecast_days)

    # === ML: 将来 ATR を RandomForestRegressor で回帰予測 ===
    ml_forecast = None
    test_r2 = None
    inference = "ewma_fallback"
    lookback = 5

    # ML 用の特徴量データフレームを構築
    feat_df = pd.DataFrame({
        "atr": atr_s,
        "vol20": daily_vol,
        "rsi": result_df["rsi"],
        # 高安値幅%: 当日のボラティリティの直接的な指標
        "range_pct": (result_df["high"] - result_df["low"]) / result_df["close"] * 100,
    }).dropna()

    # 最低サンプル数の確認（lookback + forecast_days + 余裕30）
    if len(feat_df) >= lookback + forecast_days + 30:
        X, y = [], []
        vals = feat_df.values
        # ターゲット: forecast_days 日後の ATR（shift で未来のATRをラベルとして使用）
        target = atr_s.loc[feat_df.index].shift(-forecast_days)

        for i in range(lookback, len(feat_df) - forecast_days):
            if pd.isna(target.iloc[i]):
                continue
            # 過去 lookback ステップの特徴量を flatten して入力ベクトルに
            X.append(vals[i - lookback : i].flatten())
            y.append(float(target.iloc[i]))

        if len(X) >= 30:
            X_arr, y_arr = np.array(X), np.array(y)
            path = model_file("volatility", symbol, days=days, forecast=forecast_days)
            last_features = X_arr[-1]

            def _train() -> dict:
                """RandomForestRegressor で future ATR を学習する内部クロージャ。"""
                X_train, X_test, y_train, y_test = train_test_split(
                    X_arr, y_arr, test_size=0.2, shuffle=False
                )
                # 60本の決定木でアンサンブル（速度と精度のバランス）
                model = RandomForestRegressor(n_estimators=60, random_state=42, n_jobs=-1)
                model.fit(X_train, y_train)
                return {
                    "model": model,
                    "test_r2": round(float(model.score(X_test, y_test)), 4),
                }

            bundle = load_or_train(path, _train)
            model = bundle["model"]
            # 最新の特徴量で forecast_days 日後の ATR を予測
            ml_forecast = float(model.predict(last_features.reshape(1, -1))[0])
            test_r2 = bundle.get("test_r2")
            inference = "cached" if bundle.get("loaded_from_disk") else "trained"

    # ML 予測が成功した場合は ML を優先、失敗時は EWMA を使用
    predicted_atr = ml_forecast if ml_forecast else ewma_atr
    # ATR% = ATR / 現在価格 × 100（価格水準に依存しない相対指標）
    predicted_atr_pct = predicted_atr / close * 100 if close else 0
    regime, regime_label = _vol_regime(predicted_atr_pct)

    # ボラティリティトレンドの判定（現在 vs 予測の変化率）
    recent_atr_pct = current["atr_percent"]
    vol_change = round((predicted_atr_pct - recent_atr_pct) / max(recent_atr_pct, 0.01) * 100, 1)
    if vol_change > 10:
        # 予測ATRが現在より10%以上高い → ボラ拡大見込み
        vol_trend = "expanding"
        vol_trend_label = "ボラ拡大見込み"
    elif vol_change < -10:
        # 予測ATRが現在より10%以上低い → ボラ収縮見込み
        vol_trend = "contracting"
        vol_trend_label = "ボラ収縮見込み"
    else:
        # ±10% の範囲 → ほぼ横ばい
        vol_trend = "stable"
        vol_trend_label = "ボラ横ばい見込み"

    result = {
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
            "test_r2": test_r2,
            "inference": inference,
        },
        # 人間向けの予測結果サマリー
        "interpretation": (
            f"今後{forecast_days}日のATR予測: {predicted_atr:.4f} "
            f"({predicted_atr_pct:.2f}%) — {regime_label}、{vol_trend_label}"
        ),
    }
    cache_put(key, result)
    return result
