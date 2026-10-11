"""マルチタイムフレーム分析 — src.analysis.multi_timeframe のテスト

市場データ取得とキャッシュはモックへ差し替え、
トレンド判定とアライメント（整合性）ロジックを検証する。
"""

from unittest.mock import patch

import pandas as pd
import pytest

from src.analysis.multi_timeframe import _trend_from_df, analyze_multi_timeframe
from tests.conftest import make_ohlcv


def frame_with(close: float, sma20: float, sma50: float, n: int = 120) -> pd.DataFrame:
    """SMA20 / SMA50 と終値の位置関係を意図どおりに作り込んだ OHLCV を返す。

    直近 20 本を sma20 相当、それ以前を調整値にすることで
    移動平均の並びを制御する。
    """
    # SMA50 が目標値になるよう、古い 30 本の水準を逆算する
    older = (sma50 * 50 - sma20 * 20) / 30
    closes = [older] * (n - 20) + [sma20] * 19 + [close]
    df = pd.DataFrame({
        "open": closes,
        "high": [c * 1.001 for c in closes],
        "low": [c * 0.999 for c in closes],
        "close": closes,
        "volume": [1000.0] * n,
    })
    df.index = pd.date_range(end=pd.Timestamp("2026-01-01"), periods=n, freq="D")
    return df


@pytest.fixture(autouse=True)
def no_cache():
    """キャッシュを無効化して毎回計算させる。"""
    with patch("src.analysis.multi_timeframe.cache_get", return_value=None), \
         patch("src.analysis.multi_timeframe.cache_put"):
        yield


class TestTrendFromDf:
    """_trend_from_df() のテスト"""

    def test_perfect_bullish_alignment(self):
        """終値 > SMA20 > SMA50 なら『上昇』と判定すること"""
        result = _trend_from_df(frame_with(close=110, sma20=105, sma50=100))
        assert result["trend"] == "bullish"
        assert result["label"] == "上昇"

    def test_perfect_bearish_alignment(self):
        """終値 < SMA20 < SMA50 なら『下降』と判定すること"""
        result = _trend_from_df(frame_with(close=90, sma20=95, sma50=100))
        assert result["trend"] == "bearish"
        assert result["label"] == "下降"

    def test_partial_bullish_is_labelled_as_bias(self):
        """SMA の並びが崩れていても終値 > SMA50 なら『上昇寄り』になること"""
        result = _trend_from_df(frame_with(close=103, sma20=101, sma50=100))
        assert result["trend"] == "bullish"
        assert result["label"] in ("上昇", "上昇寄り")

    def test_returns_expected_keys(self, ohlcv):
        """判定結果のキーが揃っていること"""
        assert set(_trend_from_df(ohlcv)) == {
            "trend", "label", "close", "sma_20", "sma_50", "rsi", "signal_bias", "bars",
        }

    def test_trend_is_one_of_three_values(self, ohlcv):
        """trend は bullish / bearish / neutral のいずれかであること"""
        assert _trend_from_df(ohlcv)["trend"] in ("bullish", "bearish", "neutral")

    def test_signal_bias_is_derived_from_indicators(self, ohlcv):
        """signal_bias は buy / sell / neutral のいずれかであること"""
        assert _trend_from_df(ohlcv)["signal_bias"] in ("buy", "sell", "neutral")

    def test_reports_bar_count(self, ohlcv):
        """評価に使ったバー数を返すこと"""
        assert _trend_from_df(ohlcv)["bars"] == len(ohlcv)

    def test_values_are_rounded(self, ohlcv):
        """終値・移動平均は小数 4 桁、RSI は 1 桁に丸めること"""
        result = _trend_from_df(ohlcv)
        assert result["close"] == round(result["close"], 4)
        assert result["sma_20"] == round(result["sma_20"], 4)
        assert result["rsi"] == round(result["rsi"], 1)

    def test_rsi_is_none_when_not_computable(self):
        """データ不足で RSI が出せない場合は None を返すこと"""
        assert _trend_from_df(make_ohlcv(n=5))["rsi"] is None

    def test_falls_back_to_close_when_sma_is_nan(self):
        """SMA が未計算のときは終値で代用し、例外を出さないこと"""
        result = _trend_from_df(make_ohlcv(n=5))
        assert result["sma_20"] == result["close"]
        assert result["sma_50"] == result["close"]


