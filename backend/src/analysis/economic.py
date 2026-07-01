"""
経済指標分析モジュール（ルールベース + データスコアリング）

各経済指標（雇用統計・CPI・FOMC・BOJ・GDP）の最新実績を予想値・前回値と比較し、
通貨ペアへのファンダメンタル的な強弱バイアスをスコアリングする。

スコアリングの基本ロジック:
  1. 各指標の実績と予想（または前回値）を比較して impact を判定（positive/negative/neutral）。
  2. その指標がどの通貨に影響するかを INDICATOR_CURRENCY テーブルで照合する。
  3. 影響通貨が基軸通貨なら pair_score を +1/-1、決済通貨なら逆符号で加算する。
  4. pair_score の合計が ±2 以上で強気/弱気バイアスを判定する。
"""

from src.analysis.fundamental import (
    EVENT_LABELS,
    EventType,
    get_event_alerts,
    get_fundamental_data,
    get_upcoming_events,
)

# 通貨ペアシンボルを（基軸通貨, 決済通貨）のタプルにマッピングするテーブル。
# 例: "USDJPY" → ("USD", "JPY")
CURRENCY_MAP = {
    "USDJPY": ("USD", "JPY"),
    "EURUSD": ("EUR", "USD"),
    "GBPUSD": ("GBP", "USD"),
    "AUDUSD": ("AUD", "USD"),
}

# 経済指標キーと、その指標が直接影響する通貨を対応付けるテーブル。
# 例: 米国雇用統計が予想を上回る（positive）→ USD が強まる方向性。
# 通貨ペアへの最終的な方向性は _impact_on_pair() 内で計算する。
INDICATOR_CURRENCY = {
    EventType.US_EMPLOYMENT.value: "USD",
    EventType.CPI.value: "USD",
    EventType.FOMC.value: "USD",
    EventType.GDP.value: "USD",
    EventType.BOJ.value: "JPY",
}


def _score_datapoint(point: dict) -> tuple[str, str]:
    """経済指標の1データポイントを評価し、impact（影響方向）とコメントを返す。

    スコアリング優先順位:
      1. 実績値（value）が存在しない場合 → "neutral"（データ不足）
      2. 予想値（forecast）が存在する場合 → 実績 vs 予想で判定
      3. 予想値がなく前回値（previous）が存在する場合 → 実績 vs 前回値で判定
      4. いずれも存在しない場合 → "neutral"（最新値として表示）

    Args:
        point: 経済指標1件分の辞書。
               キー: value（実績）, forecast（予想）, previous（前回値）。

    Returns:
        (impact, comment) のタプル。
        impact: "positive" | "negative" | "neutral"
        comment: 判定理由を説明する日本語文字列。
    """
    value = point.get("value")
    forecast = point.get("forecast")
    previous = point.get("previous")

    # 実績値が存在しない場合はスコアリング不能
    if value is None:
        return "neutral", "データ不足"

    # --- 予想値との比較（最優先） ---
    # 予想値がある場合: 実績 > 予想 → positive（予想超え）, 実績 < 予想 → negative（予想未達）
    if forecast is not None:
        diff = value - forecast
        if diff > 0:
            return "positive", f"予想 {forecast} を上回り ({value})"
        if diff < 0:
            return "negative", f"予想 {forecast} を下回り ({value})"
        return "neutral", f"予想通り ({value})"

    # --- 前回値との比較（フォールバック） ---
    # 予想値がない場合: 実績 > 前回 → positive（改善）, 実績 < 前回 → negative（悪化）
    if previous is not None:
        diff = value - previous
        if diff > 0:
            return "positive", f"前回 {previous} から改善 ({value})"
        if diff < 0:
            return "negative", f"前回 {previous} から悪化 ({value})"
        return "neutral", f"前回と同水準 ({value})"

    # 比較対象なし → ニュートラルとして最新値のみ表示
    return "neutral", f"最新値 {value}"


def _impact_on_pair(indicator_key: str, impact: str, base: str, quote: str) -> str:
    """経済指標の impact を通貨ペアへの方向性（bullish/bearish/neutral）に変換する。

    変換ロジック:
      - INDICATOR_CURRENCY テーブルで指標が影響する通貨を特定する。
      - impact == "positive"（指標が良い）なら、影響通貨は強まる（その通貨が基軸なら bullish）。
      - impact == "negative"（指標が悪い）なら、影響通貨は弱まる（その通貨が基軸なら bearish）。
      - 影響通貨が決済通貨（quote）の場合は方向が逆になる。

    例: USDJPY で米国雇用統計が positive の場合
        affected = "USD"（基軸通貨）、impact = "positive" → bullish（USD 高・JPY 安）

    Args:
        indicator_key: 指標キー文字列（EventType.value）。
        impact: "_score_datapoint" が返す "positive" | "negative" | "neutral"。
        base: 通貨ペアの基軸通貨（例: "USD"）。
        quote: 通貨ペアの決済通貨（例: "JPY"）。

    Returns:
        "bullish" | "bearish" | "neutral"
    """
    # INDICATOR_CURRENCY に登録されていない指標は影響なしとしてニュートラルを返す
    affected = INDICATOR_CURRENCY.get(indicator_key)
    if not affected:
        return "neutral"

    # impact がニュートラルなら通貨ペアへの方向性もニュートラル
    if impact == "neutral":
        return "neutral"

    # positive impact → 影響通貨が強くなる
    bullish_base = impact == "positive"

    if affected == base:
        # 影響通貨が基軸通貨: positive → bullish（基軸通貨高）, negative → bearish（基軸通貨安）
        return "bullish" if bullish_base else "bearish"
    if affected == quote:
        # 影響通貨が決済通貨: positive → bearish（決済通貨高 = 基軸通貨安）
        return "bearish" if bullish_base else "bullish"

    # どちらの通貨にも該当しない指標
    return "neutral"


