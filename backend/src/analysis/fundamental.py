from datetime import date, datetime, timedelta
from enum import Enum
import logging

import httpx
import pandas as pd

from src.config import settings

logger = logging.getLogger(__name__)

_calendar_cache: list[dict] | None = None
_calendar_source: str = "template"
_calendar_fetched_at: datetime | None = None


class EventType(str, Enum):
    US_EMPLOYMENT = "us_employment"
    CPI = "cpi"
    FOMC = "fomc"
    BOJ = "boj"
    GDP = "gdp"


EVENT_LABELS = {
    EventType.US_EMPLOYMENT: "米国雇用統計",
    EventType.CPI: "CPI（消費者物価指数）",
    EventType.FOMC: "FOMC",
    EventType.BOJ: "日銀政策決定会合",
    EventType.GDP: "GDP",
}

# FRED series IDs for US economic data
FRED_SERIES = {
    EventType.US_EMPLOYMENT: "PAYEMS",  # Nonfarm Payrolls
    EventType.CPI: "CPIAUCSL",  # CPI All Urban Consumers
    EventType.GDP: "GDP",  # Gross Domestic Product
}


async def fetch_fred_series(series_id: str, limit: int = 24) -> list[dict]:
    """FRED API から経済指標データを取得"""
    if not settings.fred_api_key:
        return []

    url = "https://api.stlouisfed.org/fred/series/observations"
    params = {
        "series_id": series_id,
        "api_key": settings.fred_api_key,
        "file_type": "json",
        "sort_order": "desc",
        "limit": limit,
    }

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(url, params=params)
        if response.status_code != 200:
            return []
        data = response.json()

    observations = []
    for obs in data.get("observations", []):
        if obs["value"] == ".":
            continue
        observations.append(
            {
                "date": obs["date"],
                "value": float(obs["value"]),
            }
        )
    return observations


def get_sample_fundamental_data() -> dict[str, list[dict]]:
    """サンプルファンダメンタルデータ（APIキー未設定時のフォールバック）"""
    return {
        EventType.US_EMPLOYMENT.value: [
            {"date": "2025-01-03", "value": 256000, "previous": 212000, "forecast": 165000, "unit": "千人"},
            {"date": "2024-12-06", "value": 227000, "previous": 119000, "forecast": 200000, "unit": "千人"},
            {"date": "2024-11-01", "value": 12000, "previous": 223000, "forecast": 113000, "unit": "千人"},
        ],
        EventType.CPI.value: [
            {"date": "2025-01-15", "value": 3.0, "previous": 2.7, "forecast": 2.9, "unit": "%"},
            {"date": "2024-12-11", "value": 2.7, "previous": 2.6, "forecast": 2.7, "unit": "%"},
            {"date": "2024-11-13", "value": 2.6, "previous": 2.4, "forecast": 2.6, "unit": "%"},
        ],
        EventType.FOMC.value: [
            {"date": "2025-01-29", "value": 4.50, "previous": 4.50, "forecast": 4.50, "unit": "%", "title": "政策金利"},
            {"date": "2024-12-18", "value": 4.50, "previous": 4.75, "forecast": 4.50, "unit": "%", "title": "政策金利"},
            {"date": "2024-11-07", "value": 4.75, "previous": 5.00, "forecast": 4.75, "unit": "%", "title": "政策金利"},
        ],
        EventType.BOJ.value: [
            {"date": "2025-01-24", "value": 0.50, "previous": 0.25, "forecast": 0.50, "unit": "%", "title": "政策金利"},
            {"date": "2024-12-19", "value": 0.25, "previous": 0.25, "forecast": 0.25, "unit": "%", "title": "政策金利"},
            {"date": "2024-10-31", "value": 0.25, "previous": 0.25, "forecast": 0.25, "unit": "%", "title": "政策金利"},
        ],
        EventType.GDP.value: [
            {"date": "2025-01-30", "value": 2.3, "previous": 3.1, "forecast": 2.6, "unit": "%", "title": "米国GDP成長率"},
            {"date": "2024-10-30", "value": 2.8, "previous": 3.0, "forecast": 2.8, "unit": "%", "title": "米国GDP成長率"},
            {"date": "2024-07-25", "value": 2.8, "previous": 1.4, "forecast": 2.0, "unit": "%", "title": "米国GDP成長率"},
        ],
    }


