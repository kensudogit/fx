"""経済指標のペア別インパクト分析 — src.analysis.economic のテスト"""

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from src.analysis.economic import (
    CURRENCY_MAP,
    INDICATOR_CURRENCY,
    _impact_on_pair,
    _score_datapoint,
    analyze_economic,
)


class TestCurrencyMaps:
    """通貨マッピング定数のテスト"""

    def test_pairs_split_into_base_and_quote(self):
        """各ペアが基軸通貨と決済通貨に分解されていること"""
        assert CURRENCY_MAP["USDJPY"] == ("USD", "JPY")
        assert CURRENCY_MAP["EURUSD"] == ("EUR", "USD")

    def test_all_entries_are_three_letter_codes(self):
        """通貨コードが 3 文字であること"""
        for base, quote in CURRENCY_MAP.values():
            assert len(base) == 3 and len(quote) == 3

    def test_indicators_map_to_a_currency(self):
        """各指標が影響通貨に紐づいていること"""
        assert INDICATOR_CURRENCY["cpi"] == "USD"
        assert INDICATOR_CURRENCY["boj"] == "JPY"

    def test_indicator_currencies_are_known(self):
        """指標の影響通貨が実在する通貨であること"""
        known = {c for pair in CURRENCY_MAP.values() for c in pair}
        assert set(INDICATOR_CURRENCY.values()) <= known


class TestScoreDatapoint:
    """_score_datapoint() のテスト"""

    def test_missing_value_is_neutral(self):
        """実績値が無ければ判定不能とすること"""
        impact, comment = _score_datapoint({"value": None})
        assert impact == "neutral"
        assert comment == "データ不足"

    def test_beating_the_forecast_is_positive(self):
        """予想を上回れば positive になること"""
        impact, comment = _score_datapoint({"value": 3.5, "forecast": 3.0})
        assert impact == "positive"
        assert "上回り" in comment

    def test_missing_the_forecast_is_negative(self):
        """予想を下回れば negative になること"""
        impact, _ = _score_datapoint({"value": 2.5, "forecast": 3.0})
        assert impact == "negative"

    def test_matching_the_forecast_is_neutral(self):
        """予想どおりなら neutral になること"""
        impact, comment = _score_datapoint({"value": 3.0, "forecast": 3.0})
        assert impact == "neutral"
        assert "予想通り" in comment

    def test_forecast_takes_priority_over_previous(self):
        """予想値があれば前回値より優先すること"""
        # 前回比では悪化だが、予想比では上回るケース
        impact, comment = _score_datapoint({"value": 2.5, "forecast": 2.0, "previous": 3.0})
        assert impact == "positive"
        assert "予想" in comment

    def test_falls_back_to_previous_value(self):
        """予想が無ければ前回値と比較すること"""
        impact, comment = _score_datapoint({"value": 3.5, "previous": 3.0})
        assert impact == "positive"
        assert "前回" in comment

    def test_decline_from_previous_is_negative(self):
        """前回より悪化すれば negative になること"""
        impact, _ = _score_datapoint({"value": 2.5, "previous": 3.0})
        assert impact == "negative"

    def test_same_as_previous_is_neutral(self):
        """前回と同水準なら neutral になること"""
        impact, comment = _score_datapoint({"value": 3.0, "previous": 3.0})
        assert impact == "neutral"
        assert "同水準" in comment

    def test_value_only_is_neutral(self):
        """比較対象が無ければ中立として実績値のみ報告すること"""
        impact, comment = _score_datapoint({"value": 3.0})
        assert impact == "neutral"
        assert "3.0" in comment


class TestImpactOnPair:
    """_impact_on_pair() のテスト"""

    def test_positive_us_data_lifts_usdjpy(self):
        """USD が基軸の場合、米指標の改善は通貨ペアの強気要因になること"""
        assert _impact_on_pair("cpi", "positive", "USD", "JPY") == "bullish"

    def test_negative_us_data_weighs_on_usdjpy(self):
        """米指標の悪化は弱気要因になること"""
        assert _impact_on_pair("cpi", "negative", "USD", "JPY") == "bearish"

    def test_positive_us_data_weighs_on_eurusd(self):
        """USD が決済通貨の場合は向きが反転すること"""
        assert _impact_on_pair("cpi", "positive", "EUR", "USD") == "bearish"

    def test_negative_us_data_lifts_eurusd(self):
        """USD 悪化は EURUSD の強気要因になること"""
        assert _impact_on_pair("cpi", "negative", "EUR", "USD") == "bullish"

    def test_japanese_data_on_usdjpy(self):
        """日銀イベントは JPY（決済通貨）側に効くこと"""
        assert _impact_on_pair("boj", "positive", "USD", "JPY") == "bearish"

    def test_neutral_impact_stays_neutral(self):
        """指標が中立なら方向も中立であること"""
        assert _impact_on_pair("cpi", "neutral", "USD", "JPY") == "neutral"

    def test_unrelated_currency_is_neutral(self):
        """対象通貨がペアに含まれなければ中立であること"""
        assert _impact_on_pair("cpi", "positive", "EUR", "GBP") == "neutral"

    def test_unknown_indicator_is_neutral(self):
        """未知の指標は中立として扱うこと"""
        assert _impact_on_pair("unknown_event", "positive", "USD", "JPY") == "neutral"


