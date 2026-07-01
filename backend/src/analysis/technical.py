"""
テクニカル指標計算モジュール

このモジュールは FX トレードで広く使用されるテクニカル指標を実装する。
pandas の Series/DataFrame を入出力として使用し、
`compute_all_indicators` で全指標を一括計算できる。

実装指標一覧:
- SMA (Simple Moving Average): 単純移動平均
- EMA (Exponential Moving Average): 指数移動平均
- ボリンジャーバンド: SMA ± n×σ（標準偏差）
- MACD: 短期 EMA − 長期 EMA とシグナル線
- RSI: 相対力指数（Wilder の平滑移動平均法）
- ストキャスティクス: %K と %D
- 一目均衡表: 転換線・基準線・先行スパン A/B・遅行スパン

各指標の計算には一定のウォームアップ期間（過去データ）が必要であり、
データが少ない先頭部分は NaN となる。
"""

import numpy as np
import pandas as pd


def moving_average(series: pd.Series, period: int = 20) -> pd.Series:
    """単純移動平均線 (SMA: Simple Moving Average) を計算する。

    SMA は指定した期間の終値を単純に平均した値。
    全データポイントに等しいウェイトを付与するため計算がシンプルだが、
    古いデータと新しいデータを同等に扱う点が欠点。

    計算式:
        SMA(t) = (P(t) + P(t-1) + ... + P(t-n+1)) / n
        ※ n = period

    主な用途:
    - トレンドの方向性確認
    - サポート/レジスタンスとして機能する場合がある
    - SMA20（短期）と SMA50（長期）のクロスでシグナル生成

    Args:
        series: 価格時系列（通常は終値の pd.Series）。
        period: 移動平均の計算期間（デフォルト 20）。

    Returns:
        SMA の pd.Series。先頭 (period-1) 個の値は NaN。
    """
    return series.rolling(window=period).mean()


def exponential_moving_average(series: pd.Series, period: int = 20) -> pd.Series:
    """指数移動平均線 (EMA: Exponential Moving Average) を計算する。

    EMA は直近のデータに高いウェイトを付与する移動平均。
    SMA より価格変動への反応が速いため、MACD などで広く使用される。

    計算式（再帰的定義）:
        α = 2 / (period + 1)  ← スムージング係数
        EMA(t) = α × P(t) + (1 - α) × EMA(t-1)

    adjust=False の意味:
        pandas の ewm は デフォルト（adjust=True）では加重バイアス補正を行うが、
        トレーディング指標の標準的な計算では adjust=False（再帰的計算）を使用する。

    Args:
        series: 価格時系列（通常は終値の pd.Series）。
        period: EMA のスパン（period=12 で α≈0.154、period=26 で α≈0.074）。

    Returns:
        EMA の pd.Series。先頭は不安定だが NaN にはならない。
    """
    return series.ewm(span=period, adjust=False).mean()


