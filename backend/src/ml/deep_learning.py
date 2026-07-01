"""
ディープラーニングモジュール — TensorFlow / PyTorch LSTM 価格予測

LSTM（Long Short-Term Memory）ネットワークを使って
FX の終値を時系列予測するモジュール。

対応バックエンド:
    - TensorFlow/Keras: tf.keras.Sequential + LSTM × 2 + Dropout + Dense
    - PyTorch: nn.LSTM + nn.Linear（カスタム LSTMModel クラス）
    - sklearn: RandomForestRegressor（ディープラーニングが使えない環境向け）

バックエンドの自動選択:
    resolve_price_backend() が設定（settings.ml_price_backend）を参照し、
    "auto" の場合は TensorFlow → PyTorch → sklearn の順で利用可能なものを選択する。

学習フロー（TensorFlow / PyTorch 共通）:
    1. prepare_sequences() でルックバック窓（lookback × features）の時系列を生成
    2. scale_sequences() / scale_targets() で StandardScaler 正規化
    3. 80:20 の時系列分割で訓練/テストデータを作成
    4. LSTM モデルを訓練（エポック数・バッチサイズは設定から取得）
    5. 学習済みモデルとスケーラーを model_store 経由でディスクにキャッシュ
    6. 次回呼び出し時はキャッシュが有効な場合に再学習をスキップ（推論のみ）
"""

from __future__ import annotations

import logging
import os
from typing import Any

import numpy as np
import pandas as pd
from sklearn.preprocessing import StandardScaler

from src.config import settings

logger = logging.getLogger(__name__)

# TensorFlow のログを最小化（INFO/WARNING を抑制）
os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "2")
# oneDNN 最適化を無効化（環境によっては予測値が変わる可能性があるため）
os.environ.setdefault("TF_ENABLE_ONEDNN_OPTS", "0")

# LSTM モデルに投入するデフォルト特徴量カラム
# close: ターゲット変数、残りはテクニカル指標
DEFAULT_FEATURE_COLS = [
    "close",
    "sma_20",
    "sma_50",
    "rsi",
    "macd",
    "macd_signal",
    "stoch_k",
    "stoch_d",
]


def check_ml_frameworks() -> dict:
    """インストール済みの ML フレームワークとそのバージョンを確認する。

    TensorFlow と PyTorch の import を試みて、
    インストールされていれば バージョン文字列、されていなければ None を返す。

    Returns:
        フレームワーク名をキー、バージョン文字列（またはNone）を値とする辞書:
            - tensorflow: インストール済みのバージョン（例: "2.15.0"）、またはNone
            - pytorch: インストール済みのバージョン（例: "2.1.0"）、またはNone
    """
    frameworks: dict[str, str | None] = {}

    try:
        import tensorflow as tf

        frameworks["tensorflow"] = tf.__version__
    except ImportError:
        frameworks["tensorflow"] = None

    try:
        import torch

        frameworks["pytorch"] = torch.__version__
    except ImportError:
        frameworks["pytorch"] = None

    return frameworks


def resolve_price_backend(preferred: str | None = None) -> str:
    """利用可能な価格予測バックエンドを選択して返す。

    優先順位:
        1. preferred または settings.ml_price_backend で明示指定されたバックエンド
        2. "auto" または指定なし → TensorFlow → PyTorch → sklearn の順で選択

    フォールバック:
        指定されたバックエンドが未インストールの場合は sklearn に自動フォールバック

    Args:
        preferred: 優先するバックエンド名（"tensorflow", "pytorch", "sklearn", "auto"）

    Returns:
        使用するバックエンド名（"tensorflow", "pytorch", "sklearn" のいずれか）
    """
    pref = (preferred or settings.ml_price_backend).lower()
    frameworks = check_ml_frameworks()

    # 明示指定がある場合はそのバックエンドを優先（未インストールなら sklearn）
    if pref == "sklearn":
        return "sklearn"
    if pref == "tensorflow":
        return "tensorflow" if frameworks["tensorflow"] else "sklearn"
    if pref == "pytorch":
        return "pytorch" if frameworks["pytorch"] else "sklearn"

    # "auto" または未知の指定: 利用可能なものを順に試みる
    if frameworks["tensorflow"]:
        return "tensorflow"
    if frameworks["pytorch"]:
        return "pytorch"
    return "sklearn"


