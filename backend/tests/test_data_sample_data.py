"""サンプル市場データ生成 — src.data.sample_data のテスト

外部データ源が使えない環境でのフォールバックとして、
決定論的かつ分析処理に耐える形状のデータを返すことを検証する。
"""

import pandas as pd
import pytest

from src.analysis.technical import compute_all_indicators
from src.data.sample_data import SYMBOL_BASE_PRICES, generate_sample_ohlcv


class TestSymbolBasePrices:
    """SYMBOL_BASE_PRICES のテスト"""

    def test_covers_the_major_pairs(self):
        """主要 4 通貨ペアを定義していること"""
        assert set(SYMBOL_BASE_PRICES) == {"USDJPY", "EURUSD", "GBPUSD", "AUDUSD"}

    def test_prices_are_realistic(self):
        """基準価格が現実的な水準であること"""
        assert SYMBOL_BASE_PRICES["USDJPY"] > 100      # 円は 3 桁
        assert 0.5 < SYMBOL_BASE_PRICES["EURUSD"] < 2  # ドルストレートは 1 前後

    def test_all_prices_are_positive(self):
        """すべて正の価格であること"""
        assert all(p > 0 for p in SYMBOL_BASE_PRICES.values())


class TestGenerateSampleOhlcv:
    """generate_sample_ohlcv() のテスト"""

    def test_returns_expected_columns(self):
        """OHLCV とタイムスタンプの列を持つこと"""
        df = generate_sample_ohlcv()
        assert list(df.columns) == ["timestamp", "open", "high", "low", "close", "volume"]

    def test_row_count_matches_days(self):
        """指定した本数のデータを返すこと"""
        assert len(generate_sample_ohlcv(days=50)) == 50

    def test_defaults_to_200_rows(self):
        """既定では指標計算に足りる 200 本を返すこと"""
        assert len(generate_sample_ohlcv()) == 200

    def test_prices_are_deterministic(self):
        """同じ引数なら常に同じ価格系列を返すこと（乱数シード固定）"""
        price_columns = ["open", "high", "low", "close", "volume"]
        pd.testing.assert_frame_equal(
            generate_sample_ohlcv()[price_columns],
            generate_sample_ohlcv()[price_columns],
        )

    def test_timestamps_are_anchored_to_now(self):
        """タイムスタンプは呼び出し時点を終端とすること

        価格は決定論的だが、日付軸は `pd.Timestamp.now()` を基準にしているため
        呼び出しごとに動く（スナップショット比較には使えない）。
        """
        last = generate_sample_ohlcv(days=5)["timestamp"].iloc[-1]

        assert abs((pd.Timestamp.now() - last).total_seconds()) < 60

    def test_ohlc_relationships_hold(self):
        """高値 >= 始値・終値 >= 安値 の関係が崩れないこと"""
        df = generate_sample_ohlcv(days=100)
        assert (df["high"] >= df["low"]).all()
        assert (df["high"] >= df["close"]).all()
        assert (df["high"] >= df["open"]).all()
        assert (df["low"] <= df["close"]).all()
        assert (df["low"] <= df["open"]).all()

    def test_prices_stay_positive(self):
        """価格が負にならないこと"""
        df = generate_sample_ohlcv(days=200)
        assert (df[["open", "high", "low", "close"]] > 0).all().all()

    def test_starts_near_the_base_price(self):
        """初期価格が基準価格の近傍にあること"""
        df = generate_sample_ohlcv(base_price=150.0, days=10)
        assert 140 < df["close"].iloc[0] < 160

    def test_respects_a_custom_base_price(self):
        """基準価格を変えると水準も変わること"""
        eur = generate_sample_ohlcv(symbol="EURUSD", base_price=1.08, days=10)
        assert 0.9 < eur["close"].iloc[0] < 1.2

    def test_timestamps_are_business_days_in_order(self):
        """タイムスタンプが営業日で昇順に並ぶこと"""
        ts = generate_sample_ohlcv(days=30)["timestamp"]
        assert ts.is_monotonic_increasing
        assert (ts.dt.dayofweek < 5).all()

    def test_volume_is_a_positive_integer(self):
        """出来高は正の整数であること"""
        volumes = generate_sample_ohlcv(days=30)["volume"]
        assert (volumes > 0).all()
        assert volumes.dtype.kind in "iu"

    def test_prices_are_rounded_to_three_decimals(self):
        """価格は小数 3 桁に丸めること"""
        df = generate_sample_ohlcv(days=10)
        assert (df["close"] == df["close"].round(3)).all()

    def test_output_supports_indicator_calculation(self):
        """生成データでテクニカル指標を計算できること（分析フォールバックの要件）"""
        df = generate_sample_ohlcv(days=200).set_index("timestamp")
        result = compute_all_indicators(df)
        assert not pd.isna(result["rsi"].iloc[-1])
        assert not pd.isna(result["sma_50"].iloc[-1])

    def test_prices_actually_vary(self):
        """値動きがあること（定数列ではない）"""
        assert generate_sample_ohlcv(days=100)["close"].std() > 0
