"""経済指標分析（ルールベース + データスコアリング）"""

from src.analysis.fundamental import (
    EVENT_LABELS,
    EventType,
    get_event_alerts,
    get_fundamental_data,
    get_upcoming_events,
)

CURRENCY_MAP = {
    "USDJPY": ("USD", "JPY"),
    "EURUSD": ("EUR", "USD"),
    "GBPUSD": ("GBP", "USD"),
    "AUDUSD": ("AUD", "USD"),
}

# 通貨ペアへの影響方向（指標が良い=基軸通貨にプラス等）
INDICATOR_CURRENCY = {
    EventType.US_EMPLOYMENT.value: "USD",
    EventType.CPI.value: "USD",
    EventType.FOMC.value: "USD",
    EventType.GDP.value: "USD",
    EventType.BOJ.value: "JPY",
}


def _score_datapoint(point: dict) -> tuple[str, str]:
    """実績 vs 予想・前回を比較して impact を判定"""
    value = point.get("value")
    forecast = point.get("forecast")
    previous = point.get("previous")
    if value is None:
        return "neutral", "データ不足"

    if forecast is not None:
        diff = value - forecast
        if diff > 0:
            return "positive", f"予想 {forecast} を上回り ({value})"
        if diff < 0:
            return "negative", f"予想 {forecast} を下回り ({value})"
        return "neutral", f"予想通り ({value})"

    if previous is not None:
        diff = value - previous
        if diff > 0:
            return "positive", f"前回 {previous} から改善 ({value})"
        if diff < 0:
            return "negative", f"前回 {previous} から悪化 ({value})"
        return "neutral", f"前回と同水準 ({value})"

    return "neutral", f"最新値 {value}"


def _impact_on_pair(indicator_key: str, impact: str, base: str, quote: str) -> str:
    """指標が通貨ペアに与える方向"""
    affected = INDICATOR_CURRENCY.get(indicator_key)
    if not affected:
        return "neutral"

    if impact == "neutral":
        return "neutral"

    bullish_base = impact == "positive"
    if affected == base:
        return "bullish" if bullish_base else "bearish"
    if affected == quote:
        return "bearish" if bullish_base else "bullish"
    return "neutral"


async def analyze_economic(symbol: str) -> dict:
    from src.analysis.fundamental import refresh_economic_calendar

    await refresh_economic_calendar()
    base, quote = CURRENCY_MAP.get(symbol.upper(), (symbol[:3], symbol[3:]))
    fund_data = await get_fundamental_data()
    upcoming = get_upcoming_events()[:8]
    alerts = get_event_alerts(72)

    indicators = []
    pair_score = 0

    for key, block in fund_data.items():
        label = block.get("label", key)
        data = block.get("data", [])
        if not data:
            continue
        latest = data[0]
        impact, comment = _score_datapoint(latest)
        pair_dir = _impact_on_pair(key, impact, base, quote)

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

    if pair_score >= 2:
        bias = "bullish"
        bias_label = f"{symbol} ファンダメンタル強気"
    elif pair_score <= -2:
        bias = "bearish"
        bias_label = f"{symbol} ファンダメンタル弱気"
    else:
        bias = "neutral"
        bias_label = f"{symbol} ファンダメンタル中立"

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
