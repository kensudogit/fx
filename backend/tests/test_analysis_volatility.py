"""ATR・ボラティリティ計算 — src.analysis.volatility のテスト"""

import numpy as np
import pandas as pd
import pytest

from src.analysis.volatility import calc_atr, calc_volatility_stats
from tests.conftest import make_ohlcv


def frame(highs, lows, closes) -> pd.DataFrame:
    """high / low / close を明示した DataFrame を作る。"""
    return pd.DataFrame({"high": highs, "low": lows, "close": closes})


class TestCalcAtr:
    """calc_atr() のテスト"""

    def test_constant_range_gives_that_range(self):
        """毎バーの値幅が一定なら ATR はその値幅になること"""
        n = 30
        df = frame([101.0] * n, [100.0] * n, [100.5] * n)
        assert calc_atr(df, period=14) == pytest.approx(1.0)

    def test_accounts_for_gaps(self):
        """ギャップ（前終値からの飛び）を True Range に含めること"""
        # 最終バーは高安値幅 1.0 だが、前終値 100 からのギャップは 5.0
        highs = [101.0] * 19 + [105.0]
        lows = [100.0] * 19 + [104.0]
        closes = [100.0] * 19 + [104.5]
        atr = calc_atr(frame(highs, lows, closes), period=2)
        # 値幅 1.0 だけで計算するより大きくなる
        assert atr > 1.0

    def test_zero_volatility_gives_zero(self):
        """まったく動かない市場では ATR が 0 になること"""
        n = 30
        assert calc_atr(frame([100.0] * n, [100.0] * n, [100.0] * n)) == 0.0

    def test_returns_zero_when_data_is_insufficient(self):
        """期間に満たないデータでは 0.0 を返すこと（NaN を返さない）"""
        df = frame([101.0] * 5, [100.0] * 5, [100.5] * 5)
        assert calc_atr(df, period=14) == 0.0

    def test_returns_a_plain_float(self):
        """numpy 型ではなく Python の float を返すこと（JSON 化のため）"""
        assert type(calc_atr(make_ohlcv())) is float

    def test_is_non_negative(self, ohlcv):
        """ATR は常に 0 以上であること"""
        assert calc_atr(ohlcv) >= 0

    def test_larger_for_a_more_volatile_market(self):
        """値動きが荒いほど ATR が大きくなること"""
        calm = make_ohlcv(seed=1)
        wild = calm.copy()
        wild["high"] = wild["close"] * 1.05
        wild["low"] = wild["close"] * 0.95
        assert calc_atr(wild) > calc_atr(calm)

    def test_shorter_period_reacts_faster(self):
        """期間が短いほど直近の変動を強く反映すること"""
        n = 40
        highs = [101.0] * 30 + [120.0] * 10
        lows = [100.0] * 30 + [100.0] * 10
        closes = [100.5] * 40
        df = frame(highs, lows, closes)
        assert calc_atr(df, period=5) > calc_atr(df, period=30)


class TestCalcVolatilityStats:
    """calc_volatility_stats() のテスト"""

    def test_returns_expected_keys(self, ohlcv):
        """atr / atr_percent / daily_volatility を返すこと"""
        assert set(calc_volatility_stats(ohlcv)) == {"atr", "atr_percent", "daily_volatility"}

    def test_atr_matches_calc_atr(self, ohlcv):
        """atr は calc_atr() の丸め値と一致すること"""
        stats = calc_volatility_stats(ohlcv)
        assert stats["atr"] == round(calc_atr(ohlcv), 4)

    def test_atr_percent_is_relative_to_last_close(self, ohlcv):
        """atr_percent は直近終値に対する比率（%）であること"""
        stats = calc_volatility_stats(ohlcv)
        expected = calc_atr(ohlcv) / float(ohlcv["close"].iloc[-1]) * 100
        assert stats["atr_percent"] == pytest.approx(round(expected, 3))

    def test_daily_volatility_is_stdev_of_returns(self, ohlcv):
        """daily_volatility は日次リターンの標準偏差（%）であること"""
        expected = ohlcv["close"].pct_change().dropna().std() * 100
        assert calc_volatility_stats(ohlcv)["daily_volatility"] == pytest.approx(
            round(float(expected), 3))

    def test_all_values_are_non_negative(self, ohlcv):
        """いずれの指標も 0 以上であること"""
        assert all(v >= 0 for v in calc_volatility_stats(ohlcv).values())

    def test_flat_market_yields_zeros(self):
        """まったく動かない市場では全指標が 0 になること"""
        n = 30
        stats = calc_volatility_stats(frame([100.0] * n, [100.0] * n, [100.0] * n))
        assert stats["atr"] == 0
        assert stats["atr_percent"] == 0
        assert stats["daily_volatility"] == 0

    def test_single_row_does_not_crash(self):
        """1 行しかなくても例外を投げないこと（リターンが計算できない）"""
        stats = calc_volatility_stats(frame([101.0], [100.0], [100.5]))
        assert stats["daily_volatility"] == 0
