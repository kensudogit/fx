"""
プレゼンテーション向けテストスイート — 共有フィクスチャ

このモジュールは全テストクラスで共通して使用するフィクスチャを定義する。
pytest の conftest.py メカニズムにより自動的に全テストモジュールに適用される。

フィクスチャの概要:
    - sample_ohlcv_df: テクニカル指標計算用の模擬価格データ (200 行)
    - sample_signal_row: シグナル生成テスト用の指標値 Series
    - sample_closed_positions: PnL 集計テスト用の決済済みポジションリスト
    - fx_app: FastAPI TestClient (認証バイパス付き)
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

# バックエンドルートを sys.path に追加してソースモジュールをインポート可能にする
ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


# ─────────────────────────────────────────────────────────────────────────────
# 価格データフィクスチャ
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture(scope="session")
def sample_ohlcv_df() -> pd.DataFrame:
    """200 行の擬似 OHLCV（始値・高値・安値・終値・出来高）データを生成する。

    テクニカル指標のウォームアップ期間（最大 52 期間の一目均衡表）を満たすため、
    200 行以上のデータを用意している。価格はランダムウォークで生成する。

    Returns:
        pd.DataFrame: open / high / low / close / volume 列を持つ DataFrame。
    """
    np.random.seed(42)
    n = 200
    base_price = 150.0  # USDJPY 想定
    returns = np.random.normal(0, 0.005, n)  # 日次変動率 0.5% の正規分布
    close_prices = base_price * np.cumprod(1 + returns)

    df = pd.DataFrame({
        "open":   close_prices * (1 + np.random.uniform(-0.002, 0.002, n)),
        "high":   close_prices * (1 + np.random.uniform(0.001, 0.005, n)),
        "low":    close_prices * (1 - np.random.uniform(0.001, 0.005, n)),
        "close":  close_prices,
        "volume": np.random.randint(1000, 50000, n).astype(float),
    })
    df.index = pd.date_range(end=pd.Timestamp.today(), periods=n, freq="D")
    return df


@pytest.fixture(scope="session")
def sample_ohlcv_with_indicators(sample_ohlcv_df: pd.DataFrame) -> pd.DataFrame:
    """テクニカル指標を計算済みの OHLCV DataFrame を返す。

    シグナル生成・バックテストのテストで共用するため、
    セッションスコープで1回だけ計算する。

    Returns:
        pd.DataFrame: テクニカル指標列（rsi, macd, bb_*, stoch_* など）追加済み。
    """
    from src.analysis.technical import compute_all_indicators
    return compute_all_indicators(sample_ohlcv_df.copy())


@pytest.fixture
def sample_signal_row(sample_ohlcv_with_indicators: pd.DataFrame) -> pd.Series:
    """シグナル生成テスト用に指標計算済みの1行を返す（NaN を除く末尾行）。

    Returns:
        pd.Series: NaN のない最新行の指標値。
    """
    df = sample_ohlcv_with_indicators.dropna()
    return df.iloc[-1]


# ─────────────────────────────────────────────────────────────────────────────
# PnL テスト用フィクスチャ
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture(scope="session")
def sample_closed_positions() -> list[dict]:
    """PnL 集計テスト用の決済済みポジションリストを返す。

    買いポジション (利益) x3、売りポジション (損失) x1、
    売りポジション (利益) x1 の混合データ。

    Returns:
        list[dict]: 決済済みポジションの辞書リスト。
    """
    return [
        {
            "id": "p1",
            "symbol": "USDJPY",
            "side": "buy",
            "units": 10000,
            "entry_price": 148.00,
            "close_price": 149.50,  # 150 pips 利益
            "realized_pnl_usd": None,  # テスト内で計算
        },
        {
            "id": "p2",
            "symbol": "USDJPY",
            "side": "buy",
            "units": 10000,
            "entry_price": 150.00,
            "close_price": 148.00,  # 200 pips 損失
            "realized_pnl_usd": None,
        },
        {
            "id": "p3",
            "symbol": "EURUSD",
            "side": "buy",
            "units": 10000,
            "entry_price": 1.0800,
            "close_price": 1.0850,  # 50 pips 利益
            "realized_pnl_usd": None,
        },
        {
            "id": "p4",
            "symbol": "EURUSD",
            "side": "sell",
            "units": 10000,
            "entry_price": 1.0900,
            "close_price": 1.0850,  # 50 pips 利益
            "realized_pnl_usd": None,
        },
        {
            "id": "p5",
            "symbol": "GBPUSD",
            "side": "buy",
            "units": 5000,
            "entry_price": 1.2700,
            "close_price": 1.2750,  # 50 pips 利益
            "realized_pnl_usd": None,
        },
    ]


# ─────────────────────────────────────────────────────────────────────────────
# FastAPI TestClient フィクスチャ
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture(scope="session")
def fx_app():
    """FastAPI アプリケーションの TestClient を返す。

    DB 接続・外部 API を必要とするエンドポイントは認証ミドルウェアをバイパスして
    基本的な応答検証のみ行う。

    Returns:
        httpx.Client 互換の starlette.testclient.TestClient インスタンス。
    """
    try:
        from fastapi.testclient import TestClient
        from src.main import app
        return TestClient(app, raise_server_exceptions=False)
    except Exception:
        return None