class TestAnalyzeEconomic:
    """analyze_economic() のテスト"""

    def _run(self, fundamental=None, upcoming=None, alerts=None, symbol="USDJPY"):
        """依存をモックして分析を実行する。"""
        data = fundamental if fundamental is not None else {
            "cpi": {"label": "CPI", "source": "FRED",
                    "data": [{"date": "2026-01-01", "value": 3.5, "forecast": 3.0,
                              "previous": 3.2, "unit": "%"}]},
        }
        with patch("src.analysis.fundamental.refresh_economic_calendar",
                   new=AsyncMock(return_value=[])), \
             patch("src.analysis.economic.get_fundamental_data",
                   new=AsyncMock(return_value=data)), \
             patch("src.analysis.economic.get_upcoming_events",
                   return_value=upcoming if upcoming is not None else []), \
             patch("src.analysis.economic.get_event_alerts",
                   return_value=alerts if alerts is not None else []):
            return asyncio.run(analyze_economic(symbol))

    def test_returns_expected_keys(self):
        """分析結果の主要キーが揃っていること"""
        result = self._run()
        assert {"symbol", "base_currency", "quote_currency",
                "pair_bias", "pair_bias_label"} <= set(result)

    def test_splits_the_currency_pair(self):
        """通貨ペアを基軸・決済に分解すること"""
        result = self._run()
        assert result["base_currency"] == "USD"
        assert result["quote_currency"] == "JPY"

    def test_unknown_pair_is_split_by_position(self):
        """未登録のペアでも先頭 3 文字 / 後半 3 文字で分解すること"""
        result = self._run(symbol="NZDCAD")
        assert result["base_currency"] == "NZD"
        assert result["quote_currency"] == "CAD"

    def test_normalizes_the_symbol(self):
        """シンボルを大文字化すること"""
        assert self._run(symbol="usdjpy")["symbol"] == "USDJPY"

    def test_indicator_rows_carry_the_analysis(self):
        """各指標に影響度・ペア方向・コメントを付けること"""
        indicator = self._run()["indicators"][0]

        assert indicator["key"] == "cpi"
        assert indicator["impact"] == "positive"
        assert indicator["pair_direction"] == "bullish"
        assert indicator["comment"]

    def test_empty_series_are_skipped(self):
        """データが無い指標はスキップすること"""
        result = self._run(fundamental={"cpi": {"label": "CPI", "data": []}})
        assert result["indicators"] == []

    def test_bias_requires_two_agreeing_indicators(self):
        """2 指標以上が同方向で初めてバイアスを確定すること"""
        one_bullish = self._run()
        assert one_bullish["pair_bias"] == "neutral"

        two_bullish = self._run(fundamental={
            "cpi": {"label": "CPI", "data": [{"value": 3.5, "forecast": 3.0}]},
            "us_employment": {"label": "雇用統計", "data": [{"value": 250, "forecast": 200}]},
        })
        assert two_bullish["pair_bias"] == "bullish"

    def test_bearish_bias(self):
        """弱気指標が揃えば bearish になること"""
        result = self._run(fundamental={
            "cpi": {"label": "CPI", "data": [{"value": 2.5, "forecast": 3.0}]},
            "us_employment": {"label": "雇用統計", "data": [{"value": 150, "forecast": 200}]},
        })
        assert result["pair_bias"] == "bearish"

    def test_bias_label_mentions_the_symbol(self):
        """バイアスのラベルに通貨ペア名を含めること"""
        assert "USDJPY" in self._run()["pair_bias_label"]

    def test_returns_upcoming_events_and_alerts(self):
        """今後のイベントと高影響アラートをそのまま返すこと

        実装内では高影響イベントだけを抽出した `risks` を組み立てているが、
        戻り値には含めていない（未使用のローカル変数）。API が返すのは
        フィルタ前の `upcoming_events` と、別途取得した `high_impact_alerts`。
        """
        upcoming = [
            {"date": "2026-02-01", "title": "FOMC", "country": "US", "impact": "high"},
            {"date": "2026-02-02", "title": "小売売上", "country": "US", "impact": "medium"},
        ]
        alerts = [{"date": "2026-02-01", "title": "FOMC", "hours_until": 20}]
        result = self._run(upcoming=upcoming, alerts=alerts)

        assert result["upcoming_events"] == upcoming
        assert result["high_impact_alerts"] == alerts

    def test_limits_upcoming_events_to_eight(self):
        """今後のイベントは先頭 8 件までに絞ること"""
        upcoming = [{"date": f"2026-02-{i:02d}", "title": f"ev{i}",
                     "country": "US", "impact": "high"} for i in range(1, 21)]
        assert len(self._run(upcoming=upcoming)["upcoming_events"]) == 8

    def test_overview_summarizes_the_analysis(self):
        """概要文に指標数・バイアス・アラート件数を含めること"""
        overview = self._run(alerts=[{"title": "FOMC"}])["overview"]

        assert "USD/JPY" in overview
        assert "1指標" in overview
        assert "1件" in overview

    def test_score_reflects_the_indicator_votes(self):
        """スコアが指標の方向性の合計になること"""
        result = self._run(fundamental={
            "cpi": {"label": "CPI", "data": [{"value": 3.5, "forecast": 3.0}]},
            "us_employment": {"label": "雇用統計", "data": [{"value": 250, "forecast": 200}]},
        })
        assert result["score"] == 2

    def test_refreshes_the_calendar_first(self):
        """分析前に経済カレンダーを更新すること"""
        with patch("src.analysis.fundamental.refresh_economic_calendar",
                   new=AsyncMock(return_value=[])) as refresh, \
             patch("src.analysis.economic.get_fundamental_data", new=AsyncMock(return_value={})), \
             patch("src.analysis.economic.get_upcoming_events", return_value=[]), \
             patch("src.analysis.economic.get_event_alerts", return_value=[]):
            asyncio.run(analyze_economic("USDJPY"))

        refresh.assert_awaited_once()