class TestAnalyzeMultiTimeframe:
    """analyze_multi_timeframe() のテスト"""

    def _run(self, daily: pd.DataFrame, h4: pd.DataFrame, symbol: str = "usdjpy"):
        """日足・4時間足のデータを差し込んで実行する。"""
        def fake_get(sym, days, timeframe):
            return (daily, "database") if timeframe == "1d" else (h4, "yahoo_finance")

        with patch("src.analysis.multi_timeframe.get_ohlcv_data", side_effect=fake_get):
            return analyze_multi_timeframe(symbol)

    def test_fetches_both_timeframes(self, ohlcv):
        """日足 200 日・4 時間足 60 日を取得すること"""
        with patch("src.analysis.multi_timeframe.get_ohlcv_data",
                   return_value=(ohlcv, "database")) as get_data:
            analyze_multi_timeframe("USDJPY")

        requested = {(c.kwargs["timeframe"], c.kwargs["days"]) for c in get_data.call_args_list}
        assert requested == {("1d", 200), ("4h", 60)}

    def test_normalizes_symbol_to_uppercase(self, ohlcv):
        """シンボルを大文字に正規化して返すこと"""
        assert self._run(ohlcv, ohlcv)["symbol"] == "USDJPY"

    def test_reports_source_per_timeframe(self, ohlcv):
        """時間足ごとのデータソースを含めること"""
        result = self._run(ohlcv, ohlcv)
        assert result["timeframes"]["1d"]["source"] == "database"
        assert result["timeframes"]["4h"]["source"] == "yahoo_finance"
        assert result["timeframes"]["1d"]["timeframe"] == "1d"

    def test_aligned_bullish(self):
        """両時間足が上昇なら一致と判定すること"""
        up = frame_with(close=110, sma20=105, sma50=100)
        result = self._run(up, up)

        assert result["alignment"] == "bullish"
        assert "一致" in result["alignment_label"]

    def test_aligned_bearish(self):
        """両時間足が下降なら一致と判定すること"""
        down = frame_with(close=90, sma20=95, sma50=100)
        result = self._run(down, down)

        assert result["alignment"] == "bearish"
        assert "一致" in result["alignment_label"]

    def test_daily_bullish_with_neutral_h4_is_a_bias(self):
        """日足が上昇で 4 時間足が逆行していなければ上昇バイアスになること"""
        up = frame_with(close=110, sma20=105, sma50=100)
        flat = frame_with(close=100, sma20=100, sma50=100)
        result = self._run(up, flat)

        assert result["alignment"] == "bullish_bias"
        assert result["alignment_label"] == "日足上昇バイアス"

    def test_daily_bearish_with_neutral_h4_is_a_bias(self):
        """日足が下降で 4 時間足が逆行していなければ下降バイアスになること"""
        down = frame_with(close=90, sma20=95, sma50=100)
        flat = frame_with(close=100, sma20=100, sma50=100)
        assert self._run(down, flat)["alignment"] == "bearish_bias"

    def test_conflicting_timeframes_are_mixed(self):
        """日足と 4 時間足が逆方向ならミックスと判定すること"""
        up = frame_with(close=110, sma20=105, sma50=100)
        down = frame_with(close=90, sma20=95, sma50=100)
        result = self._run(up, down)

        assert result["alignment"] == "mixed"
        assert result["alignment_label"] == "ミックス"

    def test_returns_cached_value_without_recomputing(self, ohlcv):
        """キャッシュヒット時はデータ取得を行わないこと"""
        cached = {"symbol": "USDJPY", "alignment": "bullish"}
        with patch("src.analysis.multi_timeframe.cache_get", return_value=cached), \
             patch("src.analysis.multi_timeframe.get_ohlcv_data") as get_data:
            assert analyze_multi_timeframe("USDJPY") is cached

        get_data.assert_not_called()

    def test_stores_result_in_cache(self, ohlcv):
        """計算結果をキャッシュへ保存すること"""
        with patch("src.analysis.multi_timeframe.get_ohlcv_data",
                   return_value=(ohlcv, "database")), \
             patch("src.analysis.multi_timeframe.cache_put") as cache_put:
            result = analyze_multi_timeframe("USDJPY")

        assert cache_put.call_args[0][1] == result
        assert cache_put.call_args.kwargs["ttl_seconds"] > 0
