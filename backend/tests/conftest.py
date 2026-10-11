"""
バックエンドテストスイート — 共有フィクスチャとパス設定

このモジュールは pytest の conftest.py メカニズムにより
`tests/` 配下の全テストへ自動的に適用される。

役割:
    - バックエンドルートを sys.path へ追加し `src.*` をインポート可能にする
    - テクニカル指標・シグナル・自動売買まわりで共用するダミーデータを提供する
    - 外部依存（DB / Redis / 外部 API）を持たないテストを書くための補助を提供する

FX トレード支援プラットフォーム（バックエンド）
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

# バックエンドルートを sys.path に追加してソースモジュールをインポート可能にする
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


# ─────────────────────────────────────────────────────────────────────────────
# 価格データ
# ─────────────────────────────────────────────────────────────────────────────

def make_ohlcv(n: int = 200, base: float = 150.0, seed: int = 42,
               drift: float = 0.0) -> pd.DataFrame:
    """再現性のある擬似 OHLCV データを生成する。

    テクニカル指標は最長 52 期間（一目均衡表）のウォームアップを必要とするため、
    既定では 200 行を生成する。価格は乱数シード固定のランダムウォーク。

    Args:
        n: 生成する行数。
        base: 初期価格（USDJPY を想定した 150.0 が既定）。
        seed: 乱数シード（テストの再現性のために固定する）。
        drift: 1 本あたりの平均リターン。正なら上昇、負なら下降トレンドになる。

    Returns:
        open / high / low / close / volume 列を持ち、日次 DatetimeIndex を備えた DataFrame。
    """
    rng = np.random.default_rng(seed)
    returns = rng.normal(drift, 0.005, n)
    close = base * np.cumprod(1 + returns)
    df = pd.DataFrame({
        "open": close * (1 + rng.uniform(-0.002, 0.002, n)),
        "high": close * (1 + rng.uniform(0.001, 0.005, n)),
        "low": close * (1 - rng.uniform(0.001, 0.005, n)),
        "close": close,
        "volume": rng.integers(1000, 50000, n).astype(float),
    })
    df.index = pd.date_range(end=pd.Timestamp("2026-01-01"), periods=n, freq="D")
    return df


@pytest.fixture(scope="session")
def ohlcv() -> pd.DataFrame:
    """200 行の擬似 OHLCV データ（レンジ相場）。"""
    return make_ohlcv()


@pytest.fixture(scope="session")
def ohlcv_uptrend() -> pd.DataFrame:
    """明確な上昇トレンドを持つ 200 行の擬似 OHLCV データ。"""
    return make_ohlcv(drift=0.004, seed=7)


@pytest.fixture(scope="session")
def ohlcv_downtrend() -> pd.DataFrame:
    """明確な下降トレンドを持つ 200 行の擬似 OHLCV データ。"""
    return make_ohlcv(drift=-0.004, seed=11)


@pytest.fixture(scope="session")
def indicators_df(ohlcv: pd.DataFrame) -> pd.DataFrame:
    """テクニカル指標を計算済みの OHLCV DataFrame（セッション内で 1 回だけ計算）。"""
    from src.analysis.technical import compute_all_indicators
    return compute_all_indicators(ohlcv.copy())


@pytest.fixture
def latest_row(indicators_df: pd.DataFrame) -> pd.Series:
    """指標計算済みデータの、NaN を含まない最新行。"""
    return indicators_df.dropna().iloc[-1]


# ─────────────────────────────────────────────────────────────────────────────
# 設定の一時変更
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def override_settings(monkeypatch):
    """`src.config.settings` のフィールドを一時的に差し替えるヘルパーを返す。

    使い方::

        def test_x(override_settings):
            override_settings(openai_api_key="dummy", jwt_expire_hours=1)

    テスト終了時に monkeypatch が自動的に元の値へ戻す。
    """
    from src.config import settings

    def _override(**kwargs):
        for key, value in kwargs.items():
            monkeypatch.setattr(settings, key, value, raising=False)
        return settings

    return _override
