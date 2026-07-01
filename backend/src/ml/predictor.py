"""
機械学習モジュール — 価格予測・特徴量エンジニアリング

テクニカル指標を特徴量としてランダムフォレスト（sklearn）または
LSTM（TensorFlow/PyTorch）で FX の終値を予測するモジュール。

バックエンド選択:
    resolve_price_backend() でシステム設定に応じたバックエンドを自動選択:
    1. TensorFlow が利用可能 → train_tensorflow_price_predictor
    2. PyTorch が利用可能 → train_pytorch_price_predictor
    3. いずれも未インストール → train_price_predictor_sklearn（RandomForest）

特徴量エンジニアリング:
    lookback 期間分のテクニカル指標を flatten して特徴量ベクトルを構成:
    - sma_20, sma_50: 短期・中期移動平均線
    - rsi: 相対力指数（オーバーボート/ソールド判定）
    - macd, macd_signal: MACD とシグナルライン
    - stoch_k, stoch_d: ストキャスティクス
    - bb_upper, bb_lower: ボリンジャーバンド上限・下限

キャッシュ戦略:
    - 分析キャッシュ（analysis_cache）: 同一リクエストの高速返却
    - モデルキャッシュ（model_store）: 学習済みモデルのディスク永続化
"""

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestRegressor
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import StandardScaler

from src.analysis.market_context import MarketContext
# インメモリキャッシュ（TTL 付き）
from src.infra.analysis_cache import cache_get, cache_key, cache_put
from src.ml.model_store import load_or_train, model_file


def prepare_features(df: pd.DataFrame, lookback: int = 5) -> tuple[np.ndarray, np.ndarray]:
    """テクニカル指標を sklearn 用の特徴量マトリクスに変換する。

    各タイムステップ i に対して、[i-lookback, i-1] の期間の
    テクニカル指標を flatten した特徴量ベクトルを生成する。

    特徴量の次元:
        len(available_cols) × lookback（例: 9列 × 5期間 = 45次元）

    Args:
        df: テクニカル指標を含む DataFrame
        lookback: 特徴量として使用する過去の期間数（デフォルト: 5）

    Returns:
        タプル（X, y）:
            X: 形状 (samples, lookback × features) の特徴量マトリクス
            y: 形状 (samples,) のターゲット（終値）配列
            データ不足の場合は (空配列, 空配列) を返す
    """
    feature_cols = [
        "sma_20", "sma_50", "rsi", "macd", "macd_signal",
        "stoch_k", "stoch_d", "bb_upper", "bb_lower",
    ]
    # DataFrame に存在するカラムのみを使用（欠損カラムは無視）
    available = [c for c in feature_cols if c in df.columns]
    if not available:
        return np.array([]), np.array([])

    # NaN を除去（テクニカル指標の計算初期は NaN になるため）
    features_df = df[available].dropna()
    if len(features_df) < lookback + 10:
        return np.array([]), np.array([])

    X, y = [], []
    values = features_df.values
    # close は features_df に含まれないため df から別途取得（インデックスを合わせる）
    close_values = df.loc[features_df.index, "close"].values

    # ルックバックウィンドウのスライディング処理
    for i in range(lookback, len(values)):
        # 過去 lookback ステップのテクニカル指標を flatten して特徴量ベクトルに
        X.append(values[i - lookback : i].flatten())
        # ターゲット: 現在ステップの終値（1ステップ先の終値を予測）
        y.append(close_values[i])

    return np.array(X), np.array(y)


