"""ウォークフォワード分析"""

import pandas as pd

from src.analysis.signals import backtest_signals
from src.analysis.technical import compute_all_indicators
from src.data.market_data import get_ohlcv_data


def run_walk_forward(
    symbol: str,
    days: int = 365,
    train_bars: int = 120,
    test_bars: int = 40,
    step_bars: int = 40,
) -> dict:
    df, source = get_ohlcv_data(symbol, days)
    result_df = compute_all_indicators(df)

    if len(result_df) < train_bars + test_bars + 20:
        return {"status": "error", "message": "データ不足（ウォークフォワードには最低約180日必要）"}

    windows: list[dict] = []
    start = 0
    idx = 0
    while start + train_bars + test_bars <= len(result_df):
        train_slice = result_df.iloc[start : start + train_bars]
        test_slice = result_df.iloc[start + train_bars : start + train_bars + test_bars]

        train_bt = backtest_signals(train_slice)
        test_bt = backtest_signals(test_slice)

        windows.append({
            "window": idx + 1,
            "train_start": str(train_slice["timestamp"].iloc[0])[:10],
            "train_end": str(train_slice["timestamp"].iloc[-1])[:10],
            "test_start": str(test_slice["timestamp"].iloc[0])[:10],
            "test_end": str(test_slice["timestamp"].iloc[-1])[:10],
            "in_sample": {
                "win_rate": train_bt["win_rate"],
                "total_trades": train_bt["total_trades"],
                "avg_return_pct": train_bt["avg_return_pct"],
            },
            "out_of_sample": {
                "win_rate": test_bt["win_rate"],
                "total_trades": test_bt["total_trades"],
                "avg_return_pct": test_bt["avg_return_pct"],
            },
        })
        start += step_bars
        idx += 1

    if not windows:
        return {"status": "error", "message": "ウィンドウを生成できませんでした"}

    oos_win = [w["out_of_sample"]["win_rate"] for w in windows if w["out_of_sample"]["total_trades"] > 0]
    is_win = [w["in_sample"]["win_rate"] for w in windows if w["in_sample"]["total_trades"] > 0]
    oos_ret = [w["out_of_sample"]["avg_return_pct"] for w in windows if w["out_of_sample"]["total_trades"] > 0]

    avg_oos = sum(oos_win) / len(oos_win) if oos_win else 0
    avg_is = sum(is_win) / len(is_win) if is_win else 0
    degradation = round(avg_is - avg_oos, 1)

    if degradation < 10 and avg_oos >= 45:
        robustness = "good"
        label = "堅牢 — OOSパフォーマンス良好"
    elif degradation < 20:
        robustness = "moderate"
        label = "中程度 — 過学習の可能性あり"
    else:
        robustness = "weak"
        label = "弱い — IS/OOS乖離が大きい"

    return {
        "status": "success",
        "symbol": symbol.upper(),
        "source": source,
        "train_bars": train_bars,
        "test_bars": test_bars,
        "step_bars": step_bars,
        "windows": windows,
        "summary": {
            "window_count": len(windows),
            "avg_in_sample_win_rate": round(avg_is, 1),
            "avg_out_of_sample_win_rate": round(avg_oos, 1),
            "avg_oos_return_pct": round(sum(oos_ret) / len(oos_ret), 4) if oos_ret else 0,
            "is_oos_degradation_pct": degradation,
            "robustness": robustness,
            "robustness_label": label,
        },
    }
