import numpy as np
import pandas as pd


def generate_sample_ohlcv(
    symbol: str = "USDJPY",
    days: int = 200,
    base_price: float = 150.0,
) -> pd.DataFrame:
    """サンプルOHLCVデータを生成"""
    np.random.seed(42)
    dates = pd.date_range(end=pd.Timestamp.now(), periods=days, freq="B")

    returns = np.random.normal(0.0002, 0.005, days)
    close_prices = base_price * np.cumprod(1 + returns)

    data = []
    for i, date in enumerate(dates):
        close = close_prices[i]
        daily_range = close * np.random.uniform(0.003, 0.012)
        high = close + daily_range * np.random.uniform(0.3, 0.7)
        low = close - daily_range * np.random.uniform(0.3, 0.7)
        open_price = low + (high - low) * np.random.uniform(0.2, 0.8)
        volume = int(np.random.uniform(100000, 500000))

        data.append(
            {
                "timestamp": date,
                "open": round(open_price, 3),
                "high": round(high, 3),
                "low": round(low, 3),
                "close": round(close, 3),
                "volume": volume,
            }
        )

    return pd.DataFrame(data)


SYMBOL_BASE_PRICES = {
    "USDJPY": 150.0,
    "EURUSD": 1.08,
    "GBPUSD": 1.27,
    "AUDUSD": 0.65,
}
