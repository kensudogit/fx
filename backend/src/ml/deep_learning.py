"""ディープラーニングモジュール - TensorFlow / PyTorch"""

import numpy as np


def check_ml_frameworks() -> dict:
    """インストール済みMLフレームワークの確認"""
    frameworks = {}

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


def create_lstm_model(input_shape: tuple, units: int = 50):
    """TensorFlow LSTM モデル構築（価格予測用）"""
    import tensorflow as tf

    model = tf.keras.Sequential([
        tf.keras.layers.LSTM(units, return_sequences=True, input_shape=input_shape),
        tf.keras.layers.Dropout(0.2),
        tf.keras.layers.LSTM(units // 2),
        tf.keras.layers.Dropout(0.2),
        tf.keras.layers.Dense(1),
    ])
    model.compile(optimizer="adam", loss="mse", metrics=["mae"])
    return model


def create_pytorch_lstm(input_size: int, hidden_size: int = 50, num_layers: int = 2):
    """PyTorch LSTM モデル構築（価格予測用）"""
    import torch
    import torch.nn as nn

    class LSTMModel(nn.Module):
        def __init__(self):
            super().__init__()
            self.lstm = nn.LSTM(input_size, hidden_size, num_layers, batch_first=True, dropout=0.2)
            self.fc = nn.Linear(hidden_size, 1)

        def forward(self, x):
            out, _ = self.lstm(x)
            return self.fc(out[:, -1, :])

    return LSTMModel()
