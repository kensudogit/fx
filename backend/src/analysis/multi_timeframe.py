"""
マルチタイムフレームトレンド分析モジュール

異なる時間軸（日足・4時間足）のトレンド方向を個別に算出し、
両者の整合性（アライメント）を評価することで、
トレードエントリーの信頼性を高めるための分析機能を提供する。

マルチタイムフレーム分析（MTF）の考え方:
  FX トレードでは、上位の時間足（日足）と下位の時間足（4時間足）の
  トレンド方向が一致している場合にエントリーの精度が高まるとされる。

  日足と4時間足が同方向: 強いトレンドシグナル（高信頼エントリー）
  日足が上昇・4時間足が中立: 上昇バイアス（慎重にロング狙い）
  両者が逆方向: トレード回避推奨（レンジ崩れのリスク）

キャッシュ戦略:
  MTF 分析は OHLCV データ取得と指標計算を2回行うため比較的コストが高い。
  settings.mtf_cache_ttl_seconds で設定されたTTL（例: 300秒）の間、
  計算結果をインメモリキャッシュに保存して再計算を防ぐ。
"""

import pandas as pd

from src.analysis.signals import aggregate_bias, signals_from_row
from src.analysis.technical import compute_all_indicators
from src.config import settings
from src.data.market_data import get_ohlcv_data
from src.infra.analysis_cache import cache_get, cache_key, cache_put


def _trend_from_df(df: pd.DataFrame) -> dict:
    """単一時間足の OHLCV DataFrame からトレンド情報を抽出する内部ヘルパー関数。

    トレンド判定ロジック（MA 整列チェック）:
      FX において、単純移動平均線の整列状態はトレンドの方向と強さを示す基本指標。

      上昇トレンド（bullish）:
        - 価格 > SMA20 > SMA50: 完全な上昇整列（最強の上昇シグナル）
        - 価格 > SMA50（のみ）: 中期MA上だが短期未整列（上昇寄り）

      下降トレンド（bearish）:
        - 価格 < SMA20 < SMA50: 完全な下降整列（最強の下降シグナル）
        - 価格 < SMA50（のみ）: 中期MA下だが短期未整列（下降寄り）

      中立（neutral）:
        - 上記いずれも満たさない（SMA50 と同水準付近）

    signals_from_row() による追加シグナル:
      MA 整列に加えて RSI・MACD 等の複合シグナルから
      aggregate_bias() でシグナルバイアスを算出し、メタ情報として付与する。

    Args:
        df: 単一時間足の OHLCV 形式 DataFrame。
            必要カラム: open, high, low, close, volume, timestamp。

    Returns:
        以下のキーを持つ辞書:
          trend: "bullish" | "bearish" | "neutral"
          label: 日本語のトレンド方向説明
          close: 最新終値（小数点4桁）
          sma_20: SMA20 値（小数点4桁）
          sma_50: SMA50 値（小数点4桁）
          rsi: 最新 RSI 値（小数点1桁、または None）
          signal_bias: signals_from_row() + aggregate_bias() の複合バイアス
          bars: 分析に使用したバー（ローソク足）数
    """
    # テクニカル指標を一括計算する
    result = compute_all_indicators(df)
    # 最終行（最新バー）の指標値を取得する
    latest = result.iloc[-1]

    close = float(latest["close"])
    # SMA20・SMA50 を取得（NaN の場合は現在終値で代替してMA比較を可能にする）
    sma20 = float(latest["sma_20"]) if pd.notna(latest["sma_20"]) else close
    sma50 = float(latest["sma_50"]) if pd.notna(latest["sma_50"]) else close

    # ---- MA 整列によるトレンド判定 ----
    if close > sma20 > sma50:
        # 完全上昇整列: 価格がSMA20・SMA50の両方を上回る（最も強い上昇シグナル）
        trend = "bullish"
        label = "上昇"
    elif close < sma20 < sma50:
        # 完全下降整列: 価格がSMA20・SMA50の両方を下回る（最も強い下降シグナル）
        trend = "bearish"
        label = "下降"
    elif close > sma50:
        # 中期MA（SMA50）より上だが、SMA20との整列なし: 上昇寄りの弱いシグナル
        trend = "bullish"
        label = "上昇寄り"
    elif close < sma50:
        # 中期MA（SMA50）より下だが、SMA20との整列なし: 下降寄りの弱いシグナル
        trend = "bearish"
        label = "下降寄り"
    else:
        # SMA50 と同水準付近: 方向感なし
        trend = "neutral"
        label = "中立"

    # RSI・MACD 等の複合シグナルからバイアスを算出する
    signals = signals_from_row(latest)
    return {
        "trend": trend,
        "label": label,
        "close": round(close, 4),
        "sma_20": round(sma20, 4),
        "sma_50": round(sma50, 4),
        # RSI が NaN の場合（データ不足）は None を返す
        "rsi": round(float(latest["rsi"]), 1) if pd.notna(latest["rsi"]) else None,
        # 複数テクニカルシグナルを集約したバイアス値
        "signal_bias": aggregate_bias(signals),
        "bars": len(result),
    }