async def analyze_economic(symbol: str) -> dict:
    """指定シンボルのファンダメンタル経済分析を実行する。

    処理フロー:
      1. 経済カレンダーを最新情報にリフレッシュ（Finnhub API or テンプレート）。
      2. 各経済指標（雇用統計・CPI・FOMC・BOJ・GDP）の最新データを取得する。
      3. 各指標の実績を予想/前回値と比較してスコアリングし、通貨ペアへの方向性を算出する。
      4. 全指標スコアを合算し、総合バイアス（bullish/bearish/neutral）を判定する。

    バイアス判定閾値:
      - pair_score >= +2 → bullish（強気）
      - pair_score <= -2 → bearish（弱気）
      - それ以外 → neutral（中立）

    Args:
        symbol: 通貨ペアシンボル（例: "USDJPY", "EURUSD"）。大文字・小文字どちらでも可。

    Returns:
        以下のキーを持つ辞書:
          symbol: 大文字シンボル
          base_currency / quote_currency: 基軸・決済通貨コード
          pair_bias: "bullish" | "bearish" | "neutral"
          pair_bias_label: バイアスの日本語説明文
          score: 合計スコア値（整数）
          indicators: 各指標の詳細リスト
          upcoming_events: 今後8件の経済イベントリスト
          high_impact_alerts: 72時間以内の高影響イベントリスト
          overview: 分析サマリー文字列
    """
    from src.analysis.fundamental import refresh_economic_calendar

    # 経済カレンダーを最新に更新（1時間以内にキャッシュがあればスキップ）
    await refresh_economic_calendar()

    # シンボルを基軸通貨・決済通貨に分解する
    # CURRENCY_MAP にない場合は先頭3文字/後続3文字でシンプルに分割
    base, quote = CURRENCY_MAP.get(symbol.upper(), (symbol[:3], symbol[3:]))

    # 全指標のファンダメンタルデータを取得（FRED API or サンプルデータ）
    fund_data = await get_fundamental_data()

    # 今後8件のイベントを取得（ウィジェット表示用）
    upcoming = get_upcoming_events()[:8]

    # 72時間以内の高影響イベントのアラートリストを取得
    alerts = get_event_alerts(72)

    indicators = []
    pair_score = 0  # 各指標の通貨ペア方向性を合計したスコア（正=強気寄り、負=弱気寄り）

    for key, block in fund_data.items():
        label = block.get("label", key)
        data = block.get("data", [])
        if not data:
            continue

        # 最新データポイント（先頭要素）を評価する
        latest = data[0]
        impact, comment = _score_datapoint(latest)

        # 指標の impact を通貨ペアへの方向性に変換する
        pair_dir = _impact_on_pair(key, impact, base, quote)

        # ペアスコアを累積する（bullish: +1, bearish: -1）
        if pair_dir == "bullish":
            pair_score += 1
        elif pair_dir == "bearish":
            pair_score -= 1

        indicators.append({
            "key": key,
            "name": label,
            "source": block.get("source", "sample"),
            "latest_date": latest.get("date"),
            "value": latest.get("value"),
            "previous": latest.get("previous"),
            "forecast": latest.get("forecast"),
            "unit": latest.get("unit", ""),
            "impact": impact,
            "pair_direction": pair_dir,
            "comment": comment,
        })

    # ---- ペアスコア合計から総合バイアスを判定 ----
    # 閾値 ±2 はヒューリスティックな値。複数指標が同方向を示す場合に強気/弱気と判断する。
    if pair_score >= 2:
        bias = "bullish"
        bias_label = f"{symbol} ファンダメンタル強気"
    elif pair_score <= -2:
        bias = "bearish"
        bias_label = f"{symbol} ファンダメンタル弱気"
    else:
        bias = "neutral"
        bias_label = f"{symbol} ファンダメンタル中立"

    # 今後のイベントから高影響イベント（impact="high"）のみを最大5件抽出してリスク一覧を作成
    risks = [
        f"{ev['date']}: {ev['title']} ({ev['country']})"
        for ev in upcoming
        if ev.get("impact") == "high"
    ][:5]

    return {
        "symbol": symbol.upper(),
        "base_currency": base,
        "quote_currency": quote,
        "pair_bias": bias,
        "pair_bias_label": bias_label,
        "score": pair_score,
        "indicators": indicators,
        "upcoming_events": upcoming,
        "high_impact_alerts": alerts,
        "overview": (
            f"{base}/{quote} — {len(indicators)}指標を分析。"
            f"総合バイアス: {bias_label}。"
            f"高影響イベント {len(alerts)}件が72時間以内。"
        ),
    }
