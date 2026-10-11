"""マーケットコンテキスト — src.analysis.market_context のテスト

1 リクエスト内で OHLCV と指標計算を共有するためのデータクラスを検証する。
"""

from unittest.mock import patch

import pandas as pd
import pytest

from src.analysis.market_context import MarketContext
from src.analysis.technical import compute_all_indicators
from src.analysis.volatility import calc_atr
from tests.conftest import make_ohlcv


@pytest.fixture
def context(ohlcv) -> MarketContext:
    """指標計算済みのコンテキストを返す。"""
    return MarketContext("USDJPY", 200, "database", compute_all_indicators(ohlcv.copy()))


class TestLoad:
    """MarketContext.load() のテスト"""

    def test_fetches_and_computes_indicators(self, ohlcv):
        """OHLCV を取得して指標を計算した DataFrame を保持すること"""
        with patch("src.analysis.market_context.get_ohlcv_data",
                   return_value=(ohlcv, "database")) as get_data:
            ctx = MarketContext.load("USDJPY", days=120)

        get_data.assert_called_once_with("USDJPY", 120)
        assert "rsi" in ctx.result_df.columns
        assert "macd" in ctx.result_df.columns

    def test_normalizes_symbol_to_uppercase(self, ohlcv):
        """シンボルを大文字に正規化すること"""
        with patch("src.analysis.market_context.get_ohlcv_data", return_value=(ohlcv, "database")):
            assert MarketContext.load("usdjpy").symbol == "USDJPY"

    def test_records_days_and_source(self, ohlcv):
        """取得日数とデータソースを保持すること"""
        with patch("src.analysis.market_context.get_ohlcv_data",
                   return_value=(ohlcv, "yahoo_finance")):
            ctx = MarketContext.load("USDJPY", days=90)

        assert ctx.days == 90
        assert ctx.source == "yahoo_finance"

    def test_defaults_to_200_days(self, ohlcv):
        """既定の取得日数は 200 日であること"""
        with patch("src.analysis.market_context.get_ohlcv_data",
                   return_value=(ohlcv, "database")) as get_data:
            MarketContext.load("USDJPY")

        assert get_data.call_args[0][1] == 200

    def test_indicators_are_computed_once(self, ohlcv):
        """指標計算は読み込み時に 1 回だけ行うこと（再利用のための設計）"""
        with patch("src.analysis.market_context.get_ohlcv_data", return_value=(ohlcv, "database")), \
             patch("src.analysis.market_context.compute_all_indicators",
                   side_effect=compute_all_indicators) as compute:
            ctx = MarketContext.load("USDJPY")
            _ = ctx.price
            _ = ctx.atr

        compute.assert_called_once()


class TestPrice:
    """price プロパティのテスト"""

    def test_returns_latest_close(self, context, ohlcv):
        """最終行の終値を返すこと"""
        assert context.price == pytest.approx(float(ohlcv["close"].iloc[-1]))

    def test_returns_a_plain_float(self, context):
        """numpy 型ではなく Python の float を返すこと"""
        assert type(context.price) is float


class TestAtr:
    """atr プロパティのテスト"""

    def test_matches_calc_atr(self, context):
        """volatility.calc_atr() と同じ値を返すこと"""
        assert context.atr == pytest.approx(calc_atr(context.result_df))

    def test_is_non_negative(self, context):
        """ATR は 0 以上であること"""
        assert context.atr >= 0

    def test_returns_zero_for_insufficient_data(self):
        """データが少ない場合は 0.0 を返すこと（例外にしない）"""
        short = compute_all_indicators(make_ohlcv(n=5))
        assert MarketContext("USDJPY", 5, "sample", short).atr == 0.0


class TestDataclassBehaviour:
    """データクラスとしての振る舞いのテスト"""

    def test_fields_are_accessible(self, context):
        """4 つのフィールドを保持すること"""
        assert context.symbol == "USDJPY"
        assert context.days == 200
        assert context.source == "database"
        assert isinstance(context.result_df, pd.DataFrame)

    def test_can_be_constructed_directly(self, ohlcv):
        """テストや再利用のため直接生成できること"""
        ctx = MarketContext("EURUSD", 90, "sample", compute_all_indicators(ohlcv.copy()))
        assert ctx.symbol == "EURUSD"