def analyze_multi_timeframe(symbol: str) -> dict:
    """日足・4時間足の2時間軸でトレンドを分析し、整合性（アライメント）を評価する。

    処理フロー:
      1. キャッシュを確認し、有効なキャッシュがあればそれを返す。
      2. 日足データ（200日分）と4時間足データ（60日分）を取得する。
      3. 各時間足のトレンドを _trend_from_df() で個別に判定する。
      4. 両時間足のトレンドを比較してアライメント（整合性）を判定する。
      5. 結果をキャッシュに保存して返す。

    アライメント判定ロジック（整合性チェック）:
      "bullish" または "bearish"（完全一致）:
        日足と4時間足が同じトレンド方向（かつ neutral でない）場合。
        → 最も信頼性の高いエントリーシグナル。
        例: 日足=上昇 & 4H=上昇 → 「日足・4H 一致（上昇）」

      "bullish_bias"（上昇バイアス）:
        日足が上昇で、4時間足が bearish でない場合（neutral or bullish）。
        → 上位足に従いつつ下位足の反転を待つ状況。

      "bearish_bias"（下降バイアス）:
        日足が下降で、4時間足が bullish でない場合（neutral or bearish）。
        → 上位足に従いつつ下位足の反転を待つ状況。

      "mixed"（ミックス）:
        上記いずれも当てはまらない場合。日足と4時間足が逆方向。
        → トレードを控えるか、ポジションサイズを縮小することを推奨。

    データ設計の意図:
      - 日足 200日: SMA50 計算に最低50本必要なため、余裕を持って200本取得。
      - 4時間足 60日: 4時間足1日6本 × 60日 = 360本（SMA50=8日相当）。

    Args:
        symbol: 通貨ペアシンボル（大文字で正規化される）。例: "USDJPY"。

    Returns:
        以下のキーを持つ辞書:
          symbol: 大文字シンボル
          alignment: "bullish" | "bearish" | "bullish_bias" | "bearish_bias" | "mixed"
          alignment_label: 整合性の日本語説明
          timeframes: {
            "1d": 日足トレンド情報（_trend_from_df の返り値 + timeframe/source キー）
            "4h": 4時間足トレンド情報（同上）
          }
    """
    # キャッシュキーを生成し、有効なキャッシュが存在する場合はそれを返す
    key = cache_key("mtf", symbol)
    cached = cache_get(key)
    if cached is not None:
        return cached

    # ---- 日足データの取得（200日分） ----
    # SMA50 の計算に最低50本必要なため、200日分を取得して余裕を持たせる
    daily_df, daily_src = get_ohlcv_data(symbol, days=200, timeframe="1d")

    # ---- 4時間足データの取得（60日分） ----
    # 4時間足は1日6本: 60日 × 6 = 360本分のデータを取得する
    h4_df, h4_src = get_ohlcv_data(symbol, days=60, timeframe="4h")

    # 各時間足のトレンドを独立して判定する
    daily = _trend_from_df(daily_df)
    h4 = _trend_from_df(h4_df)

    # ---- アライメント（時間足整合性）の判定 ----
    # デフォルトは "mixed"（方向が一致しない状態）
    alignment = "mixed"
    alignment_label = "ミックス"

    if daily["trend"] == h4["trend"] and daily["trend"] != "neutral":
        # 日足と4時間足が同じ方向（かつ中立でない）: 完全一致 = 最強のシグナル
        alignment = daily["trend"]
        alignment_label = "日足・4H 一致（" + daily["label"] + "）"
    elif daily["trend"] == "bullish" and h4["trend"] != "bearish":
        # 日足が上昇で4時間足が下降でない場合: 上昇バイアス（慎重にロング検討）
        alignment = "bullish_bias"
        alignment_label = "日足上昇バイアス"
    elif daily["trend"] == "bearish" and h4["trend"] != "bullish":
        # 日足が下降で4時間足が上昇でない場合: 下降バイアス（慎重にショート検討）
        alignment = "bearish_bias"
        alignment_label = "日足下降バイアス"
    # 上記以外（日足上昇かつ4時間足下降、または日足下降かつ4時間足上昇）:
    # デフォルトの "mixed" のまま（トレード回避を推奨）

    result = {
        "symbol": symbol.upper(),
        "alignment": alignment,
        "alignment_label": alignment_label,
        "timeframes": {
            # 日足データ: 元の分析結果に timeframe とデータソースを付与する
            "1d": {**daily, "timeframe": "1d", "source": daily_src},
            # 4時間足データ: 元の分析結果に timeframe とデータソースを付与する
            "4h": {**h4, "timeframe": "4h", "source": h4_src},
        },
    }

    # 計算結果を設定された TTL でキャッシュに保存する（重複計算コストの削減）
    cache_put(key, result, ttl_seconds=settings.mtf_cache_ttl_seconds)
    return result
