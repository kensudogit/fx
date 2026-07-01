"""
相場深度分析モジュール（レジーム・水準・相関・モメンタム）

このモジュールは FX 市場の多面的な分析を行い、相場環境を包括的に評価する。
以下の5つの分析コンポーネントを組み合わせて、トレード判断の基盤情報を提供する:

  1. classify_market_regime: 市場レジーム判定（トレンド/レンジ/高ボラ）
  2. find_key_levels:        サポート・レジスタンスの重要水準検出
  3. compute_momentum:       モメンタム（勢い）スコアの算出
  4. calc_pair_correlation:  通貨ペア間の相関係数行列の計算
  5. fx_session_context:     現在の FX 取引セッション判定
  6. assess_event_risk:      近接イベントリスクの評価

最終的に build_market_analysis() が全コンポーネントを統合した分析結果辞書を返す。
"""

from datetime import datetime, timezone

import pandas as pd

from src.analysis.multi_timeframe import analyze_multi_timeframe
from src.analysis.fundamental import get_event_alerts
from src.analysis.technical import compute_all_indicators
from src.analysis.volatility import calc_atr
from src.data.market_data import get_ohlcv_data
from src.data.sample_data import SYMBOL_BASE_PRICES


def _atr_series(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """DataFrame 全期間の ATR 時系列を計算する内部ヘルパー関数。

    ATR（Average True Range）は価格のボラティリティを表す指標。
    各バーの True Range（TR）を計算し、その移動平均を返す。

    True Range の計算式:
      TR[i] = max(
          High[i] - Low[i],                  # 当日の値幅（ギャップなし）
          |High[i] - Close[i-1]|,            # 前日終値から当日高値までの距離
          |Low[i]  - Close[i-1]|             # 前日終値から当日安値までの距離
      )
    ATR = TR の period 本単純移動平均（デフォルト: 14）

    前日との差分を含むことで、窓開け（ギャップアップ/ダウン）時の
    実際のボラティリティも正確に捉えることができる。

    Args:
        df: OHLCV 形式の DataFrame（high, low, close カラムが必要）。
        period: ATR の平均期間。デフォルト 14（ワイルダーが推奨した標準期間）。

    Returns:
        ATR の時系列 pd.Series（period 本前まで NaN が含まれる）。
    """
    high = df["high"]
    low = df["low"]
    close = df["close"]
    # 3つのレンジ計算を横に並べ、各行の最大値（True Range）を取得する
    tr = pd.concat(
        [high - low, (high - close.shift()).abs(), (low - close.shift()).abs()],
        axis=1,
    ).max(axis=1)
    # period 本の単純移動平均で ATR を算出する
    return tr.rolling(period).mean()


def classify_market_regime(result_df: pd.DataFrame) -> dict:
    """テクニカル指標から現在の市場レジーム（相場環境）を判定する。

    3種類のレジームを判定するための判断基準:

    1. volatile（高ボラ・不安定）:
       - ATR パーセンタイル >= 75（過去と比較してボラティリティが上位25%以上）
       - または BB 幅 > 2.5%（ボリンジャーバンドが大きく拡張している状態）
       → スキャルピングや狭い損切りには不向きな相場環境

    2. trending（トレンド相場）:
       - MA スプレッド >= 0.25%（SMA20 と SMA50 が0.25%以上乖離）
       - かつ MA が整列（価格 > SMA20 > SMA50 または 価格 < SMA20 < SMA50）
       - かつ 20日間の傾き >= 0.5%（方向感のある動き）
       → トレンドフォロー戦略が有効な相場環境

    3. ranging（レンジ相場）:
       - 上記2条件を満たさない場合
       → オシレーター系指標（RSI、ストキャスティクス等）が有効な相場環境

    各レジームの strength（強度）算出:
      - volatile: ATR パーセンタイル値を0〜100に正規化
      - trending: MA スプレッド×80 + 20日傾き×10（トレンドの強さを複合評価）
      - ranging:  100 - MA スプレッド×100（MA が整列していないほど強いレンジ）

    トレンドバイアス判定（trend_bias）:
      - 価格 > SMA20 > SMA50: 上昇トレンド（全MA整列）
      - 価格 < SMA20 < SMA50: 下降トレンド（全MA逆整列）
      - 価格 > SMA50 のみ: 上昇寄り（中期MA上だが短期は未整列）
      - 価格 < SMA50 のみ: 下降寄り（中期MA下だが短期は未整列）

    Args:
        result_df: compute_all_indicators() の出力 DataFrame。
                   必要カラム: close, sma_20, sma_50, bb_upper, bb_lower。

    Returns:
        以下のキーを持つ辞書:
          regime: "volatile" | "trending" | "ranging"
          label: 日本語の相場環境説明
          strength: 0〜100 のレジーム強度
          trend_bias: "bullish" | "bearish" | "neutral"
          trend_label: 日本語のトレンド方向説明
          atr_percentile: ATR の過去データに対するパーセンタイル（%）
          bb_width_pct: ボリンジャーバンド幅の価格に対する比率（%）
          ma_spread_pct: SMA20 と SMA50 の乖離率（%）
          slope_20d_pct: 過去20日間の終値変化率（%）
    """
    close = result_df["close"]
    price = float(close.iloc[-1])

    # SMA20・SMA50 を取得（NaN の場合は現在価格で代替して比較できるようにする）
    sma20 = float(result_df["sma_20"].iloc[-1]) if pd.notna(result_df["sma_20"].iloc[-1]) else price
    sma50 = float(result_df["sma_50"].iloc[-1]) if pd.notna(result_df["sma_50"].iloc[-1]) else price

    # 最新の ATR 値（シングル値）を取得する
    atr_now = calc_atr(result_df)
    # 全期間の ATR 時系列を計算し、現在の ATR が過去の何パーセンタイルに位置するかを算出する
    atr_hist = _atr_series(result_df).dropna()
    atr_pctile = 50.0  # データ不足時のデフォルト値（中央値相当）
    if len(atr_hist) >= 10:
        # 過去の ATR 値の中で現在 ATR 以下の割合（パーセンタイル）を計算する
        # 例: 75 → 過去の75%の期間より現在ボラが高い = 高ボラ環境
        atr_pctile = float((atr_hist <= atr_now).sum() / len(atr_hist) * 100)

    # ボリンジャーバンド幅を価格に対する割合（%）で算出する
    # BB幅 = (上限 - 下限) / 価格 × 100
    # 2.5%超: スクイーズ解放後のボラ拡大段階を示す経験的閾値
    bb_upper = float(result_df["bb_upper"].iloc[-1]) if pd.notna(result_df["bb_upper"].iloc[-1]) else price
    bb_lower = float(result_df["bb_lower"].iloc[-1]) if pd.notna(result_df["bb_lower"].iloc[-1]) else price
    bb_width_pct = (bb_upper - bb_lower) / price * 100 if price else 0

    # SMA20 と SMA50 の乖離率（%）: 移動平均の分離度 = トレンド強度の代理指標
    # 0.25%以上の乖離でトレンドが形成されていると判断する経験的閾値
    ma_spread_pct = abs(sma20 - sma50) / price * 100 if price else 0

    # 20日間の終値変化率（%）: 短期的なトレンドの傾きを確認する
    # 計算: (現在終値 - 21本前終値) / 21本前終値 × 100
    slope_20 = float((close.iloc[-1] - close.iloc[-21]) / close.iloc[-21] * 100) if len(close) > 21 else 0

    # MA 整列チェック: 上昇整列（価格 > SMA20 > SMA50）または下降整列（価格 < SMA20 < SMA50）
    aligned = (price > sma20 > sma50) or (price < sma20 < sma50)

    # ---- レジーム判定ロジック ----
    if atr_pctile >= 75 or bb_width_pct > 2.5:
        # 高ボラ: ATR が過去比で上位25%以上、またはBBが大きく拡張
        regime = "volatile"
        label = "高ボラ（不安定）"
        # 強度は ATR パーセンタイルをそのまま使用（最大100）
        strength = min(100, int(atr_pctile))
    elif ma_spread_pct >= 0.25 and aligned and abs(slope_20) >= 0.5:
        # トレンド: MA 乖離・整列・傾きの3条件を同時に満たす場合
        regime = "trending"
        label = "トレンド相場"
        # 強度はMAスプレッド（×80）と傾き（×10）の複合スコア
        strength = min(100, int(ma_spread_pct * 80 + abs(slope_20) * 10))
    else:
        # レンジ: 上記2条件を満たさない場合
        regime = "ranging"
        label = "レンジ相場"
        # 強度は MA が整列していないほど高い（MA スプレッドが小さいほどレンジが強い）
        strength = max(0, 100 - int(ma_spread_pct * 100))

    # ---- トレンドバイアス判定 ----
    trend_bias = "neutral"
    trend_label = "方向感なし"
    if price > sma20 > sma50:
        # 完全な上昇整列: 価格がSMA20・SMA50の両方を上回る
        trend_bias, trend_label = "bullish", "上昇トレンド"
    elif price < sma20 < sma50:
        # 完全な下降整列: 価格がSMA20・SMA50の両方を下回る
        trend_bias, trend_label = "bearish", "下降トレンド"
    elif price > sma50:
        # 中期MA上だが短期MAとは未整列: 上昇寄りの判断
        trend_bias, trend_label = "bullish", "上昇寄り"
    elif price < sma50:
        # 中期MA下だが短期MAとは未整列: 下降寄りの判断
        trend_bias, trend_label = "bearish", "下降寄り"

    return {
        "regime": regime,
        "label": label,
        "strength": strength,
        "trend_bias": trend_bias,
        "trend_label": trend_label,
        "atr_percentile": round(atr_pctile, 1),
        "bb_width_pct": round(bb_width_pct, 3),
        "ma_spread_pct": round(ma_spread_pct, 3),
        "slope_20d_pct": round(slope_20, 2),
    }


def find_key_levels(result_df: pd.DataFrame, symbol: str, lookback: int = 60, window: int = 5) -> dict:
    """過去データからサポート（支持）・レジスタンス（抵抗）の重要水準を検出する。

    ピボット検出アルゴリズム:
      各バー i について、前後 window 本（計 2×window+1 本）のデータを参照し、
      - i の高値が window 内の最大値 → レジスタンス候補
      - i の安値が window 内の最小値 → サポート候補
      として登録する（局所的な高値・安値の抽出）。

    クラスタリング（_cluster 内部関数）:
      近接した複数の水準を1つの水準に集約する。
      許容誤差 tol_pct（デフォルト 0.15%）以内の水準を同一クラスタとみなし、
      クラスタ内の平均価格を代表水準として採用する。
      これにより、1〜2pip 程度の誤差で形成された複数の高値/安値が
      1本の重要水準として認識される。

    重要水準は上下それぞれ最大4件を返す。

    Args:
        result_df: compute_all_indicators() の出力 DataFrame。
                   必要カラム: high, low, close。
        symbol: 通貨ペアシンボル（pip 計算に使用）。
        lookback: 検出に使用する過去バー数。デフォルト 60 本。
        window: ピボット検出のウィンドウサイズ。デフォルト 5 本（前後5本で比較）。

    Returns:
        以下のキーを持つ辞書:
          current_price: 現在価格（小数点4桁）
          supports: サポート水準リスト（昇順）
          resistances: レジスタンス水準リスト（降順）
          nearest_support: 現在価格直下の最近接サポート（または None）
          nearest_resistance: 現在価格直上の最近接レジスタンス（または None）
          distance_to_support_pips: 最近接サポートまでの距離（pips）
          distance_to_resistance_pips: 最近接レジスタンスまでの距離（pips）
    """
    # 直近 lookback 本のデータに絞り込む
    df = result_df.tail(lookback)
    highs = df["high"].values
    lows = df["low"].values
    price = float(df["close"].iloc[-1])

    resistances: list[float] = []
    supports: list[float] = []

    # ---- ピボット点の検出 ----
    # window 本以内の端（両端 window 本分）は前後データが不足するためスキップする
    for i in range(window, len(df) - window):
        h = highs[i]
        l = lows[i]
        # 前後 window 本を含む 2×window+1 本の高値の中で最大値 → ローカル高値（レジスタンス候補）
        if h == max(highs[i - window : i + window + 1]):
            resistances.append(float(h))
        # 前後 window 本を含む 2×window+1 本の安値の中で最小値 → ローカル安値（サポート候補）
        if l == min(lows[i - window : i + window + 1]):
            supports.append(float(l))

    def _cluster(levels: list[float], tol_pct: float = 0.15) -> list[float]:
        """近接した価格水準をクラスタリングして代表水準に集約する内部関数。

        アルゴリズム:
          1. 水準を降順ソートする。
          2. 直前のクラスタの先頭（最大値）と現在の水準の差が tol_pct% 以内なら
             同一クラスタに追加する。
          3. 閾値を超えた場合は新クラスタを開始する。
          4. 各クラスタの平均値を代表水準として返す。

        Args:
            levels: 価格水準のリスト。
            tol_pct: クラスタリングの許容誤差（価格の%）。デフォルト 0.15%。

        Returns:
            クラスタリング後の代表水準リスト（降順）。
        """
        if not levels:
            return []
        levels = sorted(levels, reverse=True)
        clusters: list[list[float]] = [[levels[0]]]
        for lv in levels[1:]:
            ref = clusters[-1][0]
            # ref から lv までの乖離率が tol_pct 以内なら同一クラスタに追加
            if ref and abs(lv - ref) / ref * 100 <= tol_pct:
                clusters[-1].append(lv)
            else:
                clusters.append([lv])
        # 各クラスタの平均を代表水準として採用（小数点4桁）
        return [round(sum(c) / len(c), 4) for c in clusters]

    # クラスタリング後、上下各最大4件に絞り込む
    resistances = _cluster(resistances)[:4]
    supports = _cluster(supports)[:4]
    # サポートは昇順（低い方から高い方）で並べる
    supports.sort()

    # 現在価格直下の最近接サポート（価格以下の中で最大値）
    nearest_support = max([s for s in supports if s <= price], default=None)
    # 現在価格直上の最近接レジスタンス（価格以上の中で最小値）
    nearest_resistance = min([r for r in resistances if r >= price], default=None)

    return {
        "current_price": round(price, 4),
        "supports": supports,
        "resistances": resistances,
        "nearest_support": nearest_support,
        "nearest_resistance": nearest_resistance,
        # pips 距離を計算して付与する（通貨ペアの pip サイズを考慮）
        "distance_to_support_pips": _price_distance_pips(price, nearest_support, symbol),
        "distance_to_resistance_pips": _price_distance_pips(price, nearest_resistance, symbol),
    }


def _price_distance_pips(
    from_price: float | None, to_price: float | None, symbol: str
) -> float | None:
    """2つの価格間の距離を pips 単位で計算する内部ヘルパー関数。

    pip サイズは通貨ペアによって異なる:
      - JPY ペア（USDJPY 等）: 1 pip = 0.01
      - その他（EURUSD 等）: 1 pip = 0.0001

    計算式: |to_price - from_price| / pip_size

    Args:
        from_price: 基準価格（現在価格など）。None の場合は None を返す。
        to_price: 目標価格（サポート・レジスタンスなど）。None の場合は None を返す。
        symbol: 通貨ペアシンボル（pip サイズの決定に使用）。

    Returns:
        pips 距離（小数点1桁）。どちらかの価格が None の場合は None。
    """
    if from_price is None or to_price is None:
        return None
    from src.analysis.position_sizing import pip_size

    pip = pip_size(symbol)
    return round(abs(to_price - from_price) / pip, 1) if pip else None


def compute_momentum(result_df: pd.DataFrame) -> dict:
    """複数のテクニカル指標からモメンタム（価格の勢い）を総合スコアで評価する。

    スコアリングルール（合計スコアの範囲: -100〜+100）:

      RSI（相対力指数）の寄与（最大 ±25 点）:
        RSI > 60: +25点（買われているが過熱感には達していない上昇モメンタム）
        RSI < 40: -25点（売られているが過売れには達していない下降モメンタム）
        40〜60: 0点（中立ゾーン）

      MACD ヒストグラムの寄与（最大 ±20 点）:
        ヒストグラム > 0: +20点（MACD がシグナル上 = 上昇モメンタム継続中）
        ヒストグラム < 0: -20点（MACD がシグナル下 = 下降モメンタム継続中）

      ROC5（5日間変化率）の寄与（最大 ±30 点）:
        計算式: (現在値 - 6本前終値) / 6本前終値 × 100
        スコア: roc_5 × 5 （-30〜+30 にクリップ）
        短期的な価格勢いを反映する。

      ROC20（20日間変化率）の寄与（最大 ±25 点）:
        計算式: (現在値 - 21本前終値) / 21本前終値 × 100
        スコア: roc_20 × 2 （-25〜+25 にクリップ）
        中期的なトレンドの勢いを反映する。

    モメンタムバイアス判定閾値:
      score > 30:  bullish（強い上昇モメンタム）
      score > 10:  bullish（上昇モメンタム）
      score < -30: bearish（強い下降モメンタム）
      score < -10: bearish（下降モメンタム）
      -10〜+10: neutral（中立）

    Args:
        result_df: compute_all_indicators() の出力 DataFrame。
                   必要カラム: close, rsi, macd_histogram。

    Returns:
        以下のキーを持つ辞書:
          score: 総合モメンタムスコア（-100〜+100）
          bias: "bullish" | "bearish" | "neutral"
          label: 日本語のモメンタム説明
          rsi: 最新 RSI 値（小数点1桁）
          macd_histogram: 最新 MACD ヒストグラム値（小数点6桁）
          roc_5d_pct: 5日間変化率（%）
          roc_20d_pct: 20日間変化率（%）
    """
    close = result_df["close"]
    price = float(close.iloc[-1])

    # RSI 値を取得（NaN の場合は中立値 50 を使用）
    rsi_val = float(result_df["rsi"].iloc[-1]) if pd.notna(result_df["rsi"].iloc[-1]) else 50.0

    # MACD ヒストグラムを取得（NaN の場合は 0 を使用）
    macd_hist = (
        float(result_df["macd_histogram"].iloc[-1])
        if pd.notna(result_df["macd_histogram"].iloc[-1])
        else 0.0
    )

    # ROC5: 5日間（6本前との比較）の価格変化率（%）
    # 計算: (現在終値 - 6本前終値) / 6本前終値 × 100
    roc_5 = float((close.iloc[-1] - close.iloc[-6]) / close.iloc[-6] * 100) if len(close) > 6 else 0.0

    # ROC20: 20日間（21本前との比較）の価格変化率（%）
    # 計算: (現在終値 - 21本前終値) / 21本前終値 × 100
    roc_20 = float((close.iloc[-1] - close.iloc[-21]) / close.iloc[-21] * 100) if len(close) > 21 else 0.0

    # ---- スコアの積み上げ計算 ----
    score = 0

    # RSI による寄与: 60超 → +25、40未満 → -25
    if rsi_val > 60:
        score += 25
    elif rsi_val < 40:
        score -= 25

    # MACD ヒストグラムによる寄与: 正 → +20、負 → -20
    if macd_hist > 0:
        score += 20
    elif macd_hist < 0:
        score -= 20

    # ROC5 による寄与: 短期変化率 × 5、-30〜+30 にクリップ
    score += max(-30, min(30, roc_5 * 5))

    # ROC20 による寄与: 中期変化率 × 2、-25〜+25 にクリップ
    score += max(-25, min(25, roc_20 * 2))

    # 最終スコアを -100〜+100 の範囲にクリップ
    score = max(-100, min(100, score))

    # ---- バイアス判定 ----
    if score > 30:
        bias, label = "bullish", "強い上昇モメンタム"
    elif score < -30:
        bias, label = "bearish", "強い下降モメンタム"
    elif score > 10:
        bias, label = "bullish", "上昇モメンタム"
    elif score < -10:
        bias, label = "bearish", "下降モメンタム"
    else:
        bias, label = "neutral", "中立"

    return {
        "score": score,
        "bias": bias,
        "label": label,
        "rsi": round(rsi_val, 1),
        "macd_histogram": round(macd_hist, 6),
        "roc_5d_pct": round(roc_5, 2),
        "roc_20d_pct": round(roc_20, 2),
    }


def calc_pair_correlation(days: int = 60) -> dict:
    """主要通貨ペア間のリターン相関係数行列を計算する。

    各通貨ペアの日次リターン（前日比変化率）を計算し、
    pandas の .corr() メソッドでピアソン相関係数行列を生成する。

    相関係数の解釈:
      +1.0: 完全正相関（2つのペアが全く同じ動きをする）
       0.0: 無相関（2つのペアの動きに関連性がない）
      -1.0: 完全負相関（2つのペアが逆方向に動く）

    例: EURUSD と GBPUSD は通常強い正相関（0.7〜0.9）を示す。
        USDJPY と EURUSD は負相関になることが多い（USD が共通通貨のため）。

    データの整合性確保:
      pd.DataFrame(returns).dropna() で全ペアの観測値が揃っている日のみを使用する。
      データ不足（10本未満）の場合は対角行列（自己相関=1、他は0）を返す。

    Args:
        days: 相関計算に使用する過去日数。デフォルト 60 日。

    Returns:
        以下のキーを持つ辞書:
          pairs: 通貨ペアシンボルのリスト
          matrix: {ペアA: {ペアB: 相関係数}} の入れ子辞書（小数点3桁）
          days: 計算に使用した日数
          observations: 実際に使用された観測値数
    """
    returns: dict[str, pd.Series] = {}
    # 全通貨ペアの日次リターン（前日比変化率）を計算する
    for sym in SYMBOL_BASE_PRICES:
        df, _ = get_ohlcv_data(sym, days)
        # pct_change() で前日比変化率を計算し、NaN（初日）を除外する
        returns[sym] = df["close"].pct_change().dropna()

    # 全ペアのリターンを横並びにして、全ペアでデータが揃っている日のみ残す
    aligned = pd.DataFrame(returns).dropna()

    # データが不足している場合は単位行列（自己相関のみ1）を返す
    if aligned.empty or len(aligned) < 10:
        pairs = list(SYMBOL_BASE_PRICES.keys())
        matrix = {a: {b: 1.0 if a == b else 0.0 for b in pairs} for a in pairs}
        return {"pairs": pairs, "matrix": matrix, "days": days, "observations": 0}

    # ピアソン相関係数行列を計算する
    corr = aligned.corr()
    pairs = list(corr.columns)
    # DataFrame を入れ子辞書形式に変換する（JSON シリアライズ対応）
    matrix = {
        a: {b: round(float(corr.loc[a, b]), 3) for b in pairs}
        for a in pairs
    }
    return {"pairs": pairs, "matrix": matrix, "days": days, "observations": len(aligned)}


def fx_session_context() -> dict:
    """現在 UTC 時刻から FX 取引セッションを判定し、市場特性を返す。

    FX 市場は24時間365日稼働しているが、主要金融センターの営業時間帯によって
    流動性・ボラティリティの特性が大きく異なる。

    セッション区分（UTC 時刻基準）:
      アジア時間帯（00:00〜06:59 UTC）:
        - 東京市場が主導するセッション
        - 流動性が低く、レンジ形成しやすい
        - クロス円（USDJPY, AUDJPY 等）の動きに注目

      ロンドン時間帯（07:00〜12:59 UTC）:
        - 世界最大の FX 市場センター（ロンドン）が開場
        - トレンドが発生しやすく、EUR/GBP 絡みのペアで流動性が高まる
        - アジア時間帯のレンジをブレイクアウトすることが多い

      ロンドン×NY 重複時間帯（13:00〜20:59 UTC）:
        - ロンドンと NY の両市場が同時に開いている最も流動性の高い時間帯
        - 方向性が出やすく、大口注文が集中する
        - 米国経済指標発表が集中する時間帯

      NY 時間帯（21:00〜23:59 UTC）:
        - NY 単独稼働となるセッション
        - 流動性は低下するが、米指標の余韻で急変動が起きる可能性がある

    Returns:
        以下のキーを持つ辞書:
          session: "asia" | "london" | "overlap" | "new_york"
          label: セッション名の日本語表記
          note: トレード時の注意点・特性の説明
    """
    hour_utc = datetime.now(timezone.utc).hour
    # UTC 0〜6時: アジアセッション（東京市場中心）
    if 0 <= hour_utc < 7:
        return {"session": "asia", "label": "アジア時間帯", "note": "レンジ形成・クロス円の動きに注意"}
    # UTC 7〜12時: ロンドンセッション（欧州市場中心）
    if 7 <= hour_utc < 13:
        return {"session": "london", "label": "ロンドン時間帯", "note": "トレンド発生・EUR/GBP絡みのボラ拡大"}
    # UTC 13〜20時: ロンドン×NY 重複セッション（最高流動性）
    if 13 <= hour_utc < 21:
        return {"session": "overlap", "label": "ロンドン×NY重複", "note": "最も流動性が高く方向性が出やすい"}
    # UTC 21〜23時: NY 単独セッション
    return {"session": "new_york", "label": "NY時間帯", "note": "米指標前後で急変動に注意"}


def assess_event_risk(within_hours: int = 48) -> dict:
    """直近の高影響経済イベントリスクを評価する。

    get_event_alerts() を使用して指定時間内の高影響イベント数を集計し、
    リスクレベル（high/medium/low）を判定する。

    リスクレベル判定基準:
      high:   高影響イベントが2件以上 → 複数の重要指標発表が重なる高リスク期間
      medium: 高影響イベントが1件     → 特定の重要指標に注意が必要な中リスク期間
      low:    高影響イベントが0件     → 直近のイベントリスクが低い安定期間

    Args:
        within_hours: リスク評価の時間的範囲（時間単位）。デフォルト 48 時間。

    Returns:
        以下のキーを持つ辞書:
          level: "high" | "medium" | "low"
          label: リスクレベルの日本語説明
          within_hours: 評価に使用した時間範囲
          alerts: 高影響イベントの詳細リスト（get_event_alerts の返り値）
    """
    alerts = get_event_alerts(within_hours)
    # アラート件数によってリスクレベルを3段階で判定する
    if len(alerts) >= 2:
        level, label = "high", "高 — 複数の高影響イベントが近接"
    elif len(alerts) == 1:
        level, label = "medium", "中 — 高影響イベントが48時間以内"
    else:
        level, label = "low", "低 — 直近48時間に高影響イベントなし"
    return {"level": level, "label": label, "within_hours": within_hours, "alerts": alerts}


def build_market_analysis(symbol: str, days: int = 200) -> dict:
    """指定シンボルの包括的な市場分析レポートを構築する。

    本モジュールの全分析コンポーネントを統合し、
    1つの辞書として市場の多面的な状況を提供する。

    統合される分析コンポーネント:
      regime:          市場レジーム（トレンド/レンジ/高ボラ）
      key_levels:      サポート・レジスタンス水準
      momentum:        複合モメンタムスコア
      multi_timeframe: 日足・4時間足のトレンド整合性
      correlation:     主要通貨ペア間の相関行列
      session:         現在の FX 取引セッション
      event_risk:      直近 48 時間のイベントリスク

    Args:
        symbol: 通貨ペアシンボル（大文字・小文字どちらでも可）。例: "USDJPY"。
        days: 分析に使用する過去日数。デフォルト 200 日。

    Returns:
        全分析コンポーネントの結果を含む辞書。
        各コンポーネントの詳細は個別関数の Returns を参照。
    """
    # OHLCV データの取得とテクニカル指標の一括計算
    df, source = get_ohlcv_data(symbol, days)
    result_df = compute_all_indicators(df)
    sym = symbol.upper()

    return {
        "symbol": sym,
        "source": source,
        "days": days,
        # 市場レジーム判定（トレンド/レンジ/高ボラ）
        "regime": classify_market_regime(result_df),
        # 重要サポート・レジスタンス水準の検出
        "key_levels": find_key_levels(result_df, sym),
        # モメンタム（RSI・MACD・ROC の複合スコア）
        "momentum": compute_momentum(result_df),
        # マルチタイムフレーム（日足・4H）のトレンド整合性
        "multi_timeframe": analyze_multi_timeframe(sym),
        # 主要通貨ペア間の相関係数行列（過去90日または days 以内）
        "correlation": calc_pair_correlation(min(days, 90)),
        # 現在の FX セッション（アジア/ロンドン/重複/NY）
        "session": fx_session_context(),
        # 直近 48 時間のイベントリスク評価
        "event_risk": assess_event_risk(48),
    }
