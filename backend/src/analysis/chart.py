"""
matplotlib チャート生成モジュール

このモジュールは FX テクニカル分析チャートを PNG 画像（バイト列）として生成する。
価格ライン・移動平均線・ボリンジャーバンド・RSI・MACD を1枚の図にまとめて描画し、
フロントエンドやレポートへ埋め込み可能な形式で返す。

生成されるチャート構成（indicator="all" の場合）:
  - 上段パネル: 終値・SMA20/SMA50・ボリンジャーバンド
  - 中段パネル: RSI（14期間）
  - 下段パネル: MACD ライン・シグナルライン・ヒストグラム
"""

import io

import matplotlib

# GUI バックエンドを使用しないよう Agg（ファイル出力専用）に切り替える。
# サーバーサイドで GUI なしに PNG を生成する際に必須の設定。
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import pandas as pd

from src.analysis.technical import compute_all_indicators


def generate_technical_chart(df: pd.DataFrame, symbol: str, indicator: str = "price") -> bytes:
    """テクニカル分析チャートを PNG バイト列で生成する。

    OHLCV データフレームからテクニカル指標を計算し、matplotlib で描画した後、
    PNG 形式のバイト列として返す。指標の種類（indicator 引数）によって
    サブプロットの構成が変わる。

    Args:
        df: OHLCV 形式の pandas DataFrame。
            必要カラム: open, high, low, close, volume, timestamp。
        symbol: 通貨ペアシンボル（例: "USDJPY"）。チャートタイトルに使用。
        indicator: 描画するパネルの指定。
            "price"  → 価格パネルのみ（デフォルト）。
            "all"    → 価格・RSI・MACD の3パネル構成。

    Returns:
        PNG 画像データのバイト列。HTTP レスポンスや埋め込み用に直接使用可能。

    Raises:
        KeyError: df に必要なカラムが存在しない場合。
        ValueError: df が空の場合。
    """
    # テクニカル指標を一括計算する（SMA・EMA・BB・RSI・MACD 等）
    result = compute_all_indicators(df)

    # indicator="all" の場合は3段パネル、それ以外は価格のみの1段パネルを作成する。
    # height_ratios=[3, 1, 1] で上段（価格）を大きく、中・下段（オシレーター）を小さく配置。
    fig, axes = plt.subplots(
        3 if indicator == "all" else 1,
        1,
        figsize=(14, 10 if indicator == "all" else 5),
        gridspec_kw={"height_ratios": [3, 1, 1]} if indicator == "all" else None,
    )

    # 1パネル構成の場合、axes はスカラーになるため、
    # 以降のループ処理を統一するためリストに変換する。
    if indicator != "all":
        axes = [axes]

    # ---- 上段パネル: 価格チャート ----
    ax_price = axes[0]
    dates = result["timestamp"]

    # 終値ライン（薄いホワイト系）
    ax_price.plot(dates, result["close"], label="Close", color="#e8edf4", linewidth=1.5)

    # SMA20（20日単純移動平均）: 短期トレンドの方向感を確認するための指標
    # 計算式: SMA20 = 直近20本の終値の算術平均
    ax_price.plot(dates, result["sma_20"], label="SMA20", color="#f59e0b", linewidth=1)

    # SMA50（50日単純移動平均）: 中期トレンドの方向感を確認するための指標
    # 計算式: SMA50 = 直近50本の終値の算術平均
    ax_price.plot(dates, result["sma_50"], label="SMA50", color="#8b5cf6", linewidth=1)

    # ボリンジャーバンド（BB）の上限・下限を半透明で塗りつぶす。
    # BB = SMA20 ± 2σ（標準偏差×2）で計算され、価格の変動範囲（±2σ内に約95%の値が収まる）を示す。
    # バンド幅が広いほどボラティリティが高く、狭いほどスクイーズ（価格圧縮）状態を示す。
    ax_price.fill_between(dates, result["bb_upper"], result["bb_lower"], alpha=0.1, color="#3b82f6")

    ax_price.set_title(f"{symbol} - Technical Analysis", color="white", fontsize=14)
    ax_price.legend(loc="upper left", fontsize=8)
    ax_price.xaxis.set_major_formatter(mdates.DateFormatter("%m/%d"))
    ax_price.grid(True, alpha=0.2)

    # ---- 中段パネル: RSI（Relative Strength Index: 相対力指数） ----
    if indicator == "all" and len(axes) > 2:
        ax_rsi = axes[1]
        # RSI ライン: 0〜100 の範囲で価格のモメンタム（勢い）を示す。
        # 計算式: RSI = 100 - (100 / (1 + RS))  ※ RS = 上昇幅平均 / 下落幅平均（期間14）
        ax_rsi.plot(dates, result["rsi"], color="#8b5cf6", linewidth=1.5)

        # 70ライン（赤破線）: 買われすぎゾーンの境界。70超で過熱感あり、反落のサイン。
        ax_rsi.axhline(70, color="#ef4444", linestyle="--", alpha=0.5)
        # 30ライン（緑破線）: 売られすぎゾーンの境界。30未満で過売れ感あり、反発のサイン。
        ax_rsi.axhline(30, color="#22c55e", linestyle="--", alpha=0.5)
        ax_rsi.set_ylabel("RSI")
        ax_rsi.set_ylim(0, 100)
        ax_rsi.grid(True, alpha=0.2)

        # ---- 下段パネル: MACD（Moving Average Convergence Divergence） ----
        ax_macd = axes[2]
        # MACD ヒストグラム: MACD ライン - シグナルラインの差をバーで表示。
        # ゼロラインを上回る → 上昇モメンタム加速、下回る → 下降モメンタム加速を示す。
        ax_macd.bar(dates, result["macd_histogram"], color="#3b82f6", alpha=0.5, width=0.8)

        # MACD ライン: EMA12 - EMA26（短期EMAと長期EMAの差）
        # ゼロラインを上抜け → ゴールデンクロス的なシグナル
        ax_macd.plot(dates, result["macd"], color="#f59e0b", linewidth=1)

        # シグナルライン: MACD の EMA9（MACD のなめらかな平均）
        # MACD がシグナルを上抜けると買い、下抜けると売りのサイン。
        ax_macd.plot(dates, result["macd_signal"], color="#ef4444", linewidth=1)
        ax_macd.set_ylabel("MACD")
        ax_macd.grid(True, alpha=0.2)

    # ---- チャート全体のダークテーマ設定 ----
    # 図全体の背景色を濃紺系ダークカラーに統一する
    fig.patch.set_facecolor("#1e2a3a")
    for ax in axes:
        ax.set_facecolor("#1e2a3a")
        # 軸目盛りラベルの文字色を薄青系に設定
        ax.tick_params(colors="#8b9cb3")
        ax.yaxis.label.set_color("#8b9cb3")
        # 軸の枠線（スパイン）をダーク系の色に設定
        for spine in ax.spines.values():
            spine.set_color("#2d3f56")

    plt.tight_layout()

    # PNG バイト列として出力するためのインメモリバッファを使用する。
    # dpi=120 で高解像度（Web 表示に適切な品質）で保存する。
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=120, facecolor=fig.get_facecolor())
    plt.close(fig)  # メモリリークを防ぐため、使い終わった Figure を明示的に閉じる
    buf.seek(0)
    return buf.read()
