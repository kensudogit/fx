"""テクニカル指標の計算 — src.analysis.technical のテスト

各指標を既知の入力に対して手計算値と突き合わせ、
ウォームアップ期間（先頭の NaN）と出力形状も検証する。
"""

import numpy as np
import pandas as pd
import pytest

from src.analysis.technical import (
    bollinger_bands,
    compute_all_indicators,
    exponential_moving_average,
    ichimoku,
    macd,
    moving_average,
    rsi,
    series_to_list,
    stochastic,
)
from tests.conftest import make_ohlcv


@pytest.fixture
def ramp() -> pd.Series:
    """1, 2, 3, ... という単調増加の系列（手計算しやすい）。"""
    return pd.Series([float(i) for i in range(1, 21)])


class TestMovingAverage:
    """moving_average()（単純移動平均）のテスト"""

    def test_matches_manual_average(self, ramp):
        """直近 n 本の単純平均になること"""
        sma = moving_average(ramp, period=5)
        assert sma.iloc[4] == pytest.approx(3.0)      # (1+2+3+4+5)/5
        assert sma.iloc[-1] == pytest.approx(18.0)    # (16+…+20)/5

    def test_warmup_period_is_nan(self, ramp):
        """先頭 period-1 本は NaN であること"""
        sma = moving_average(ramp, period=5)
        assert sma.iloc[:4].isna().all()
        assert not np.isnan(sma.iloc[4])

    def test_preserves_length_and_index(self, ramp):
        """入力と同じ長さ・インデックスで返すこと"""
        sma = moving_average(ramp, period=5)
        assert len(sma) == len(ramp)
        assert sma.index.equals(ramp.index)

    def test_constant_series_equals_the_constant(self):
        """定数系列の移動平均はその定数になること"""
        s = pd.Series([7.0] * 30)
        assert moving_average(s, 10).dropna().eq(7.0).all()

    def test_period_longer_than_data_is_all_nan(self, ramp):
        """データ数より長い期間を指定すると全て NaN になること"""
        assert moving_average(ramp, period=100).isna().all()


class TestExponentialMovingAverage:
    """exponential_moving_average()（指数移動平均）のテスト"""

    def test_first_value_equals_first_price(self, ramp):
        """先頭は最初の価格そのものになること（pandas の ewm の仕様）"""
        assert exponential_moving_average(ramp, 5).iloc[0] == pytest.approx(1.0)

    def test_matches_recursive_formula(self, ramp):
        """EMA(t) = α·P(t) + (1-α)·EMA(t-1) を満たすこと"""
        period = 5
        alpha = 2 / (period + 1)
        ema = exponential_moving_average(ramp, period)
        expected = alpha * ramp.iloc[3] + (1 - alpha) * ema.iloc[2]
        assert ema.iloc[3] == pytest.approx(expected)

    def test_reacts_faster_than_sma(self):
        """急騰時は SMA より速く追随すること"""
        s = pd.Series([10.0] * 20 + [20.0] * 5)
        assert exponential_moving_average(s, 10).iloc[-1] > moving_average(s, 10).iloc[-1]

    def test_has_no_nan(self, ramp):
        """min_periods を指定しないため NaN を含まないこと"""
        assert not exponential_moving_average(ramp, 5).isna().any()


class TestBollingerBands:
    """bollinger_bands() のテスト"""

    def test_returns_three_bands(self, ramp):
        """upper / middle / lower の 3 本を返すこと"""
        assert set(bollinger_bands(ramp)) == {"upper", "middle", "lower"}

    def test_middle_is_the_sma(self, ramp):
        """中心線は同期間の SMA と一致すること"""
        bb = bollinger_bands(ramp, period=5)
        pd.testing.assert_series_equal(bb["middle"], moving_average(ramp, 5), check_names=False)

    def test_bands_are_ordered(self, ohlcv):
        """常に lower < middle < upper であること"""
        bb = bollinger_bands(ohlcv["close"])
        valid = bb["upper"].notna()
        assert (bb["upper"][valid] > bb["middle"][valid]).all()
        assert (bb["middle"][valid] > bb["lower"][valid]).all()

    def test_band_width_scales_with_std_dev(self, ohlcv):
        """標準偏差の倍率を上げるとバンド幅が広がること"""
        narrow = bollinger_bands(ohlcv["close"], std_dev=1.0)
        wide = bollinger_bands(ohlcv["close"], std_dev=3.0)
        n_width = (narrow["upper"] - narrow["lower"]).dropna().mean()
        w_width = (wide["upper"] - wide["lower"]).dropna().mean()
        assert w_width == pytest.approx(n_width * 3, rel=0.01)

    def test_flat_series_collapses_the_bands(self):
        """変動のない系列ではバンド幅がゼロになること"""
        s = pd.Series([100.0] * 40)
        bb = bollinger_bands(s)
        assert (bb["upper"].dropna() == bb["lower"].dropna()).all()