def bollinger_bands(
    series: pd.Series, period: int = 20, std_dev: float = 2.0
) -> dict[str, pd.Series]:
    """ボリンジャーバンド（Bollinger Bands）を計算する。

    ボリンジャーバンドは SMA を中心に上下に ±n標準偏差のバンドを設けた指標。
    正規分布の仮定のもとで、価格がバンド内に収まる確率は:
    - ±1σ: 約 68.3%
    - ±2σ: 約 95.4%（デフォルト）
    - ±3σ: 約 99.7%

    バンドタッチは統計的異常を示し、平均回帰（バンド内への復帰）を期待できる。
    ただし、トレンドが強い場合はバンド沿いを推移することもある（バンドウォーク）。

    計算式:
        Middle（中心線） = SMA(period)
        σ = series の rolling 標準偏差
        Upper（上限バンド） = Middle + std_dev × σ
        Lower（下限バンド） = Middle - std_dev × σ

    Args:
        series:  価格時系列（通常は終値）。
        period:  SMA と標準偏差の計算期間（デフォルト 20）。
        std_dev: バンド幅の標準偏差倍数（デフォルト 2.0）。

    Returns:
        "upper"・"middle"・"lower" の各 pd.Series を値に持つ dict。
        先頭 (period-1) 個の値は NaN。
    """
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
    """MACD (Moving Average Convergence Divergence) を計算する。

    MACD は短期 EMA と長期 EMA の差を用いてモメンタムを測定する指標。
    トレンドの方向・強さ・転換点を視覚化するために広く使われる。

    計算式:
        EMA_fast = EMA(fast_period)  ← 通常 12 日
        EMA_slow = EMA(slow_period)  ← 通常 26 日
        MACD 線 = EMA_fast - EMA_slow
        シグナル線 = EMA(MACD 線, signal_period)  ← 通常 9 日
        ヒストグラム = MACD 線 - シグナル線

    シグナル解釈:
    - MACD 線 > シグナル線（ゴールデンクロス）: 買いシグナル
    - MACD 線 < シグナル線（デッドクロス）: 売りシグナル
    - ヒストグラムが正で増加: 上昇モメンタムが強まっている
    - ヒストグラムが負で減少: 下落モメンタムが弱まりつつある（底打ちに注意）

    Args:
        series:        価格時系列（通常は終値）。
        fast_period:   短期 EMA の期間（デフォルト 12）。
        slow_period:   長期 EMA の期間（デフォルト 26）。
        signal_period: シグナル線 EMA の期間（デフォルト 9）。

    Returns:
        "macd"（MACD 線）・"signal"（シグナル線）・"histogram" の各 pd.Series を持つ dict。
    """
    ema_fast = exponential_moving_average(series, fast_period)
    ema_slow = exponential_moving_average(series, slow_period)
    # MACD 線: 短期 EMA と長期 EMA の差（短期が長期を上回れば正）
    macd_line = ema_fast - ema_slow
    # シグナル線: MACD 線の EMA（MACD のトレンドを平滑化）
    signal_line = exponential_moving_average(macd_line, signal_period)
    # ヒストグラム: MACD 線とシグナル線の差（モメンタムの勢いを示す）
    histogram = macd_line - signal_line
    return {"macd": macd_line, "signal": signal_line, "histogram": histogram}


def rsi(series: pd.Series, period: int = 14) -> pd.Series:
    """RSI (Relative Strength Index: 相対力指数) を計算する。

    RSI は Welles Wilder が 1978 年に考案した指標で、
    一定期間の上昇幅と下落幅の比率から相対的な強さを 0〜100 で表す。

    計算式（Wilder の指数移動平均を使用）:
        Δ = P(t) - P(t-1)  ← 前日比
        Gain = Δ > 0 の場合は Δ、それ以外は 0
        Loss = Δ < 0 の場合は |Δ|、それ以外は 0

        avg_gain = Gain の Wilder の EMA（α = 1/period）
        avg_loss = Loss の Wilder の EMA（α = 1/period）

        RS = avg_gain / avg_loss
        RSI = 100 - (100 / (1 + RS))

    Wilder の EMA（alpha=1/period）は通常の EMA（alpha=2/(period+1)）より
    平滑化が強く、ノイズの影響を受けにくい。

    解釈の目安:
    - RSI < 30: 売られ過ぎ（反発の可能性）
    - RSI > 70: 買われ過ぎ（下落の可能性）
    - RSI = 50: 中立（方向感なし）
    - ダイバージェンス（価格とRSIの逆行）: トレンド転換の強力なシグナル

    Args:
        series: 価格時系列（通常は終値）。
        period: RSI の計算期間（デフォルト 14）。Wilder の推奨値。

    Returns:
        RSI 値の pd.Series（0〜100 の範囲）。
        先頭 period 個は NaN となる。
    """
    delta = series.diff()
    # 上昇分（Gain）と下落分（Loss）を分離
    gain = delta.where(delta > 0, 0.0)
    loss = (-delta).where(delta < 0, 0.0)
    # Wilder の平滑移動平均: alpha = 1/period（通常の EMA より平滑化が強い）
    avg_gain = gain.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    # RS（Relative Strength）= 平均上昇 / 平均下落
    rs = avg_gain / avg_loss
    # RSI = 100 - (100 / (1 + RS))
    # RS が大きいほど RSI は 100 に近づく（強い上昇トレンド）
    return 100 - (100 / (1 + rs))


