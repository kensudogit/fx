"""テクニカルシグナル抽出・バックテスト"""

import pandas as pd


def signals_from_row(row: pd.Series) -> list[dict]:
    signals = []

    if pd.notna(row.get("rsi")):
        if row["rsi"] < 30:
            signals.append({"indicator": "RSI", "signal": "buy", "value": round(row["rsi"], 2), "reason": "売られ過ぎ"})
        elif row["rsi"] > 70:
            signals.append({"indicator": "RSI", "signal": "sell", "value": round(row["rsi"], 2), "reason": "買われ過ぎ"})

    if pd.notna(row.get("macd")) and pd.notna(row.get("macd_signal")):
        if row["macd"] > row["macd_signal"]:
            signals.append({"indicator": "MACD", "signal": "buy", "reason": "MACDがシグナル線を上抜け"})
        elif row["macd"] < row["macd_signal"]:
            signals.append({"indicator": "MACD", "signal": "sell", "reason": "MACDがシグナル線を下抜け"})

    if pd.notna(row.get("bb_lower")) and pd.notna(row.get("bb_upper")):
        if row["close"] < row["bb_lower"]:
            signals.append({"indicator": "Bollinger Bands", "signal": "buy", "reason": "下限バンドタッチ"})
        elif row["close"] > row["bb_upper"]:
            signals.append({"indicator": "Bollinger Bands", "signal": "sell", "reason": "上限バンドタッチ"})

    if pd.notna(row.get("stoch_k")) and pd.notna(row.get("stoch_d")):
        if row["stoch_k"] < 20 and row["stoch_d"] < 20:
            signals.append({"indicator": "Stochastic", "signal": "buy", "reason": "売られ過ぎ圏"})
        elif row["stoch_k"] > 80 and row["stoch_d"] > 80:
            signals.append({"indicator": "Stochastic", "signal": "sell", "reason": "買われ過ぎ圏"})

    return signals


def aggregate_bias(signals: list[dict]) -> str:
    buy = sum(1 for s in signals if s["signal"] == "buy")
    sell = sum(1 for s in signals if s["signal"] == "sell")
    if buy > sell:
        return "buy"
    if sell > buy:
        return "sell"
    return "neutral"


def backtest_signals(result_df: pd.DataFrame) -> dict:
    """ルールベースシグナルの簡易バックテスト（翌日終値方向）"""
    trades: list[dict] = []

    for i in range(50, len(result_df) - 1):
        row = result_df.iloc[i]
        next_close = float(result_df.iloc[i + 1]["close"])
        current_close = float(row["close"])
        if current_close == 0:
            continue

        signals = signals_from_row(row)
        bias = aggregate_bias(signals)
        if bias == "neutral":
            continue

        ret_pct = (next_close - current_close) / current_close * 100
        win = (bias == "buy" and ret_pct > 0) or (bias == "sell" and ret_pct < 0)
        trades.append({"bias": bias, "return_pct": round(ret_pct if bias == "buy" else -ret_pct, 4), "win": win})

    if not trades:
        return {
            "total_trades": 0,
            "win_rate": 0,
            "avg_return_pct": 0,
            "buy_trades": 0,
            "sell_trades": 0,
            "message": "十分なシグナルがありません",
        }

    wins = sum(1 for t in trades if t["win"])
    return {
        "total_trades": len(trades),
        "win_rate": round(wins / len(trades) * 100, 1),
        "avg_return_pct": round(sum(t["return_pct"] for t in trades) / len(trades), 4),
        "buy_trades": sum(1 for t in trades if t["bias"] == "buy"),
        "sell_trades": sum(1 for t in trades if t["bias"] == "sell"),
        "period_bars": len(result_df),
    }