class TestMacd:
    """macd() のテスト"""

    def test_returns_three_series(self, ohlcv):
        """macd / signal / histogram を返すこと"""
        assert set(macd(ohlcv["close"])) == {"macd", "signal", "histogram"}

    def test_macd_line_is_fast_minus_slow_ema(self, ohlcv):
        """MACD 線は短期 EMA − 長期 EMA であること"""
        close = ohlcv["close"]
        expected = exponential_moving_average(close, 12) - exponential_moving_average(close, 26)
        pd.testing.assert_series_equal(macd(close)["macd"], expected, check_names=False)

    def test_histogram_is_macd_minus_signal(self, ohlcv):
        """ヒストグラムは MACD − シグナルであること"""
        m = macd(ohlcv["close"])
        pd.testing.assert_series_equal(m["histogram"], m["macd"] - m["signal"], check_names=False)

    def test_positive_in_an_uptrend(self, ohlcv_uptrend):
        """上昇トレンドでは MACD が正になること"""
        assert macd(ohlcv_uptrend["close"])["macd"].iloc[-1] > 0

    def test_negative_in_a_downtrend(self, ohlcv_downtrend):
        """下降トレンドでは MACD が負になること"""
        assert macd(ohlcv_downtrend["close"])["macd"].iloc[-1] < 0

    def test_custom_periods_are_honoured(self, ohlcv):
        """期間を変えると結果も変わること"""
        default = macd(ohlcv["close"])["macd"].iloc[-1]
        custom = macd(ohlcv["close"], fast_period=5, slow_period=35)["macd"].iloc[-1]
        assert default != pytest.approx(custom)


class TestRsi:
    """rsi() のテスト"""

    def test_stays_within_bounds(self, ohlcv):
        """0〜100 の範囲に収まること"""
        values = rsi(ohlcv["close"]).dropna()
        assert values.between(0, 100).all()

    def test_warmup_period_is_nan(self, ohlcv):
        """先頭 period 本は NaN であること"""
        assert rsi(ohlcv["close"], period=14).iloc[:13].isna().all()

    def test_monotonic_rise_saturates_at_100(self):
        """一方的な上昇では 100 に張り付くこと（損失がゼロのため）"""
        s = pd.Series([float(i) for i in range(1, 60)])
        assert rsi(s).iloc[-1] == pytest.approx(100.0)

    def test_monotonic_fall_saturates_at_0(self):
        """一方的な下落では 0 に張り付くこと"""
        s = pd.Series([float(i) for i in range(60, 1, -1)])
        assert rsi(s).iloc[-1] == pytest.approx(0.0)

    def test_uptrend_reads_higher_than_downtrend(self, ohlcv_uptrend, ohlcv_downtrend):
        """上昇トレンドの RSI は下降トレンドより高いこと"""
        assert rsi(ohlcv_uptrend["close"]).iloc[-1] > rsi(ohlcv_downtrend["close"]).iloc[-1]

    def test_shorter_period_is_more_volatile(self, ohlcv):
        """期間が短いほど値の振れ幅が大きいこと"""
        assert rsi(ohlcv["close"], 5).dropna().std() > rsi(ohlcv["close"], 30).dropna().std()


class TestStochastic:
    """stochastic() のテスト"""

    def test_returns_k_and_d(self, ohlcv):
        """%K と %D を返すこと"""
        assert set(stochastic(ohlcv["high"], ohlcv["low"], ohlcv["close"])) == {"k", "d"}

    def test_stays_within_bounds(self, ohlcv):
        """0〜100 の範囲に収まること"""
        st = stochastic(ohlcv["high"], ohlcv["low"], ohlcv["close"])
        assert st["k"].dropna().between(0, 100).all()
        assert st["d"].dropna().between(0, 100).all()

    def test_k_is_100_at_period_high(self):
        """期間高値で引けると %K が 100 になること"""
        high = pd.Series([10.0] * 20)
        low = pd.Series([0.0] * 20)
        close = pd.Series([5.0] * 19 + [10.0])
        assert stochastic(high, low, close)["k"].iloc[-1] == pytest.approx(100.0)

    def test_k_is_0_at_period_low(self):
        """期間安値で引けると %K が 0 になること"""
        high = pd.Series([10.0] * 20)
        low = pd.Series([0.0] * 20)
        close = pd.Series([5.0] * 19 + [0.0])
        assert stochastic(high, low, close)["k"].iloc[-1] == pytest.approx(0.0)

    def test_d_is_the_moving_average_of_k(self, ohlcv):
        """%D は %K の移動平均であること"""
        st = stochastic(ohlcv["high"], ohlcv["low"], ohlcv["close"], d_period=3)
        pd.testing.assert_series_equal(st["d"], st["k"].rolling(3).mean(), check_names=False)


