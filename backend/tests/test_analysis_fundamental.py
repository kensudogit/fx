"""経済指標・カレンダー — src.analysis.fundamental のテスト

外部 API（FRED / Finnhub）はモックへ差し替え、
データ構造・フォールバック・アラート抽出のロジックを検証する。
"""

import asyncio
from datetime import date, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import src.analysis.fundamental as fundamental
from src.analysis.fundamental import (
    EVENT_LABELS,
    FRED_SERIES,
    EventType,
    _template_events,
    fetch_fred_series,
    get_calendar_source,
    get_event_alerts,
    get_sample_fundamental_data,
    get_upcoming_events,
)


@pytest.fixture(autouse=True)
def clear_calendar_cache():
    """カレンダーキャッシュをテストごとに初期化する。"""
    original_cache = fundamental._calendar_cache
    original_source = fundamental._calendar_source
    fundamental._calendar_cache = []
    yield
    fundamental._calendar_cache = original_cache
    fundamental._calendar_source = original_source


class TestEventType:
    """EventType 列挙体のテスト"""

    def test_is_a_string_enum(self):
        """文字列として扱えること（JSON 化・辞書キー用）"""
        assert EventType.CPI == "cpi"
        assert EventType.CPI.value == "cpi"

    def test_covers_the_five_major_events(self):
        """主要 5 イベントを定義していること"""
        assert {e.value for e in EventType} == {
            "us_employment", "cpi", "fomc", "boj", "gdp",
        }

    def test_every_event_has_a_japanese_label(self):
        """すべてのイベントに日本語ラベルがあること"""
        for event in EventType:
            assert EVENT_LABELS[event]

    def test_fred_series_only_maps_supported_events(self):
        """FRED 系列 ID を持つのは FRED が提供する指標のみであること"""
        assert set(FRED_SERIES) <= set(EventType)
        assert EventType.FOMC not in FRED_SERIES  # 政策金利は FRED 系列から取らない


class TestFetchFredSeries:
    """fetch_fred_series() のテスト"""

    def _client(self, status_code=200, payload=None):
        """httpx.AsyncClient のコンテキストマネージャをモックする。"""
        response = MagicMock()
        response.status_code = status_code
        response.json.return_value = payload or {}
        client = MagicMock()
        client.get = AsyncMock(return_value=response)
        ctx = MagicMock()
        ctx.__aenter__ = AsyncMock(return_value=client)
        ctx.__aexit__ = AsyncMock(return_value=False)
        return ctx, client

    def test_returns_empty_without_api_key(self, override_settings):
        """API キー未設定なら通信せず空リストを返すこと"""
        override_settings(fred_api_key="")
        with patch("src.analysis.fundamental.httpx.AsyncClient") as client:
            assert asyncio.run(fetch_fred_series("PAYEMS")) == []
        client.assert_not_called()

    def test_parses_observations(self, override_settings):
        """観測値を date / value の辞書へ変換すること"""
        override_settings(fred_api_key="key")
        ctx, _ = self._client(payload={"observations": [
            {"date": "2026-01-01", "value": "150.5"},
            {"date": "2025-12-01", "value": "149.0"},
        ]})
        with patch("src.analysis.fundamental.httpx.AsyncClient", return_value=ctx):
            result = asyncio.run(fetch_fred_series("PAYEMS"))

        assert result == [
            {"date": "2026-01-01", "value": 150.5},
            {"date": "2025-12-01", "value": 149.0},
        ]

    def test_skips_missing_values(self, override_settings):
        """FRED の欠測記号 '.' の行は除外すること"""
        override_settings(fred_api_key="key")
        ctx, _ = self._client(payload={"observations": [
            {"date": "2026-01-01", "value": "."},
            {"date": "2025-12-01", "value": "149.0"},
        ]})
        with patch("src.analysis.fundamental.httpx.AsyncClient", return_value=ctx):
            result = asyncio.run(fetch_fred_series("PAYEMS"))

        assert len(result) == 1
        assert result[0]["value"] == 149.0

    def test_non_200_response_returns_empty(self, override_settings):
        """API エラー時は空リストを返すこと（例外にしない）"""
        override_settings(fred_api_key="key")
        ctx, _ = self._client(status_code=500)
        with patch("src.analysis.fundamental.httpx.AsyncClient", return_value=ctx):
            assert asyncio.run(fetch_fred_series("PAYEMS")) == []

    def test_requests_latest_first(self, override_settings):
        """最新データが先頭に来るよう降順で要求すること"""
        override_settings(fred_api_key="key")
        ctx, client = self._client(payload={"observations": []})
        with patch("src.analysis.fundamental.httpx.AsyncClient", return_value=ctx):
            asyncio.run(fetch_fred_series("CPIAUCSL", limit=5))

        params = client.get.call_args.kwargs["params"]
        assert params["sort_order"] == "desc"
        assert params["limit"] == 5
        assert params["series_id"] == "CPIAUCSL"


class TestSampleFundamentalData:
    """get_sample_fundamental_data() のテスト"""

    def test_covers_every_event_type(self):
        """全イベント種別のサンプルを持つこと"""
        data = get_sample_fundamental_data()
        assert set(data) == {e.value for e in EventType}

    def test_every_series_is_non_empty(self):
        """各系列に少なくとも 1 件のデータがあること"""
        for series in get_sample_fundamental_data().values():
            assert len(series) >= 1

    def test_datapoints_have_expected_fields(self):
        """各データ点が日付・実績・前回・予想・単位を持つこと

        `title` は政策金利系（FOMC / 日銀 / GDP）のみが持つ任意項目。
        """
        for series in get_sample_fundamental_data().values():
            for point in series:
                assert {"date", "value", "previous", "forecast", "unit"} <= set(point)

    def test_dates_are_iso_formatted(self):
        """日付は ISO 形式であること"""
        for series in get_sample_fundamental_data().values():
            for point in series:
                date.fromisoformat(point["date"])  # 例外が出なければ OK

    def test_series_are_newest_first(self):
        """各系列は新しい順に並んでいること"""
        for series in get_sample_fundamental_data().values():
            dates = [p["date"] for p in series]
            assert dates == sorted(dates, reverse=True)