def prepare_sequences(
    df: pd.DataFrame,
    lookback: int | None = None,
    feature_cols: list[str] | None = None,
) -> tuple[np.ndarray, np.ndarray]:
    """LSTM 用の時系列ウィンドウとターゲット配列を生成する。

    入力データから lookback 期間のスライディングウィンドウを生成し、
    LSTM モデルが期待する形状 (samples, lookback, features) の配列を作る。

    ウィンドウ生成の例（lookback=3, 入力長=6）:
        [t0, t1, t2] → target: t3
        [t1, t2, t3] → target: t4
        [t2, t3, t4] → target: t5

    Args:
        df: テクニカル指標を含む DataFrame（各行が1タイムステップ）
        lookback: ウィンドウサイズ（過去何ステップを入力とするか）。
                  None の場合は settings.ml_lstm_lookback を使用
        feature_cols: 使用する特徴量のカラム名リスト。
                      None の場合は DEFAULT_FEATURE_COLS を使用

    Returns:
        タプル（X, y）:
            X: 形状 (samples, lookback, features) の入力配列
            y: 形状 (samples,) のターゲット（終値）配列
            データ不足の場合は (空配列, 空配列) を返す
    """
    lookback = lookback or settings.ml_lstm_lookback
    feature_cols = feature_cols or DEFAULT_FEATURE_COLS
    # DataFrame に存在するカラムのみを使用（欠損カラムは無視）
    available = [c for c in feature_cols if c in df.columns]
    # close カラムが必須、かつ最低2カラム必要
    if len(available) < 2 or "close" not in available:
        return np.array([]), np.array([])

    # NaN を除去してから変換（NaN があると LSTM の学習が失敗するため）
    work = df[available].dropna()
    # lookback + 余裕分のデータが必要
    if len(work) < lookback + 10:
        return np.array([]), np.array([])

    values = work.values.astype(np.float64)
    # ターゲットカラム（close）のインデックスを特定
    close_idx = available.index("close")
    x_list: list[np.ndarray] = []
    y_list: list[float] = []

    # スライディングウィンドウで入力ウィンドウとターゲットのペアを生成
    for i in range(lookback, len(values)):
        # 入力: i-lookback から i-1 までの lookback ステップ
        x_list.append(values[i - lookback : i])
        # ターゲット: i ステップ目の終値（1ステップ先の予測）
        y_list.append(float(values[i, close_idx]))

    if not x_list:
        return np.array([]), np.array([])

    return np.array(x_list), np.array(y_list)


def scale_sequences(
    x: np.ndarray,
    scaler: StandardScaler | None = None,
) -> tuple[np.ndarray, StandardScaler]:
    """時系列データを StandardScaler で正規化する（z-score 正規化）。

    3D 配列 (samples, lookback, features) を 2D に展開してスケーリングし、
    元の形状に戻す。スケーラーが指定された場合は fit_transform せず
    transform のみを実行（推論時のデータリーク防止）。

    Args:
        x: 形状 (samples, lookback, features) の入力配列
        scaler: 既存の StandardScaler（None の場合は新規にフィット）

    Returns:
        タプル（正規化済み配列, StandardScaler）
    """
    n_samples, _lookback, n_features = x.shape
    # 2D に展開してスケーリング（StandardScaler は 2D を期待）
    flat = x.reshape(-1, n_features)
    if scaler is None:
        scaler = StandardScaler()
        scaler.fit(flat)
    # transform して元の 3D 形状に戻す
    scaled = scaler.transform(flat).reshape(n_samples, _lookback, n_features)
    return scaled, scaler