class TestIchimoku:
    """ichimoku()（一目均衡表）のテスト"""

    def test_returns_all_five_lines(self, ohlcv):
        """転換線・基準線・先行スパン A/B・遅行スパンを返すこと"""
        ichi = ichimoku(ohlcv["high"], ohlcv["low"], ohlcv["close"])
        assert set(ichi) == {"tenkan", "kijun", "senkou_a", "senkou_b", "chikou"}

    def test_tenkan_is_midpoint_of_recent_range(self, ohlcv):
        """転換線は直近 9 本の高値・安値の中央値であること"""
        ichi = ichimoku(ohlcv["high"], ohlcv["low"], ohlcv["close"])
        expected = (ohlcv["high"].rolling(9).max() + ohlcv["low"].rolling(9).min()) / 2
        pd.testing.assert_series_equal(ichi["tenkan"], expected, check_names=False)

    def test_senkou_lines_are_shifted_forward(self, ohlcv):
        """先行スパンは未来方向へずらすため、先頭に NaN が増えること"""
        ichi = ichimoku(ohlcv["high"], ohlcv["low"], ohlcv["close"])
        assert ichi["senkou_a"].isna().sum() > ichi["tenkan"].isna().sum()

    def test_chikou_is_shifted_backward(self, ohlcv):
        """遅行スパンは過去方向へずらすため、末尾が NaN になること"""
        ichi = ichimoku(ohlcv["high"], ohlcv["low"], ohlcv["close"])
        assert pd.isna(ichi["chikou"].iloc[-1])

    def test_all_lines_keep_input_length(self, ohlcv):
        """すべての線が入力と同じ長さであること"""
        ichi = ichimoku(ohlcv["high"], ohlcv["low"], ohlcv["close"])
        assert all(len(s) == len(ohlcv) for s in ichi.values())


class TestComputeAllIndicators:
    """compute_all_indicators() のテスト"""

    EXPECTED_COLUMNS = [
        "sma_20", "sma_50", "ema_12", "ema_26",
        "bb_upper", "bb_middle", "bb_lower",
        "macd", "macd_signal", "macd_histogram",
        "rsi", "stoch_k", "stoch_d",
    ]

    def test_adds_all_indicator_columns(self, ohlcv):
        """想定する指標列をすべて追加すること"""
        result = compute_all_indicators(ohlcv.copy())
        for column in self.EXPECTED_COLUMNS:
            assert column in result.columns

    def test_adds_ichimoku_columns(self, ohlcv):
        """一目均衡表の列を ichi_ プレフィックスで追加すること"""
        result = compute_all_indicators(ohlcv.copy())
        for key in ("tenkan", "kijun", "senkou_a", "senkou_b", "chikou"):
            assert f"ichi_{key}" in result.columns

    def test_keeps_original_ohlcv_columns(self, ohlcv):
        """元の OHLCV 列を保持すること"""
        result = compute_all_indicators(ohlcv.copy())
        for column in ("open", "high", "low", "close", "volume"):
            assert column in result.columns

    def test_does_not_mutate_the_input(self, ohlcv):
        """入力 DataFrame を破壊しないこと"""
        original = ohlcv.copy()
        compute_all_indicators(original)
        assert list(original.columns) == list(ohlcv.columns)

    def test_preserves_row_count(self, ohlcv):
        """行数を変えないこと"""
        assert len(compute_all_indicators(ohlcv.copy())) == len(ohlcv)

    def test_latest_row_has_usable_values(self, ohlcv):
        """ウォームアップ後の最新行には主要指標の値が入っていること"""
        latest = compute_all_indicators(ohlcv.copy()).iloc[-1]
        for column in ("sma_20", "sma_50", "rsi", "macd", "bb_upper"):
            assert not pd.isna(latest[column])

    def test_short_history_yields_nan_for_long_indicators(self):
        """データが少ないと長期指標は NaN のままであること"""
        short = make_ohlcv(n=10)
        result = compute_all_indicators(short)
        assert result["sma_50"].isna().all()


class TestSeriesToList:
    """series_to_list() のテスト（JSON 化のための変換）"""

    def test_converts_nan_to_none(self):
        """NaN は JSON で扱える None にすること"""
        assert series_to_list(pd.Series([1.0, np.nan, 3.0])) == [1.0, None, 3.0]

    def test_rounds_to_six_decimals(self):
        """小数 6 桁に丸めること（レスポンスサイズの抑制）"""
        assert series_to_list(pd.Series([1.23456789])) == [1.234568]

    def test_returns_plain_floats(self):
        """numpy 型ではなく Python の float を返すこと"""
        values = series_to_list(pd.Series(np.array([1.5, 2.5], dtype=np.float32)))
        assert all(type(v) is float for v in values)

    def test_empty_series_returns_empty_list(self):
        """空の系列は空リストになること"""
        assert series_to_list(pd.Series([], dtype=float)) == []

    def test_all_nan_series(self):
        """全て NaN なら全て None になること"""
        assert series_to_list(pd.Series([np.nan] * 3)) == [None, None, None]