def stochastic(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    k_period: int = 14,
    d_period: int = 3,
) -> dict[str, pd.Series]:
    """ストキャスティクス（Stochastic Oscillator）の %K と %D を計算する。

    ストキャスティクスは George Lane が考案した指標で、
    一定期間の高値・安値レンジに対する現在値の相対位置を示す。
    "終値は、強い上昇トレンドでは期間高値付近に、
    強い下降トレンドでは期間安値付近に収束する" という観察に基づく。

    計算式:
        %K = (close - n期間最安値) / (n期間最高値 - n期間最安値) × 100
        %D = %K の m日単純移動平均（スムージング）

    例: 14 日高値が 155.00、安値が 150.00、終値が 154.00 の場合
        %K = (154 - 150) / (155 - 150) × 100 = 80%

    解釈の目安:
    - %K < 20 かつ %D < 20: 売られ過ぎ圏（買いシグナル候補）
    - %K > 80 かつ %D > 80: 買われ過ぎ圏（売りシグナル候補）
    - %K が %D を上抜け（ゴールデンクロス）: 買いシグナル（売られ過ぎ圏で特に有効）
    - %K が %D を下抜け（デッドクロス）: 売りシグナル

    Args:
        high:     高値の時系列 Series。
        low:      安値の時系列 Series。
        close:    終値の時系列 Series。
        k_period: %K の計算期間（デフォルト 14）。
        d_period: %D の移動平均期間（デフォルト 3）。

    Returns:
        "k"（%K）と "d"（%D）の pd.Series を持つ dict。
        先頭 (k_period-1) 個は NaN。
    """
    # n期間の最安値と最高値を計算
    lowest_low = low.rolling(window=k_period).min()
    highest_high = high.rolling(window=k_period).max()
    # %K: 期間レンジ内の現在値の相対位置（0〜100%）
    k = 100 * (close - lowest_low) / (highest_high - lowest_low)
    # %D: %K を平滑化したシグナル線（クロスでシグナル判定）
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
    """一目均衡表（Ichimoku Cloud）を計算する。

    一目均衡表は細田悟一（ペンネーム: 一目山人）が 1969 年に発表した
    日本発のテクニカル指標で、トレンド・サポート/レジスタンス・
    勢い・シグナルを 1 つのチャートで視覚化する。

    各線の計算式と意味:
    【転換線（Tenkan-sen）】 期間: 9 日（デフォルト）
        転換線 = (9日高値 + 9日安値) / 2
        短期のサポート/レジスタンス。価格がここを下抜けると短期トレンド転換。

    【基準線（Kijun-sen）】 期間: 26 日（デフォルト）
        基準線 = (26日高値 + 26日安値) / 2
        中期のサポート/レジスタンス。転換線が基準線を上抜けると買いシグナル。

    【先行スパン A（Senkou Span A）】
        先行スパン A = (転換線 + 基準線) / 2
        26 日先にシフト（displacement = 26）
        雲（クラウド）の上限を形成する。

    【先行スパン B（Senkou Span B）】 期間: 52 日（デフォルト）
        先行スパン B = (52日高値 + 52日安値) / 2
        26 日先にシフト（displacement = 26）
        雲（クラウド）の下限を形成する。

    【遅行スパン（Chikou Span）】
        遅行スパン = 現在の終値を 26 日前にシフト
        現在の終値と過去の価格水準を比較してモメンタムを確認。
        現在価格が 26 日前の終値より高ければ上昇トレンドとみなす。

    シグナル解釈:
    - 価格が雲の上: 上昇トレンド（先行スパン A と B が雲を形成）
    - 価格が雲の下: 下降トレンド
    - 価格が雲の中: トレンドなし（レンジ）
    - 転換線 > 基準線: 強気バイアス

    Args:
        high:            高値の時系列 Series。
        low:             安値の時系列 Series。
        close:           終値の時系列 Series。
        tenkan_period:   転換線の期間（デフォルト 9）。
        kijun_period:    基準線の期間（デフォルト 26）。
        senkou_b_period: 先行スパン B の期間（デフォルト 52）。
        displacement:    先行・遅行スパンのシフト量（デフォルト 26）。

    Returns:
        "tenkan"・"kijun"・"senkou_a"・"senkou_b"・"chikou" の各 pd.Series を持つ dict。
    """
    # 転換線: 9 日高安平均（短期均衡値）
    tenkan = (high.rolling(tenkan_period).max() + low.rolling(tenkan_period).min()) / 2
    # 基準線: 26 日高安平均（中期均衡値）
    kijun = (high.rolling(kijun_period).max() + low.rolling(kijun_period).min()) / 2
    # 先行スパン A: 転換線と基準線の平均を 26 日先にシフト（雲の上限）
    senkou_a = ((tenkan + kijun) / 2).shift(displacement)
    # 先行スパン B: 52 日高安平均を 26 日先にシフト（雲の下限）
    senkou_b = (
        (high.rolling(senkou_b_period).max() + low.rolling(senkou_b_period).min()) / 2
    ).shift(displacement)
    # 遅行スパン: 現在の終値を 26 日前にシフト（過去との比較でモメンタム確認）
    chikou = close.shift(-displacement)
    return {
        "tenkan": tenkan,
        "kijun": kijun,
        "senkou_a": senkou_a,
        "senkou_b": senkou_b,
        "chikou": chikou,
    }


