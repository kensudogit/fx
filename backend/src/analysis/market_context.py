"""シンボル単位の OHLCV + テクニカル指標（リクエスト内共有用）"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from src.analysis.technical import compute_all_indicators
from src.analysis.volatility import calc_atr
from src.data.market_data import get_ohlcv_data


@dataclass
class MarketContext:
    symbol: str
    days: int
    source: str
    result_df: pd.DataFrame

    @property
    def price(self) -> float:
        return float(self.result_df["close"].iloc[-1])

    @property
    def atr(self) -> float | None:
        return calc_atr(self.result_df)

    @classmethod
    def load(cls, symbol: str, days: int = 200) -> MarketContext:
        df, source = get_ohlcv_data(symbol, days)
        result_df = compute_all_indicators(df)
        return cls(symbol.upper(), days, source, result_df)