async def get_fundamental_data(event_type: EventType | None = None) -> dict:
    """ファンダメンタル分析データを取得"""
    sample = get_sample_fundamental_data()

    if event_type:
        types = [event_type]
    else:
        types = list(EventType)

    result = {}
    for et in types:
        label = EVENT_LABELS[et]
        if et in FRED_SERIES and settings.fred_api_key:
            fred_data = await fetch_fred_series(FRED_SERIES[et])
            if fred_data:
                result[et.value] = {
                    "label": label,
                    "source": "FRED",
                    "data": fred_data,
                }
                continue

        result[et.value] = {
            "label": label,
            "source": "sample",
            "data": sample.get(et.value, []),
        }

    return result


def get_upcoming_events() -> list[dict]:
    """今後の経済イベント（キャッシュ or テンプレート）"""
    if _calendar_cache:
        return _calendar_cache
    return _template_events()


def get_calendar_source() -> str:
    return _calendar_source


async def refresh_economic_calendar(force: bool = False) -> list[dict]:
    """Finnhub から経済カレンダーを取得（APIキー未設定時はテンプレート）"""
    global _calendar_cache, _calendar_source, _calendar_fetched_at

    now = datetime.now()
    if (
        not force
        and _calendar_cache
        and _calendar_fetched_at
        and (now - _calendar_fetched_at).total_seconds() < 3600
    ):
        return _calendar_cache

    if settings.finnhub_api_key:
        try:
            events = await _fetch_finnhub_calendar()
            if events:
                _calendar_cache = events
                _calendar_source = "finnhub"
                _calendar_fetched_at = now
                return events
        except Exception as e:
            logger.warning("Finnhub calendar fetch failed: %s", e)

    _calendar_cache = _template_events()
    _calendar_source = "template"
    _calendar_fetched_at = now
    return _calendar_cache


async def _fetch_finnhub_calendar(days_ahead: int = 30) -> list[dict]:
    today = date.today()
    end = today + timedelta(days=days_ahead)
    url = "https://finnhub.io/api/v1/calendar/economic"
    params = {
        "from": today.isoformat(),
        "to": end.isoformat(),
        "token": settings.finnhub_api_key,
    }
    async with httpx.AsyncClient(timeout=20.0) as client:
        response = await client.get(url, params=params)
        if response.status_code != 200:
            return []
        data = response.json()

    events = []
    for item in data.get("economicCalendar", []):
        impact_raw = (item.get("impact") or "").lower()
        if impact_raw in ("high", "3"):
            impact = "high"
        elif impact_raw in ("medium", "2"):
            impact = "medium"
        else:
            impact = "low"

        event_date = item.get("time", "")[:10] or today.isoformat()
        country = (item.get("country") or "US").upper()
        title = item.get("event") or "経済指標"
        events.append({
            "date": event_date,
            "event_type": "economic",
            "title": title,
            "country": country,
            "impact": impact,
            "estimate": item.get("estimate"),
            "actual": item.get("actual"),
            "unit": item.get("unit"),
        })

    return sorted(events, key=lambda e: e["date"])


def _template_events() -> list[dict]:
    """今後の経済イベントカレンダー（日付は本日基準で動的生成）"""
    today = date.today()
    templates = [
        (3, EventType.US_EMPLOYMENT, "US", "high"),
        (7, EventType.CPI, "US", "high"),
        (14, EventType.FOMC, "US", "high"),
        (21, EventType.BOJ, "JP", "high"),
        (10, EventType.GDP, "US", "medium"),
        (1, EventType.CPI, "US", "high"),
        (28, EventType.US_EMPLOYMENT, "US", "high"),
    ]
    events = []
    for offset, et, country, impact in templates:
        d = today + timedelta(days=offset)
        title = EVENT_LABELS[et]
        if et == EventType.GDP and offset == 10:
            title = "米国GDP（改定値）"
        events.append({
            "date": d.isoformat(),
            "event_type": et.value,
            "title": title,
            "country": country,
            "impact": impact,
        })
    return sorted(events, key=lambda e: e["date"])


def get_event_alerts(within_hours: int = 48) -> list[dict]:
    """指定時間以内の高影響イベント"""
    now = datetime.now()
    deadline = now + timedelta(hours=within_hours)
    alerts = []
    for event in get_upcoming_events():
        if event["impact"] != "high":
            continue
        event_dt = datetime.combine(date.fromisoformat(event["date"]), datetime.min.time())
        if now <= event_dt <= deadline:
            hours_left = (event_dt - now).total_seconds() / 3600
            alerts.append({**event, "hours_until": round(hours_left, 1)})
    return alerts