def train_price_predictor_sklearn(df: pd.DataFrame, symbol: str = "", days: int = 200) -> dict:
    """RandomForestRegressor で価格予測モデルを学習・推論する。

    sklearn の RandomForest を使った価格予測。
    TensorFlow/PyTorch が利用できない環境でのフォールバックとして機能する。

    学習フロー:
        1. prepare_features() で特徴量を生成
        2. キャッシュ確認（symbol が指定された場合のみ）
        3. 80:20 時系列分割（シャッフルなし）で学習/テスト分割
        4. StandardScaler で正規化
        5. RandomForestRegressor(n_estimators=100) を学習
        6. 最新の特徴量ベクトルで予測

    Args:
        df: テクニカル指標を含む DataFrame
        symbol: 通貨ペアコード（モデルキャッシュのキーに使用。空文字はキャッシュなし）
        days: データ期間（モデルキャッシュのキーに使用）

    Returns:
        予測結果の辞書:
            - status: "success" または "insufficient_data"
            - prediction: 予測終値
            - current_price: 現在の終値
            - train_r2 / test_r2: 学習/テストの R² スコア
            - model: "RandomForestRegressor"
            - backend: "sklearn"
            - inference: "cached" または "trained"
    """
    X, y = prepare_features(df)
    if len(X) < 20:
        return {"status": "insufficient_data", "message": "データが不足しています"}

    # モデルキャッシュのパスを生成（symbol 指定時のみキャッシュを使用）
    path = model_file("price", symbol or "UNKNOWN", days=days)
    # 推論に使用する最新の特徴量ベクトルを保持（lambda クロージャで使用）
    last_features = X[-1]

    def _train() -> dict:
        """RandomForest モデルを学習する内部クロージャ。"""
        # 時系列データなのでシャッフルなしで分割（未来データの漏洩を防ぐ）
        X_train, X_test, y_train, y_test = train_test_split(
            X, y, test_size=0.2, shuffle=False
        )
        # StandardScaler で正規化（スケーラーはキャッシュに含める）
        scaler = StandardScaler()
        X_train_scaled = scaler.fit_transform(X_train)
        X_test_scaled = scaler.transform(X_test)

        # RandomForest 学習（n_jobs=-1 で全 CPU コアを使用）
        model = RandomForestRegressor(n_estimators=100, random_state=42, n_jobs=-1)
        model.fit(X_train_scaled, y_train)
        return {
            "model": model,
            "scaler": scaler,
            "train_r2": round(float(model.score(X_train_scaled, y_train)), 4),
            "test_r2": round(float(model.score(X_test_scaled, y_test)), 4),
        }

    # symbol が指定された場合はキャッシュを活用、されていない場合は毎回学習
    bundle = load_or_train(path, _train) if symbol else _train()
    model = bundle["model"]
    scaler = bundle["scaler"]

    # 最新の特徴量を正規化して予測
    prediction = float(model.predict(scaler.transform(last_features.reshape(1, -1)))[0])

    return {
        "status": "success",
        "prediction": round(prediction, 4),
        "current_price": round(float(df["close"].iloc[-1]), 4),
        "train_r2": bundle.get("train_r2"),
        "test_r2": bundle.get("test_r2"),
        "model": "RandomForestRegressor",
        "backend": "sklearn",
        "inference": "cached" if bundle.get("loaded_from_disk") else "trained",
    }


def train_price_predictor(df: pd.DataFrame, symbol: str = "", days: int = 200) -> dict:
    """設定に応じて最適なバックエンドで価格予測を実行するファサード関数。

    バックエンドの選択:
        resolve_price_backend() が設定（settings.ml_price_backend）を参照し、
        利用可能なフレームワークに応じて自動選択する:
        - "tensorflow" → TensorFlow LSTM
        - "pytorch" → PyTorch LSTM
        - "sklearn"（フォールバック）→ RandomForestRegressor

    Args:
        df: テクニカル指標を含む DataFrame
        symbol: 通貨ペアコード
        days: データ期間

    Returns:
        使用したバックエンドに依存するが、共通キー:
            - status: "success" または "insufficient_data"
            - prediction: 予測終値
            - current_price: 現在の終値
            - backend: 使用したバックエンド名
    """
    from src.ml.deep_learning import (
        resolve_price_backend,
        train_pytorch_price_predictor,
        train_tensorflow_price_predictor,
    )

    # 利用可能なバックエンドを動的に解決
    backend = resolve_price_backend()
    if backend == "tensorflow":
        return train_tensorflow_price_predictor(df, symbol, days)
    if backend == "pytorch":
        return train_pytorch_price_predictor(df, symbol, days)
    # どちらも利用不可の場合は sklearn にフォールバック
    return train_price_predictor_sklearn(df, symbol, days)


def predict_price(symbol: str, days: int = 200) -> dict:
    """指定通貨ペアの価格予測を実行する（キャッシュ + モデル永続化）。

    2層のキャッシュで重複計算を回避:
        1. 分析キャッシュ（analysis_cache）: 同一シンボル・期間・バックエンドの
           結果を TTL 内で再利用（高速）
        2. モデルキャッシュ（model_store）: 学習済みモデルを TTL 内で再使用
           （再学習コストを削減）

    Args:
        symbol: 通貨ペアコード（例: "USDJPY"）
        days: データ取得期間（日数）

    Returns:
        価格予測結果の辞書（symbol と source を追加した train_price_predictor の戻り値）
    """
    from src.ml.deep_learning import resolve_price_backend

    backend = resolve_price_backend()
    # キャッシュキー: シンボル・期間・バックエンドの組み合わせで一意に識別
    key = cache_key("ml:price", symbol, days=days, backend=backend)
    cached = cache_get(key)
    if cached is not None:
        # キャッシュヒット: 即座に返す（市場データ取得・モデル推論なし）
        return cached

    # MarketContext を通じて過去データとテクニカル指標を取得
    ctx = MarketContext.load(symbol, days)
    prediction = train_price_predictor(ctx.result_df, symbol=symbol, days=days)
    result = {"symbol": symbol.upper(), "source": ctx.source, **prediction}
    # 次回呼び出しのために分析キャッシュに保存
    cache_put(key, result)
    return result