def compute_all_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """全テクニカル指標を一括計算して DataFrame に追加する。

    元の OHLCV DataFrame を複製し、以下の全指標を計算して列として追加する:
    - SMA 20・SMA 50（短期・中期トレンド確認）
    - EMA 12・EMA 26（MACD の構成要素）
    - ボリンジャーバンド（上限・中心・下限）
    - MACD 線・シグナル線・ヒストグラム
    - RSI（14 日）
    - ストキャスティクス %K・%D
    - 一目均衡表（転換線・基準線・先行スパン A/B・遅行スパン）

    ウォームアップ期間の目安:
    - SMA50 が安定するまで: 最低 50 バー必要
    - MACD (26 日 EMA): 最低 26 バー
    - 一目均衡表（52 日）: 最低 78 バー（52 + 26 シフト）
    先頭部分が NaN になることを前提にして使用すること。

    Args:
        df: "open"・"high"・"low"・"close"・"volume" 列を含む OHLCV DataFrame。

    Returns:
        元の全列に加えて各指標列を追加した新しい DataFrame（元の df は変更しない）。
    """
    result = df.copy()
    close = df["close"]
    high = df["high"]
    low = df["low"]

    # 移動平均（SMA）: 短期 20 日と中期 50 日でトレンドを評価
    result["sma_20"] = moving_average(close, 20)
    result["sma_50"] = moving_average(close, 50)
    # 指数移動平均（EMA）: MACD の構成要素として 12 日と 26 日を計算
    result["ema_12"] = exponential_moving_average(close, 12)
    result["ema_26"] = exponential_moving_average(close, 26)

    # ボリンジャーバンド: ±2σ（標準的な設定）
    bb = bollinger_bands(close)
    result["bb_upper"] = bb["upper"]
    result["bb_middle"] = bb["middle"]
    result["bb_lower"] = bb["lower"]

    # MACD: 標準設定（12-26-9）
    macd_data = macd(close)
    result["macd"] = macd_data["macd"]
    result["macd_signal"] = macd_data["signal"]
    result["macd_histogram"] = macd_data["histogram"]

    # RSI: 14 日（Wilder の推奨期間）
    result["rsi"] = rsi(close)

    # ストキャスティクス: 14 日 %K、3 日 %D
    stoch = stochastic(high, low, close)
    result["stoch_k"] = stoch["k"]
    result["stoch_d"] = stoch["d"]

    # 一目均衡表: 標準設定（9-26-52-26）
    ichi = ichimoku(high, low, close)
    for key, series in ichi.items():
        # 列名を "ichi_" プレフィックス付きで追加（例: "ichi_tenkan", "ichi_kijun"）
        result[f"ichi_{key}"] = series

    return result


def series_to_list(series: pd.Series) -> list[float | None]:
    """pandas Series を JSON シリアライズ可能なリストに変換する。

    API レスポンスや JSON 出力のために、pandas Series を
    Python ネイティブの list に変換する。NaN 値は None に置換し、
    JSON の null として表現できるようにする。

    Args:
        series: 変換対象の pd.Series（数値型を想定）。

    Returns:
        float または None のリスト。NaN → None、数値は小数点 6 桁に丸め。
    """
    return [None if pd.isna(v) else round(float(v), 6) for v in series]