def scale_targets(
    y: np.ndarray,
    scaler: StandardScaler | None = None,
) -> tuple[np.ndarray, StandardScaler]:
    """ターゲット（終値）配列を StandardScaler で正規化する。

    LSTM の出力層を 1 ユニットにして終値を直接予測するため、
    ターゲットも入力と別に正規化する必要がある。

    Args:
        y: 形状 (samples,) のターゲット配列（終値）
        scaler: 既存のスケーラー（None の場合は新規作成）

    Returns:
        タプル（正規化済みターゲット配列, StandardScaler）
    """
    # StandardScaler は 2D を期待するため reshape
    y_2d = y.reshape(-1, 1)
    if scaler is None:
        scaler = StandardScaler()
        scaler.fit(y_2d)
    # ravel() で 1D に戻す
    return scaler.transform(y_2d).ravel(), scaler


def inverse_scale_target(value: float, scaler: StandardScaler) -> float:
    """正規化済みの予測値を元の価格スケールに逆変換する。

    モデルの出力（正規化済み終値）を実際の価格に戻すために使用する。

    Args:
        value: モデルが出力した正規化済みスカラー値
        scaler: 学習時に使用したターゲットの StandardScaler

    Returns:
        元のスケール（USD/JPY 等）に戻した予測価格
    """
    return float(scaler.inverse_transform([[value]])[0][0])


def scale_single_sequence(x: np.ndarray, scaler: StandardScaler) -> np.ndarray:
    """推論用に単一のウィンドウを正規化する。

    形状 (lookback, features) の1つの入力ウィンドウを、
    学習時のスケーラーで正規化して (1, lookback, features) に変換する。

    Args:
        x: 形状 (lookback, features) の単一ウィンドウ
        scaler: 学習時に使用した入力の StandardScaler

    Returns:
        形状 (1, lookback, features) の正規化済み配列（バッチ次元追加済み）
    """
    lookback, n_features = x.shape
    flat = x.reshape(-1, n_features)
    return scaler.transform(flat).reshape(1, lookback, n_features)


