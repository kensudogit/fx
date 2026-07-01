"""
ATR・ボラティリティ計算モジュール

このモジュールは FX トレードにおけるボラティリティ（価格変動の激しさ）を
定量化する関数を提供する。

【ATR（Average True Range）とは】
J. Welles Wilder が 1978 年に考案したボラティリティ指標。
ギャップ（前日終値から当日始値へのジャンプ）を考慮した真の値幅（True Range）の
移動平均であり、1 日あたりの典型的な価格変動幅を表す。

ATR は価格の方向性を示さず、純粋にボラティリティのみを計測するため、
- ストップロスの設定（ATR × 1.5〜2.0 倍が一般的）
- ポジションサイズの調整
- 市場環境（高ボラ/低ボラ）の判定
などに活用される。

【日次ボラティリティとの違い】
- ATR: 高値・安値・前終値を用いた実際の値幅ベース（より直接的）
- 日次ボラティリティ: 日次リターンの標準偏差（統計的アプローチ）
両者は相補的な情報を提供するため、`calc_volatility_stats` で両方を計算する。
"""

import pandas as pd


def calc_atr(df: pd.DataFrame, period: int = 14) -> float:
    """ATR（Average True Range: 平均真の値幅）を計算する。

    【True Range（TR）の計算式】
    True Range は以下の 3 つの絶対値のうち最大値:
        TR = max(
            High - Low,          ← 当日の高安値幅（ギャップなしの場合）
            |High - Close(-1)|,  ← 当日高値と前日終値の差（上方ギャップ考慮）
            |Low  - Close(-1)|   ← 当日安値と前日終値の差（下方ギャップ考慮）
        )

    ギャップを考慮する理由:
    例えば前日終値 150.00、当日始値（高値）155.00、安値 154.00 の場合、
    High - Low = 1.00 だが実際の価格変動は 5.00（ギャップ分を含む）。
    TR はこれを正確に捕捉する。

    【ATR の計算式】
    ATR(t) = TR の n 期間単純移動平均の最終値
    ※ Wilder の元論文では指数移動平均を使用するが、
       本実装では簡便な単純移動平均（rolling mean）を採用している。

    例: USDJPY で ATR = 0.80 の場合
        → 1 日の典型的な値幅は 80 pips（0.01 pip の場合 0.80 / 0.01 = 80）

    Args:
        df:     "high"・"low"・"close" 列を含む OHLCV DataFrame。
        period: ATR の移動平均期間（デフォルト 14）。Wilder の標準設定。

    Returns:
        最新の ATR 値（float）。価格単位（例: USDJPY なら円）。
        計算に十分なデータがない（先頭の NaN）場合は 0.0 を返す。
    """
    high = df["high"]
    low = df["low"]
    close = df["close"]
    # True Range の 3 成分を計算して横方向の最大値を取る
    # pd.concat で列方向（axis=1）に結合し、各行の最大値（max(axis=1)）を True Range とする
    tr = pd.concat(
        [
            high - low,                        # 当日高安値幅
            (high - close.shift()).abs(),       # 高値と前日終値の差（上ギャップ考慮）
            (low - close.shift()).abs(),        # 安値と前日終値の差（下ギャップ考慮）
        ],
        axis=1,
    ).max(axis=1)
    # period 日間の True Range を単純移動平均して ATR を算出
    atr = tr.rolling(period).mean().iloc[-1]
    return float(atr) if pd.notna(atr) else 0.0


def calc_volatility_stats(df: pd.DataFrame, period: int = 14) -> dict:
    """ATR・ATR%・日次ボラティリティを含むボラティリティ統計を計算する。

    【各指標の意味と用途】

    1. ATR（平均真の値幅）
       - 意味: 直近 period 日間の平均的な日中値幅（価格単位）
       - 用途: ストップロス設定・ポジションサイズ計算

    2. ATR%（ATR の現在価格比）
       - 計算式: ATR / 現在価格 × 100
       - 意味: 現在価格に対するボラティリティの相対的な大きさ（%）
       - 用途: 異なる通貨ペアのボラティリティを横比較できる
       - 閾値の目安:
           < 0.5%: 超低ボラ（レンジ相場・薄商い）
           0.5〜1.0%: 通常のボラティリティ
           1.0〜1.5%: やや高ボラ（ストップ幅に注意）
           > 1.5%: 高ボラ（ストップ幅を広げ、ポジションサイズを縮小）
           > 2.0%: 極端な高ボラ（新規エントリー自粛を検討）

    3. 日次ボラティリティ（日次リターンの標準偏差）
       - 計算式: 日次リターン（前日比%変化）の標準偏差 × 100
       - 意味: 日次リターンの散らばり具合（リスクの統計的な尺度）
       - 用途: シャープレシオ計算・VaR 推定・ポートフォリオリスク計算
       - 年率換算: 日次ボラ × √252（取引日数）

    Args:
        df:     "high"・"low"・"close" 列を含む OHLCV DataFrame。
        period: ATR の計算期間（デフォルト 14）。

    Returns:
        以下のキーを持つ dict:
        - atr: ATR 値（価格単位、小数点 4 桁）
        - atr_percent: ATR を現在価格の% で表した値（小数点 3 桁）
        - daily_volatility: 日次リターンの標準偏差（%、小数点 3 桁）
        データが空の場合や close が 0 の場合は 0 を返す。
    """
    atr_val = calc_atr(df, period)
    close_val = float(df["close"].iloc[-1])
    # 日次リターン: (P(t) - P(t-1)) / P(t-1)（pct_change で計算）
    # NaN（最初の行）を除いてから標準偏差を算出
    daily_returns = df["close"].pct_change().dropna()
    return {
        "atr": round(atr_val, 4),
        # ATR%: 現在価格比での相対的ボラティリティ（通貨ペア間の横比較に有効）
        "atr_percent": round(atr_val / close_val * 100, 3) if close_val else 0,
        # 日次ボラ: 日次リターンの標準偏差（%）。リターンは小数→%変換のため×100
        "daily_volatility": round(float(daily_returns.std() * 100), 3) if len(daily_returns) else 0,
    }