class TestTemplateEvents:
    """_template_events() のテスト"""

    def test_returns_seven_events(self):
        """テンプレートは 7 件のイベントを返すこと"""
        assert len(_template_events()) == 7

    def test_all_events_are_in_the_future(self):
        """すべて未来日付であること"""
        today = date.today()
        assert all(date.fromisoformat(e["date"]) > today for e in _template_events())

    def test_events_are_sorted_by_date(self):
        """日付の昇順で並ぶこと"""
        dates = [e["date"] for e in _template_events()]
        assert dates == sorted(dates)

    def test_every_event_has_required_fields(self):
        """各イベントが必要なフィールドを持つこと"""
        for event in _template_events():
            assert set(event) == {"date", "event_type", "title", "country", "impact"}

    def test_impacts_are_known_levels(self):
        """影響度は既知のレベルのみであること"""
        assert {e["impact"] for e in _template_events()} <= {"high", "medium", "low"}

    def test_includes_a_high_impact_event_within_two_days(self):
        """直近アラート検証用に 48 時間以内の高影響イベントを含むこと"""
        soon = date.today() + timedelta(days=2)
        upcoming = [e for e in _template_events() if date.fromisoformat(e["date"]) <= soon]
        assert any(e["impact"] == "high" for e in upcoming)

    def test_gdp_is_medium_impact(self):
        """GDP は中程度の影響として区別されること"""
        gdp = [e for e in _template_events() if e["event_type"] == "gdp"]
        assert all(e["impact"] == "medium" for e in gdp)

    def test_includes_both_us_and_jp_events(self):
        """米国・日本の双方のイベントを含むこと"""
        countries = {e["country"] for e in _template_events()}
        assert countries == {"US", "JP"}


class TestGetUpcomingEvents:
    """get_upcoming_events() のテスト"""

    def test_falls_back_to_templates(self):
        """キャッシュが空ならテンプレートを返すこと"""
        assert get_upcoming_events() == _template_events()

    def test_prefers_the_cache(self):
        """キャッシュがあればそちらを返すこと（Finnhub 取得済み）"""
        cached = [{"date": "2026-06-01", "event_type": "cpi", "title": "CPI",
                   "country": "US", "impact": "high"}]
        fundamental._calendar_cache = cached
        assert get_upcoming_events() is cached

    def test_source_is_reported(self):
        """データソースを取得できること"""
        assert isinstance(get_calendar_source(), str)


class TestGetEventAlerts:
    """get_event_alerts() のテスト"""

    def _events(self, *offsets_hours, impact="high"):
        """現在から指定時間後のイベントを組み立てる（日付粒度）。"""
        now = datetime.now()
        return [
            {
                "date": (now + timedelta(hours=h)).date().isoformat(),
                "event_type": "cpi", "title": f"event+{h}h",
                "country": "US", "impact": impact,
            }
            for h in offsets_hours
        ]

    def test_only_high_impact_events_are_returned(self):
        """影響度が high 以外のイベントは除外すること"""
        events = self._events(48, impact="medium")
        with patch("src.analysis.fundamental.get_upcoming_events", return_value=events):
            assert get_event_alerts(within_hours=96) == []

    def test_past_events_are_excluded(self):
        """発表済みイベントは含めないこと"""
        events = self._events(-72)
        with patch("src.analysis.fundamental.get_upcoming_events", return_value=events):
            assert get_event_alerts(within_hours=96) == []

    def test_events_beyond_the_window_are_excluded(self):
        """指定時間より先のイベントは含めないこと"""
        events = self._events(24 * 10)
        with patch("src.analysis.fundamental.get_upcoming_events", return_value=events):
            assert get_event_alerts(within_hours=48) == []

    def test_includes_hours_until(self):
        """残り時間を hours_until として付与すること"""
        events = self._events(24 * 2)
        with patch("src.analysis.fundamental.get_upcoming_events", return_value=events):
            alerts = get_event_alerts(within_hours=24 * 5)

        assert len(alerts) == 1
        assert alerts[0]["hours_until"] > 0
        assert alerts[0]["title"].startswith("event+")

    def test_original_fields_are_preserved(self):
        """元のイベント情報を保持したまま返すこと"""
        events = self._events(24)
        with patch("src.analysis.fundamental.get_upcoming_events", return_value=events):
            alert = get_event_alerts(within_hours=72)[0]

        assert alert["country"] == "US"
        assert alert["impact"] == "high"

    def test_wider_window_returns_more_alerts(self):
        """時間幅を広げるほど対象イベントが増えること"""
        events = self._events(24, 24 * 5, 24 * 20)
        with patch("src.analysis.fundamental.get_upcoming_events", return_value=events):
            near = get_event_alerts(within_hours=48)
            far = get_event_alerts(within_hours=24 * 30)

        assert len(far) > len(near)

    def test_works_with_the_default_template_calendar(self):
        """既定のテンプレートカレンダーでも例外なく動くこと"""
        for alert in get_event_alerts(within_hours=24 * 30):
            assert alert["impact"] == "high"
            assert alert["hours_until"] >= 0