def create_lstm_model(input_shape: tuple, units: int | None = None):
    """TensorFlow/Keras で2層 LSTM 価格予測モデルを構築する。

    モデル構造:
        - LSTM(units, return_sequences=True): 時系列の全ステップを次の層に渡す
        - Dropout(0.2): 過学習防止
        - LSTM(units//2): 最終ステップのみを次の層に渡す
        - Dropout(0.2): 過学習防止
        - Dense(1): 終値を1値で出力

    最適化:
        - optimizer: Adam（学習率は Keras デフォルトの 0.001）
        - loss: MSE（平均二乗誤差、回帰タスク）
        - metrics: MAE（平均絶対誤差、精度の参考指標）

    Args:
        input_shape: 入力形状のタプル (lookback, n_features)
        units: LSTM ユニット数（None の場合は settings.ml_lstm_units を使用）

    Returns:
        コンパイル済みの tf.keras.Sequential モデル
    """
    import tensorflow as tf

    units = units or settings.ml_lstm_units
    model = tf.keras.Sequential(
        [
            # 第1層 LSTM: return_sequences=True で全ステップの出力を第2層に渡す
            tf.keras.layers.LSTM(units, return_sequences=True, input_shape=input_shape),
            tf.keras.layers.Dropout(0.2),
            # 第2層 LSTM: 最後のタイムステップのみを Dense 層に渡す
            tf.keras.layers.LSTM(max(units // 2, 8)),
            tf.keras.layers.Dropout(0.2),
            # 出力層: 次の終値を1つのスカラーとして出力
            tf.keras.layers.Dense(1),
        ]
    )
    model.compile(optimizer="adam", loss="mse", metrics=["mae"])
    return model


def create_pytorch_lstm(input_size: int, hidden_size: int | None = None, num_layers: int = 2):
    """PyTorch で2層 LSTM 価格予測モデルを構築する。

    モデル構造（LSTMModel クラス）:
        - nn.LSTM(input_size, hidden_size, num_layers, batch_first=True):
          batch_first=True で入力を (batch, seq, features) 形式に
        - nn.Linear(hidden_size, 1): 最終ステップの隠れ状態から終値を予測

    Dropout:
        num_layers > 1 の場合のみ LSTM 内の Dropout（0.2）を有効化

    forward() の処理:
        1. LSTM に入力を渡し、全ステップの出力と最終隠れ状態を取得
        2. 最終タイムステップの出力（out[:, -1, :]）を全結合層に渡す
        3. スカラー予測値を返す

    Args:
        input_size: 入力特徴量の数
        hidden_size: LSTM の隠れユニット数（None の場合は settings.ml_lstm_units）
        num_layers: LSTM の層数（デフォルト: 2）

    Returns:
        初期化済みの LSTMModel インスタンス（未学習）
    """
    import torch.nn as nn

    hidden_size = hidden_size or settings.ml_lstm_units

    class LSTMModel(nn.Module):
        """PyTorch LSTM 価格予測モデル。

        属性:
            lstm: 多層 LSTM モジュール（batch_first=True）
            fc: 終値を出力する全結合層（隠れ次元 → 1）
        """

        def __init__(self):
            super().__init__()
            # LSTM 層: batch_first=True で (batch, seq, features) 形式を受け取る
            self.lstm = nn.LSTM(
                input_size,
                hidden_size,
                num_layers,
                batch_first=True,
                # 多層 LSTM の場合のみ層間 Dropout を有効化
                dropout=0.2 if num_layers > 1 else 0.0,
            )
            # 最終タイムステップの隠れ状態から1値（終値）を予測する全結合層
            self.fc = nn.Linear(hidden_size, 1)

        def forward(self, x):
            """フォワードパス（推論・学習共用）。

            Args:
                x: 形状 (batch, lookback, features) の入力テンソル

            Returns:
                形状 (batch, 1) の予測終値テンソル
            """
            # LSTM を通す（out: 全ステップの出力、_: 最終隠れ状態）
            out, _ = self.lstm(x)
            # 最終タイムステップの出力を全結合層に渡して予測値を得る
            return self.fc(out[:, -1, :])

    return LSTMModel()


def _insufficient() -> dict:
    """データ不足時のエラーレスポンスを生成する。

    Returns:
        status="insufficient_data" のエラー辞書
    """
    return {"status": "insufficient_data", "message": "データが不足しています"}


def train_tensorflow_price_predictor(
    df: pd.DataFrame,
    symbol: str,
    days: int,
) -> dict:
    """TensorFlow LSTM を使って価格予測モデルを学習・推論する。

    学習フロー:
        1. prepare_sequences() でルックバックウィンドウを生成（最低30サンプル必要）
        2. キャッシュ（モデルファイル）が有効な場合は学習をスキップして推論
        3. 新規学習時: 80:20 時系列分割 → モデル構築 → epochs エポック学習
        4. 最新ウィンドウで次の終値を予測
        5. モデルとスケーラーをディスクにキャッシュ

    Args:
        df: テクニカル指標を含む DataFrame
        symbol: 通貨ペアコード（モデルファイルのパス生成に使用）
        days: データ期間（モデルファイルのパス生成に使用）

    Returns:
        予測結果の辞書:
            - status: "success" または "insufficient_data"
            - prediction: 予測終値
            - current_price: 現在の終値
            - train_mae / test_mae: 学習・テスト MAE
            - model: モデル名（"LSTM (TensorFlow)"）
            - backend: "tensorflow"
            - inference: "cached"（キャッシュ使用）または "trained"（新規学習）
    """
    from src.ml.model_store import dl_model_paths, load_or_train_dl

    lookback = settings.ml_lstm_lookback
    x, y = prepare_sequences(df, lookback)
    # 最低30サンプル（ウィンドウ）が必要
    if len(x) < 30:
        return _insufficient()

    # TensorFlow 用モデルのパス（.keras + メタ .joblib）を生成
    paths = dl_model_paths("price", symbol, "tensorflow", days=days)

    def _train() -> dict[str, Any]:
        """TensorFlow LSTM モデルを学習する内部クロージャ。"""
        # 入力とターゲットをそれぞれ正規化（スケーラーはキャッシュに含める）
        x_scaled, x_scaler = scale_sequences(x)
        y_scaled, y_scaler = scale_targets(y)

        # 80:20 の時系列分割（シャッフルなし、未来データを学習に使わない）
        split = max(int(len(x_scaled) * 0.8), len(x_scaled) - 5)
        x_train, x_test = x_scaled[:split], x_scaled[split:]
        y_train, y_test = y_scaled[:split], y_scaled[split:]

        # LSTM モデルを構築して学習
        model = create_lstm_model((lookback, x.shape[2]))
        model.fit(
            x_train,
            y_train,
            epochs=settings.ml_lstm_epochs,
            batch_size=settings.ml_lstm_batch_size,
            verbose=0,  # ログ抑制
            # テストデータが存在する場合のみバリデーションを実行
            validation_data=(x_test, y_test) if len(x_test) > 0 else None,
        )

        # 学習データでの MAE を計算（逆変換してから誤差算出）
        train_preds = y_scaler.inverse_transform(
            model.predict(x_train, verbose=0).reshape(-1, 1)
        ).ravel()
        train_mae = float(np.mean(np.abs(train_preds - y[:split])))

        # テストデータでの MAE を計算
        if len(x_test) > 0:
            test_preds = y_scaler.inverse_transform(
                model.predict(x_test, verbose=0).reshape(-1, 1)
            ).ravel()
            test_mae = float(np.mean(np.abs(test_preds - y[split:])))
        else:
            test_mae = train_mae

        return {
            "model": model,
            "scaler": x_scaler,    # 入力の StandardScaler
            "y_scaler": y_scaler,  # ターゲットの StandardScaler
            "input_size": x.shape[2],
            "lookback": lookback,
            "train_mae": round(train_mae, 4),
            "test_mae": round(test_mae, 4),
        }

    # キャッシュ済みモデルがあれば読み込み、なければ学習して保存
    bundle = load_or_train_dl(paths, "tensorflow", _train)
    model = bundle["model"]
    scaler = bundle["scaler"]
    y_scaler = bundle["y_scaler"]

    # 最新のルックバックウィンドウで次の終値を予測
    last_x = scale_single_sequence(x[-1], scaler)
    raw_pred = float(model.predict(last_x, verbose=0)[0][0])
    # 正規化済み予測値を元のスケールに逆変換
    prediction = inverse_scale_target(raw_pred, y_scaler)

    return {
        "status": "success",
        "prediction": round(prediction, 4),
        "current_price": round(float(df["close"].iloc[-1]), 4),
        "train_mae": bundle.get("train_mae"),
        "test_mae": bundle.get("test_mae"),
        "model": "LSTM (TensorFlow)",
        "backend": "tensorflow",
        # キャッシュから読み込んだか、新規学習したかを示すフラグ
        "inference": "cached" if bundle.get("loaded_from_disk") else "trained",
    }


def train_pytorch_price_predictor(
    df: pd.DataFrame,
    symbol: str,
    days: int,
) -> dict:
    """PyTorch LSTM を使って価格予測モデルを学習・推論する。

    学習フロー（TensorFlow 版と同等のロジック、PyTorch 実装）:
        1. prepare_sequences() でルックバックウィンドウを生成
        2. キャッシュが有効な場合は再学習をスキップ
        3. 新規学習時: Adam オプティマイザ + MSE 損失でミニバッチ学習
           （注: PyTorch 実装では全データを1バッチで学習）
        4. 最新ウィンドウで推論

    Args:
        df: テクニカル指標を含む DataFrame
        symbol: 通貨ペアコード
        days: データ期間

    Returns:
        TensorFlow 版と同形式の予測結果辞書（backend="pytorch"）
    """
    import torch
    import torch.nn as nn

    from src.ml.model_store import dl_model_paths, load_or_train_dl

    lookback = settings.ml_lstm_lookback
    x, y = prepare_sequences(df, lookback)
    if len(x) < 30:
        return _insufficient()

    # PyTorch 用モデルのパス（.pt の state_dict + メタ .joblib）を生成
    paths = dl_model_paths("price", symbol, "pytorch", days=days)

    def _train() -> dict[str, Any]:
        """PyTorch LSTM モデルを学習する内部クロージャ。"""
        x_scaled, x_scaler = scale_sequences(x)
        y_scaled, y_scaler = scale_targets(y)

        # 80:20 の時系列分割
        split = max(int(len(x_scaled) * 0.8), len(x_scaled) - 5)
        x_train, x_test = x_scaled[:split], x_scaled[split:]
        y_train, y_test = y_scaled[:split], y_scaled[split:]

        input_size = x.shape[2]
        model = create_pytorch_lstm(input_size)
        criterion = nn.MSELoss()
        optimizer = torch.optim.Adam(model.parameters(), lr=0.001)

        # NumPy 配列を PyTorch テンソルに変換
        x_tensor = torch.tensor(x_train, dtype=torch.float32)
        # ターゲットは (batch, 1) 形状に変換（MSELoss の要件）
        y_tensor = torch.tensor(y_train, dtype=torch.float32).unsqueeze(1)

        # 学習ループ（指定エポック数分繰り返す）
        model.train()
        for _ in range(settings.ml_lstm_epochs):
            optimizer.zero_grad()        # 勾配をリセット
            out = model(x_tensor)        # フォワードパス
            loss = criterion(out, y_tensor)  # MSE 損失を計算
            loss.backward()              # 誤差逆伝播
            optimizer.step()             # パラメータ更新

        # 評価モードに切り替えて MAE を計算
        model.eval()
        with torch.no_grad():  # 評価時は勾配計算を無効化
            train_preds = y_scaler.inverse_transform(
                model(x_tensor).numpy().reshape(-1, 1)
            ).ravel()
            train_mae = float(np.mean(np.abs(train_preds - y[:split])))
            if len(x_test) > 0:
                test_preds = y_scaler.inverse_transform(
                    model(torch.tensor(x_test, dtype=torch.float32)).numpy().reshape(-1, 1)
                ).ravel()
                test_mae = float(np.mean(np.abs(test_preds - y[split:])))
            else:
                test_mae = train_mae

        return {
            "model": model,
            "scaler": x_scaler,
            "y_scaler": y_scaler,
            "input_size": input_size,
            "lookback": lookback,
            "train_mae": round(train_mae, 4),
            "test_mae": round(test_mae, 4),
        }

    # キャッシュ済みモデルがあれば読み込み、なければ学習して保存
    bundle = load_or_train_dl(paths, "pytorch", _train)
    model = bundle["model"]
    scaler = bundle["scaler"]
    y_scaler = bundle["y_scaler"]

    # 最新ウィンドウを正規化して推論
    last_x = scale_single_sequence(x[-1], scaler)

    import torch

    # 評価モードで推論（Dropout を無効化）
    model.eval()
    with torch.no_grad():
        pred_tensor = model(torch.tensor(last_x, dtype=torch.float32))
    # テンソルのスカラーを Python float に変換してから逆正規化
    prediction = inverse_scale_target(float(pred_tensor.item()), y_scaler)

    return {
        "status": "success",
        "prediction": round(prediction, 4),
        "current_price": round(float(df["close"].iloc[-1]), 4),
        "train_mae": bundle.get("train_mae"),
        "test_mae": bundle.get("test_mae"),
        "model": "LSTM (PyTorch)",
        "backend": "pytorch",
        "inference": "cached" if bundle.get("loaded_from_disk") else "trained",
    }
