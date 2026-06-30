"""ディープラーニングモジュール - TensorFlow / PyTorch LSTM 価格予測"""

from __future__ import annotations

import logging
import os
from typing import Any

import numpy as np
import pandas as pd
from sklearn.preprocessing import StandardScaler

from src.config import settings

logger = logging.getLogger(__name__)

os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "2")
os.environ.setdefault("TF_ENABLE_ONEDNN_OPTS", "0")

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
    """インストール済みMLフレームワークの確認"""
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
    """利用可能な価格予測バックエンドを解決（auto → tensorflow → pytorch → sklearn）"""
    pref = (preferred or settings.ml_price_backend).lower()
    frameworks = check_ml_frameworks()

    if pref == "sklearn":
        return "sklearn"
    if pref == "tensorflow":
        return "tensorflow" if frameworks["tensorflow"] else "sklearn"
    if pref == "pytorch":
        return "pytorch" if frameworks["pytorch"] else "sklearn"

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
    """LSTM 用の時系列ウィンドウ (samples, lookback, features) とターゲットを生成"""
    lookback = lookback or settings.ml_lstm_lookback
    feature_cols = feature_cols or DEFAULT_FEATURE_COLS
    available = [c for c in feature_cols if c in df.columns]
    if len(available) < 2 or "close" not in available:
        return np.array([]), np.array([])

    work = df[available].dropna()
    if len(work) < lookback + 10:
        return np.array([]), np.array([])

    values = work.values.astype(np.float64)
    close_idx = available.index("close")
    x_list: list[np.ndarray] = []
    y_list: list[float] = []

    for i in range(lookback, len(values)):
        x_list.append(values[i - lookback : i])
        y_list.append(float(values[i, close_idx]))

    if not x_list:
        return np.array([]), np.array([])

    return np.array(x_list), np.array(y_list)


def scale_sequences(
    x: np.ndarray,
    scaler: StandardScaler | None = None,
) -> tuple[np.ndarray, StandardScaler]:
    """系列データを StandardScaler で正規化"""
    n_samples, _lookback, n_features = x.shape
    flat = x.reshape(-1, n_features)
    if scaler is None:
        scaler = StandardScaler()
        scaler.fit(flat)
    scaled = scaler.transform(flat).reshape(n_samples, _lookback, n_features)
    return scaled, scaler


def scale_targets(
    y: np.ndarray,
    scaler: StandardScaler | None = None,
) -> tuple[np.ndarray, StandardScaler]:
    """ターゲット（終値）を正規化"""
    y_2d = y.reshape(-1, 1)
    if scaler is None:
        scaler = StandardScaler()
        scaler.fit(y_2d)
    return scaler.transform(y_2d).ravel(), scaler


def inverse_scale_target(value: float, scaler: StandardScaler) -> float:
    """正規化済み予測値を元の価格スケールに戻す"""
    return float(scaler.inverse_transform([[value]])[0][0])


def scale_single_sequence(x: np.ndarray, scaler: StandardScaler) -> np.ndarray:
    """推論用に単一ウィンドウを正規化"""
    lookback, n_features = x.shape
    flat = x.reshape(-1, n_features)
    return scaler.transform(flat).reshape(1, lookback, n_features)


