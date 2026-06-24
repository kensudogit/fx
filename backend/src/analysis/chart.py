"""matplotlib チャート生成"""

import io

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import pandas as pd

from src.analysis.technical import compute_all_indicators


def generate_technical_chart(df: pd.DataFrame, symbol: str, indicator: str = "price") -> bytes:
    """テクニカル分析チャートを PNG バイト列で生成"""
    result = compute_all_indicators(df)

    fig, axes = plt.subplots(
        3 if indicator == "all" else 1,
        1,
        figsize=(14, 10 if indicator == "all" else 5),
        gridspec_kw={"height_ratios": [3, 1, 1]} if indicator == "all" else None,
    )

    if indicator != "all":
        axes = [axes]

    ax_price = axes[0]
    dates = result["timestamp"]

    ax_price.plot(dates, result["close"], label="Close", color="#e8edf4", linewidth=1.5)
    ax_price.plot(dates, result["sma_20"], label="SMA20", color="#f59e0b", linewidth=1)
    ax_price.plot(dates, result["sma_50"], label="SMA50", color="#8b5cf6", linewidth=1)
    ax_price.fill_between(dates, result["bb_upper"], result["bb_lower"], alpha=0.1, color="#3b82f6")
    ax_price.set_title(f"{symbol} - Technical Analysis", color="white", fontsize=14)
    ax_price.legend(loc="upper left", fontsize=8)
    ax_price.xaxis.set_major_formatter(mdates.DateFormatter("%m/%d"))
    ax_price.grid(True, alpha=0.2)

    if indicator == "all" and len(axes) > 2:
        ax_rsi = axes[1]
        ax_rsi.plot(dates, result["rsi"], color="#8b5cf6", linewidth=1.5)
        ax_rsi.axhline(70, color="#ef4444", linestyle="--", alpha=0.5)
        ax_rsi.axhline(30, color="#22c55e", linestyle="--", alpha=0.5)
        ax_rsi.set_ylabel("RSI")
        ax_rsi.set_ylim(0, 100)
        ax_rsi.grid(True, alpha=0.2)

        ax_macd = axes[2]
        ax_macd.bar(dates, result["macd_histogram"], color="#3b82f6", alpha=0.5, width=0.8)
        ax_macd.plot(dates, result["macd"], color="#f59e0b", linewidth=1)
        ax_macd.plot(dates, result["macd_signal"], color="#ef4444", linewidth=1)
        ax_macd.set_ylabel("MACD")
        ax_macd.grid(True, alpha=0.2)

    fig.patch.set_facecolor("#1e2a3a")
    for ax in axes:
        ax.set_facecolor("#1e2a3a")
        ax.tick_params(colors="#8b9cb3")
        ax.yaxis.label.set_color("#8b9cb3")
        for spine in ax.spines.values():
            spine.set_color("#2d3f56")

    plt.tight_layout()
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=120, facecolor=fig.get_facecolor())
    plt.close(fig)
    buf.seek(0)
    return buf.read()
