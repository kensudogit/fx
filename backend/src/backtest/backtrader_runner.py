"""Backtrader による戦略バックテスト"""

import pandas as pd

from src.analysis.technical import compute_all_indicators
from src.data.market_data import get_ohlcv_data


def run_backtrader_backtest(symbol: str, days: int = 200, cash: float = 10000) -> dict:
    try:
        import backtrader as bt
    except ImportError:
        return {"status": "error", "message": "backtrader がインストールされていません"}

    df, source = get_ohlcv_data(symbol, days)
    if len(df) < 60:
        return {"status": "error", "message": "データ不足"}

    result_df = compute_all_indicators(df)
    data = result_df[["timestamp", "open", "high", "low", "close", "volume", "rsi", "macd", "macd_signal"]].copy()
    data = data.dropna(subset=["close", "rsi", "macd", "macd_signal"])
    data = data.set_index("timestamp")
    data.index = pd.to_datetime(data.index)

    class RsiMacdStrategy(bt.Strategy):
        params = dict(rsi_low=30, rsi_high=70)

        def __init__(self):
            self.rsi = bt.indicators.RSI(self.data.close, period=14)
            self.macd = bt.indicators.MACD(self.data.close)

        def next(self):
            if self.position:
                if self.rsi[0] > self.params.rsi_high or self.macd.macd[0] < self.macd.signal[0]:
                    self.close()
            elif self.rsi[0] < self.params.rsi_low and self.macd.macd[0] > self.macd.signal[0]:
                self.buy()

    cerebro = bt.Cerebro()
    feed = bt.feeds.PandasData(dataname=data)
    cerebro.adddata(feed)
    cerebro.addstrategy(RsiMacdStrategy)
    cerebro.broker.setcash(cash)
    cerebro.broker.setcommission(commission=0.0002)
    start_value = cerebro.broker.getvalue()
    results = cerebro.run()
    end_value = cerebro.broker.getvalue()
    strat = results[0]
    trades = strat.analyzers.trades if hasattr(strat, "analyzers") else None

    total_return = (end_value - start_value) / start_value * 100
    return {
        "status": "success",
        "engine": "backtrader",
        "symbol": symbol.upper(),
        "source": source,
        "initial_cash": cash,
        "final_value": round(end_value, 2),
        "total_return_pct": round(total_return, 2),
        "bars": len(data),
        "strategy": "RSI(30/70) + MACD crossover",
    }