def create_lstm_model(input_shape: tuple, units: int | None = None):
    """TensorFlow LSTM モデル構築（価格予測用）"""
    import tensorflow as tf

    units = units or settings.ml_lstm_units
    model = tf.keras.Sequential(
        [
            tf.keras.layers.LSTM(units, return_sequences=True, input_shape=input_shape),
            tf.keras.layers.Dropout(0.2),
            tf.keras.layers.LSTM(max(units // 2, 8)),
            tf.keras.layers.Dropout(0.2),
            tf.keras.layers.Dense(1),
        ]
    )
    model.compile(optimizer="adam", loss="mse", metrics=["mae"])
    return model


def create_pytorch_lstm(input_size: int, hidden_size: int | None = None, num_layers: int = 2):
    """PyTorch LSTM モデル構築（価格予測用）"""
    import torch.nn as nn

    hidden_size = hidden_size or settings.ml_lstm_units

    class LSTMModel(nn.Module):
        def __init__(self):
            super().__init__()
            self.lstm = nn.LSTM(
                input_size,
                hidden_size,
                num_layers,
                batch_first=True,
                dropout=0.2 if num_layers > 1 else 0.0,
            )
            self.fc = nn.Linear(hidden_size, 1)

        def forward(self, x):
            out, _ = self.lstm(x)
            return self.fc(out[:, -1, :])

    return LSTMModel()


def _insufficient() -> dict:
    return {"status": "insufficient_data", "message": "データが不足しています"}


def train_tensorflow_price_predictor(
    df: pd.DataFrame,
    symbol: str,
    days: int,
) -> dict:
    """TensorFlow LSTM による価格予測"""
    from src.ml.model_store import dl_model_paths, load_or_train_dl

    lookback = settings.ml_lstm_lookback
    x, y = prepare_sequences(df, lookback)
    if len(x) < 30:
        return _insufficient()

    paths = dl_model_paths("price", symbol, "tensorflow", days=days)

    def _train() -> dict[str, Any]:
        x_scaled, x_scaler = scale_sequences(x)
        y_scaled, y_scaler = scale_targets(y)
        split = max(int(len(x_scaled) * 0.8), len(x_scaled) - 5)
        x_train, x_test = x_scaled[:split], x_scaled[split:]
        y_train, y_test = y_scaled[:split], y_scaled[split:]

        model = create_lstm_model((lookback, x.shape[2]))
        model.fit(
            x_train,
            y_train,
            epochs=settings.ml_lstm_epochs,
            batch_size=settings.ml_lstm_batch_size,
            verbose=0,
            validation_data=(x_test, y_test) if len(x_test) > 0 else None,
        )

        train_preds = y_scaler.inverse_transform(
            model.predict(x_train, verbose=0).reshape(-1, 1)
        ).ravel()
        train_mae = float(np.mean(np.abs(train_preds - y[:split])))
        if len(x_test) > 0:
            test_preds = y_scaler.inverse_transform(
                model.predict(x_test, verbose=0).reshape(-1, 1)
            ).ravel()
            test_mae = float(np.mean(np.abs(test_preds - y[split:])))
        else:
            test_mae = train_mae
        return {
            "model": model,
            "scaler": x_scaler,
            "y_scaler": y_scaler,
            "input_size": x.shape[2],
            "lookback": lookback,
            "train_mae": round(train_mae, 4),
            "test_mae": round(test_mae, 4),
        }

    bundle = load_or_train_dl(paths, "tensorflow", _train)
    model = bundle["model"]
    scaler = bundle["scaler"]
    y_scaler = bundle["y_scaler"]
    last_x = scale_single_sequence(x[-1], scaler)
    raw_pred = float(model.predict(last_x, verbose=0)[0][0])
    prediction = inverse_scale_target(raw_pred, y_scaler)

    return {
        "status": "success",
        "prediction": round(prediction, 4),
        "current_price": round(float(df["close"].iloc[-1]), 4),
        "train_mae": bundle.get("train_mae"),
        "test_mae": bundle.get("test_mae"),
        "model": "LSTM (TensorFlow)",
        "backend": "tensorflow",
        "inference": "cached" if bundle.get("loaded_from_disk") else "trained",
    }


def train_pytorch_price_predictor(
    df: pd.DataFrame,
    symbol: str,
    days: int,
) -> dict:
    """PyTorch LSTM による価格予測"""
    import torch
    import torch.nn as nn

    from src.ml.model_store import dl_model_paths, load_or_train_dl

    lookback = settings.ml_lstm_lookback
    x, y = prepare_sequences(df, lookback)
    if len(x) < 30:
        return _insufficient()

    paths = dl_model_paths("price", symbol, "pytorch", days=days)

    def _train() -> dict[str, Any]:
        x_scaled, x_scaler = scale_sequences(x)
        y_scaled, y_scaler = scale_targets(y)
        split = max(int(len(x_scaled) * 0.8), len(x_scaled) - 5)
        x_train, x_test = x_scaled[:split], x_scaled[split:]
        y_train, y_test = y_scaled[:split], y_scaled[split:]

        input_size = x.shape[2]
        model = create_pytorch_lstm(input_size)
        criterion = nn.MSELoss()
        optimizer = torch.optim.Adam(model.parameters(), lr=0.001)

        x_tensor = torch.tensor(x_train, dtype=torch.float32)
        y_tensor = torch.tensor(y_train, dtype=torch.float32).unsqueeze(1)

        model.train()
        for _ in range(settings.ml_lstm_epochs):
            optimizer.zero_grad()
            out = model(x_tensor)
            loss = criterion(out, y_tensor)
            loss.backward()
            optimizer.step()

        model.eval()
        with torch.no_grad():
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

    bundle = load_or_train_dl(paths, "pytorch", _train)
    model = bundle["model"]
    scaler = bundle["scaler"]
    y_scaler = bundle["y_scaler"]
    last_x = scale_single_sequence(x[-1], scaler)

    import torch

    model.eval()
    with torch.no_grad():
        pred_tensor = model(torch.tensor(last_x, dtype=torch.float32))
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
