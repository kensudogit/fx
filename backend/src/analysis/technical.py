import numpy as np
import pandas as pd


def moving_average(series: pd.Series, period: int = 20) -> pd.Series:
    """単純移動平均線 (SMA)"""
    return series.rolling(window=period).mean()


def exponential_moving_average(series: pd.Series, period: int = 20) -> pd.Series:
    """指数移動平均線 (EMA)"""
    return series.ewm(span=period, adjust=False).mean()


def bollinger_bands(
    series: pd.Series, period: int = 20, std_dev: float = 2.0
) -> dict[str, pd.Series]:
    """ボリンジャーバンド"""
    middle = moving_average(series, period)
    std = series.rolling(window=period).std()
    upper = middle + (std * std_dev)
    lower = middle - (std * std_dev)
    return {"upper": upper, "middle": middle, "lower": lower}


def macd(
    series: pd.Series,
    fast_period: int = 12,
    slow_period: int = 26,
    signal_period: int = 9,
) -> dict[str, pd.Series]:
    """MACD (Moving Average Convergence Divergence)"""
    ema_fast = exponential_moving_average(series, fast_period)
    ema_slow = exponential_moving_average(series, slow_period)
    macd_line = ema_fast - ema_slow
    signal_line = exponential_moving_average(macd_line, signal_period)
    histogram = macd_line - signal_line
    return {"macd": macd_line, "signal": signal_line, "histogram": histogram}


def rsi(series: pd.Series, period: int = 14) -> pd.Series:
    """RSI (Relative Strength Index)"""
    delta = series.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = (-delta).where(delta < 0, 0.0)
    avg_gain = gain.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def stochastic(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    k_period: int = 14,
    d_period: int = 3,
) -> dict[str, pd.Series]:
    """ストキャスティクス (%K, %D)"""
    lowest_low = low.rolling(window=k_period).min()
    highest_high = high.rolling(window=k_period).max()
    k = 100 * (close - lowest_low) / (highest_high - lowest_low)
    d = k.rolling(window=d_period).mean()
    return {"k": k, "d": d}


def ichimoku(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    tenkan_period: int = 9,
    kijun_period: int = 26,
    senkou_b_period: int = 52,
    displacement: int = 26,
) -> dict[str, pd.Series]:
    """一目均衡表"""
    tenkan = (high.rolling(tenkan_period).max() + low.rolling(tenkan_period).min()) / 2
    kijun = (high.rolling(kijun_period).max() + low.rolling(kijun_period).min()) / 2
    senkou_a = ((tenkan + kijun) / 2).shift(displacement)
    senkou_b = (
        (high.rolling(senkou_b_period).max() + low.rolling(senkou_b_period).min()) / 2
    ).shift(displacement)
    chikou = close.shift(-displacement)
    return {
        "tenkan": tenkan,
        "kijun": kijun,
        "senkou_a": senkou_a,
        "senkou_b": senkou_b,
        "chikou": chikou,
    }


def compute_all_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """全テクニカル指標を一括計算"""
    result = df.copy()
    close = df["close"]
    high = df["high"]
    low = df["low"]

    result["sma_20"] = moving_average(close, 20)
    result["sma_50"] = moving_average(close, 50)
    result["ema_12"] = exponential_moving_average(close, 12)
    result["ema_26"] = exponential_moving_average(close, 26)

    bb = bollinger_bands(close)
    result["bb_upper"] = bb["upper"]
    result["bb_middle"] = bb["middle"]
    result["bb_lower"] = bb["lower"]

    macd_data = macd(close)
    result["macd"] = macd_data["macd"]
    result["macd_signal"] = macd_data["signal"]
    result["macd_histogram"] = macd_data["histogram"]

    result["rsi"] = rsi(close)

    stoch = stochastic(high, low, close)
    result["stoch_k"] = stoch["k"]
    result["stoch_d"] = stoch["d"]

    ichi = ichimoku(high, low, close)
    for key, series in ichi.items():
        result[f"ichi_{key}"] = series

    return result


def series_to_list(series: pd.Series) -> list[float | None]:
    """pandas Series を JSON シリアライズ可能なリストに変換"""
    return [None if pd.isna(v) else round(float(v), 6) for v in series]
