"""
トレンド予測モジュール（機械学習 + テクニカルルール + マルチタイムフレーム）

FX 相場のトレンド方向（bullish/bearish/neutral）を3つの手法を組み合わせて予測する:

1. ルールベース（_rule_trend）:
   SMA クロスオーバー・終値と SMA の位置関係・RSI・MACD の
   4つの指標をスコアリングして機械的にトレンドを判定

2. 機械学習（RandomForestClassifier）:
   過去 lookback ステップのテクニカル指標を特徴量として
   horizon 日後のリターンを 3 クラス分類（bullish/bearish/neutral）

3. マルチタイムフレーム（MTF）:
   複数時間足（例: 1H, 4H, 日足）のトレンドが揃っているかを確認

最終判定（多数決）:
    3手法のうち 2 票以上が一致したトレンドを採用する

キャッシュ:
    analysis_cache でキャッシュ（result_df が外部から渡された場合は無効）
    → バッチ分析時の重複計算を回避
"""

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import train_test_split

from src.analysis.multi_timeframe import analyze_multi_timeframe
from src.analysis.technical import compute_all_indicators
from src.data.market_data import get_ohlcv_data
from src.infra.analysis_cache import cache_get, cache_key, cache_put
from src.ml.model_store import load_or_train, model_file


def _rule_trend(latest: pd.Series) -> tuple[str, list[str]]:
    """ルールベースでテクニカル指標からトレンドを判定する。

    4つの指標をスコアリングし、合計スコアに基づいてトレンドを返す:
        +1: 上昇シグナル、-1: 下降シグナル、0: 無効（条件を満たさない）

    スコア集計:
        1. SMA20 vs SMA50: 短期 > 長期 → +1（ゴールデンクロス状態）
        2. 終値 vs SMA20: 終値 > SMA20 → +1（SMA 上にある）
        3. RSI: > 55 → +1（買い圧力強い）、< 45 → -1（売り圧力強い）
        4. MACD vs シグナル: MACD > シグナル → +1（上昇モメンタム）

    判定基準:
        合計 >= +2 → bullish、<= -2 → bearish、それ以外 → neutral

    Args:
        latest: DataFrame の最新行（テクニカル指標を含む pd.Series）

    Returns:
        タプル（トレンドラベル, 判定根拠のリスト）
    """
    reasons: list[str] = []
    score = 0

    # 1. SMA クロスオーバー: SMA20 > SMA50 は短期上昇トレンドのシグナル
    if pd.notna(latest.get("sma_20")) and pd.notna(latest.get("sma_50")):
        if latest["sma_20"] > latest["sma_50"]:
            score += 1
            reasons.append("SMA20 > SMA50（短期上昇トレンド）")
        elif latest["sma_20"] < latest["sma_50"]:
            score -= 1
            reasons.append("SMA20 < SMA50（短期下降トレンド）")

    # 2. 終値と SMA20 の位置関係: 終値が SMA 上にあれば上昇傾向
    if pd.notna(latest.get("close")) and pd.notna(latest.get("sma_20")):
        if latest["close"] > latest["sma_20"]:
            score += 1
            reasons.append("終値がSMA20上")
        else:
            score -= 1
            reasons.append("終値がSMA20下")

    # 3. RSI による買い/売り圧力の判定
    # RSI > 55: 買い圧力優勢、< 45: 売り圧力優勢、45-55: 中立
    rsi = latest.get("rsi")
    if pd.notna(rsi):
        if rsi > 55:
            score += 1
            reasons.append(f"RSI {rsi:.1f}（買い圧力）")
        elif rsi < 45:
            score -= 1
            reasons.append(f"RSI {rsi:.1f}（売り圧力）")

    # 4. MACD ゴールデン/デッドクロス: MACD > シグナル は上昇モメンタム
    if pd.notna(latest.get("macd")) and pd.notna(latest.get("macd_signal")):
        if latest["macd"] > latest["macd_signal"]:
            score += 1
            reasons.append("MACD > シグナル")
        else:
            score -= 1
            reasons.append("MACD < シグナル")

    # スコアに基づいてトレンドラベルを決定（2票以上で方向性ありと判断）
    if score >= 2:
        return "bullish", reasons
    if score <= -2:
        return "bearish", reasons
    return "neutral", reasons


def _build_trend_dataset(df: pd.DataFrame, horizon: int = 5, lookback: int = 5) -> tuple[np.ndarray, np.ndarray]:
    """RandomForestClassifier 用のトレンド分類データセットを生成する。

    horizon 日後のリターンを計算し、3 クラスのラベルを付与する:
        - 1（bullish）: horizon 日後のリターン > +0.1%
        - 0（bearish）: horizon 日後のリターン < -0.1%
        - 2（neutral）: それ以外（-0.1% 〜 +0.1%）

    閾値 ±0.1% の意味:
        FX では微小な変動は「横ばい」として扱い、
        明確な方向性のある動きのみをシグナルとして学習させる

    Args:
        df: テクニカル指標を含む DataFrame
        horizon: 何日後のリターンでラベルを付けるか（デフォルト: 5日後）
        lookback: 入力特徴量のウィンドウサイズ

    Returns:
        タプル（X, y）:
            X: 形状 (samples, lookback × features) の特徴量マトリクス
            y: 形状 (samples,) のクラスラベル（0, 1, 2）
            データ不足の場合は (空配列, 空配列) を返す
    """
    cols = ["sma_20", "sma_50", "rsi", "macd", "macd_signal", "stoch_k", "close"]
    available = [c for c in cols if c in df.columns]
    work = df[available].dropna().copy()
    # lookback + horizon + マージン（20）のデータが必要
    if len(work) < lookback + horizon + 20:
        return np.array([]), np.array([])

    # 終値シリーズ（将来リターンの計算に使用）
    close = df.loc[work.index, "close"]
    X, y = [], []
    values = work.values

    for i in range(lookback, len(work) - horizon):
        # i ステップから horizon 日後のリターンを計算
        future_ret = close.iloc[i + horizon] / close.iloc[i] - 1
        # ±0.1% を閾値としてラベルを付与
        label = 1 if future_ret > 0.001 else (0 if future_ret < -0.001 else 2)
        X.append(values[i - lookback : i].flatten())
        y.append(label)

    return np.array(X), np.array(y)


def predict_trend(
    symbol: str,
    days: int = 200,
    horizon: int = 5,
    *,
    result_df: pd.DataFrame | None = None,
    source: str | None = None,
    mtf: dict | None = None,
) -> dict:
    """トレンド予測を実行する（ルール + ML + MTF の統合）。

    3つの予測手法の結果を多数決で統合して最終トレンドを決定する。

    呼び出しパターン:
        1. 単独呼び出し: symbol を指定してデータを内部で取得
        2. バッチ呼び出し: result_df を外部から渡して重複データ取得を避ける

    Args:
        symbol: 通貨ペアコード（例: "USDJPY"）
        days: データ取得期間（日数）
        horizon: 予測する日数（例: 5 = 5日後のトレンドを予測）
        result_df: テクニカル指標付き DataFrame（None の場合は内部で取得）
        source: データソース名（result_df を外部から渡す場合に使用）
        mtf: マルチタイムフレーム分析結果（None の場合は内部で計算）

    Returns:
        トレンド予測結果の辞書:
            - symbol: 通貨ペア
            - source: データ取得元
            - current_price: 現在価格
            - trend: 最終トレンド（"bullish", "bearish", "neutral"）
            - trend_label: 日本語トレンドラベル
            - confidence: 信頼度（ML モデルの確率、またはデフォルト 50%）
            - horizon_days: 予測期間
            - rule_based: ルールベース判定結果
            - ml: ML モデル判定結果
            - multi_timeframe: MTF 判定結果
    """
    # キャッシュキーを生成（result_df が渡された場合はキャッシュを使わない）
    key = cache_key("ml:trend", symbol, days=days, horizon=horizon)
    if result_df is None:
        cached = cache_get(key)
        if cached is not None:
            return cached

    if result_df is None:
        # 外部から渡されていない場合は市場データを取得してテクニカル指標を計算
        df, source = get_ohlcv_data(symbol, days)
        result_df = compute_all_indicators(df)
    else:
        source = source or "shared"

    latest = result_df.iloc[-1]
    price = float(latest["close"])

    # ルールベース判定（テクニカル指標のスコアリング）
    rule_trend, reasons = _rule_trend(latest)

    # MTF（マルチタイムフレーム）分析
    if mtf is None:
        mtf = analyze_multi_timeframe(symbol)

    # ML データセットを生成して RandomForest で分類
    X, y = _build_trend_dataset(result_df, horizon=horizon)
    ml_result: dict = {"status": "insufficient_data"}

    if len(X) >= 40:
        # 十分なデータがある場合は ML モデルを学習（またはキャッシュから読み込み）
        path = model_file("trend", symbol, days=days, horizon=horizon)

        def _train() -> dict:
            """RandomForestClassifier を学習する内部クロージャ。"""
            # 時系列分割（シャッフルなし）
            X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, shuffle=False)
            # 80 本の決定木でアンサンブル（n_jobs=-1 で並列化）
            model = RandomForestClassifier(n_estimators=80, random_state=42, n_jobs=-1)
            model.fit(X_train, y_train)
            return {
                "model": model,
                "test_accuracy": round(float(model.score(X_test, y_test)) * 100, 1),
            }

        bundle = load_or_train(path, _train)
        model = bundle["model"]

        # 最新の特徴量ベクトルでトレンドを予測
        pred = int(model.predict(X[-1].reshape(1, -1))[0])
        # クラスごとの確率を取得（多クラス確率の最大値を信頼度として使用）
        proba = model.predict_proba(X[-1].reshape(1, -1))[0]

        # クラスラベルを文字列に変換
        trend_map = {1: "bullish", 0: "bearish", 2: "neutral"}
        ml_trend = trend_map.get(pred, "neutral")
        # 最も高い確率を信頼度（%）として使用
        confidence = round(float(max(proba)) * 100, 1)
        ml_result = {
            "status": "success",
            "trend": ml_trend,
            "confidence": confidence,
            "horizon_days": horizon,
            "test_accuracy": bundle.get("test_accuracy"),
            "model": "RandomForestClassifier",
            "inference": "cached" if bundle.get("loaded_from_disk") else "trained",
        }
    else:
        # データ不足時はルールベースの結果をフォールバックとして使用
        ml_trend = rule_trend
        confidence = 50.0

    # === ルール + ML + MTF の多数決で最終トレンドを決定 ===
    votes = [rule_trend, ml_result.get("trend", rule_trend), mtf.get("alignment", "neutral")]
    bull = votes.count("bullish")
    bear = votes.count("bearish")

    if bull > bear and bull >= 2:
        # 2票以上が bullish → 上昇トレンド確定
        combined = "bullish"
        label = "上昇トレンド"
    elif bear > bull and bear >= 2:
        # 2票以上が bearish → 下降トレンド確定
        combined = "bearish"
        label = "下降トレンド"
    else:
        # 決定打なし → レンジ相場として扱う
        combined = "neutral"
        label = "レンジ / 方向感なし"

    result = {
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
    # result_df が外部から渡された場合はキャッシュしない（重複保存を避ける）
    cache_put(key, result)
    return result
