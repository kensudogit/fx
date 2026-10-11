"""ポジションサイジング — src.analysis.position_sizing のテスト

固定リスク%法の計算が仕様どおりか、pip 換算が通貨ペアごとに正しいかを検証する。
"""

import pytest

from src.analysis.position_sizing import (
    calculate_position_size,
    pip_size,
    pip_value_per_lot_usd,
    pips_from_atr,
)


class TestPipSize:
    """pip_size() のテスト"""

    @pytest.mark.parametrize("symbol", ["USDJPY", "EURJPY", "GBPJPY", "AUDJPY"])
    def test_jpy_pairs_use_two_decimals(self, symbol):
        """JPY ペアの 1 pip は 0.01 であること"""
        assert pip_size(symbol) == 0.01

    @pytest.mark.parametrize("symbol", ["EURUSD", "GBPUSD", "AUDUSD", "EURGBP"])
    def test_other_pairs_use_four_decimals(self, symbol):
        """その他ペアの 1 pip は 0.0001 であること"""
        assert pip_size(symbol) == 0.0001

    def test_is_case_insensitive(self):
        """小文字で渡しても判定できること"""
        assert pip_size("usdjpy") == 0.01
        assert pip_size("eurusd") == 0.0001


class TestPipValuePerLot:
    """pip_value_per_lot_usd() のテスト"""

    def test_jpy_pair_converts_via_rate(self):
        """JPY ペアは現在レートで USD 換算すること"""
        # (100,000 × 0.01) ÷ 150.00 = 6.666...
        assert pip_value_per_lot_usd("USDJPY", 150.0) == pytest.approx(6.6667, abs=1e-4)

    def test_usd_quoted_pair_is_ten_dollars(self):
        """USD クォートペアは 1 pip = 10 USD であること"""
        assert pip_value_per_lot_usd("EURUSD", 1.08) == pytest.approx(10.0)

    def test_usd_quoted_value_is_independent_of_price(self):
        """USD クォートペアの pip 価値はレートに依存しないこと"""
        assert pip_value_per_lot_usd("GBPUSD", 1.2) == pip_value_per_lot_usd("GBPUSD", 1.4)

    def test_jpy_value_falls_as_rate_rises(self):
        """JPY ペアはレートが上がるほど pip の USD 価値が下がること"""
        assert pip_value_per_lot_usd("USDJPY", 160.0) < pip_value_per_lot_usd("USDJPY", 140.0)

    def test_zero_price_returns_zero(self):
        """レート 0 でも 0 除算にならないこと"""
        assert pip_value_per_lot_usd("USDJPY", 0) == 0.0

    def test_cross_pair_falls_back_to_nominal_value(self):
        """クロス円でも USD でもないペアは名目値にフォールバックすること"""
        assert pip_value_per_lot_usd("EURGBP", 0.85) == pytest.approx(10.0)


class TestPipsFromAtr:
    """pips_from_atr() のテスト"""

    def test_converts_atr_to_pips_for_usd_pair(self):
        """ATR × 乗数 ÷ pip で pip 幅に変換すること"""
        # (0.0060 × 1.5) ÷ 0.0001 = 90 pips
        assert pips_from_atr(0.0060, "EURUSD") == 90.0

    def test_converts_atr_to_pips_for_jpy_pair(self):
        """JPY ペアでも pip 換算できること"""
        # (0.90 × 1.5) ÷ 0.01 = 135 pips
        assert pips_from_atr(0.90, "USDJPY") == 135.0

    def test_multiplier_scales_linearly(self):
        """乗数に比例して広がること"""
        assert pips_from_atr(0.0060, "EURUSD", 3.0) == pytest.approx(
            pips_from_atr(0.0060, "EURUSD", 1.5) * 2)

    def test_rounds_to_one_decimal(self):
        """小数 1 桁に丸めること"""
        assert pips_from_atr(0.00123456, "EURUSD") == round(0.00123456 * 1.5 / 0.0001, 1)

    def test_zero_atr_gives_zero_pips(self):
        """ATR が 0 なら 0 pips になること"""
        assert pips_from_atr(0.0, "EURUSD") == 0.0


class TestCalculatePositionSize:
    """calculate_position_size() のテスト"""

    def test_fixed_fractional_math(self):
        """固定リスク%法どおりのロット数を返すこと

        残高 $10,000・リスク 1% → 許容損失 $100。
        EURUSD のストップ 20 pips、1 pip = $10 なので 1 ロットのリスクは $200。
        よって推奨ロットは 100 / 200 = 0.5。
        """
        result = calculate_position_size("EURUSD", 1.08, 10_000, 1.0, stop_pips=20)

        assert result["risk_amount_usd"] == 100.0
        assert result["pip_value_per_lot_usd"] == 10.0
        assert result["recommended_lots"] == 0.5
        assert result["max_loss_usd"] == pytest.approx(100.0)

    def test_lots_scale_with_balance(self):
        """残高が倍なら推奨ロットも倍になること"""
        small = calculate_position_size("EURUSD", 1.08, 10_000, 1.0, stop_pips=20)
        large = calculate_position_size("EURUSD", 1.08, 20_000, 1.0, stop_pips=20)
        assert large["recommended_lots"] == pytest.approx(small["recommended_lots"] * 2)

    def test_lots_shrink_as_stop_widens(self):
        """ストップが広いほどロットは小さくなること"""
        tight = calculate_position_size("EURUSD", 1.08, 10_000, 1.0, stop_pips=20)
        wide = calculate_position_size("EURUSD", 1.08, 10_000, 1.0, stop_pips=80)
        assert wide["recommended_lots"] < tight["recommended_lots"]

    def test_lots_scale_with_risk_percent(self):
        """リスク%を上げるとロットも増えること"""
        low = calculate_position_size("EURUSD", 1.08, 10_000, 1.0, stop_pips=20)
        high = calculate_position_size("EURUSD", 1.08, 10_000, 2.0, stop_pips=20)
        assert high["recommended_lots"] > low["recommended_lots"]

    def test_uses_atr_when_stop_is_not_given(self):
        """ストップ未指定なら ATR ベースで算出すること"""
        result = calculate_position_size("EURUSD", 1.08, 10_000, 1.0, atr=0.0060)

        assert result["stop_pips"] == 90.0
        assert result["atr_based_stop"] is True

    @pytest.mark.parametrize("symbol,expected", [("USDJPY", 30.0), ("EURUSD", 20.0)])
    def test_falls_back_to_default_stop(self, symbol, expected):
        """ストップも ATR も無ければ通貨ペアごとの既定値を使うこと"""
        result = calculate_position_size(symbol, 150.0, 10_000, 1.0)

        assert result["stop_pips"] == expected
        assert result["atr_based_stop"] is False

    @pytest.mark.parametrize("stop", [0, -10])
    def test_non_positive_stop_is_ignored(self, stop):
        """0 以下のストップ指定は無効として既定値へ切り替えること"""
        assert calculate_position_size("EURUSD", 1.08, 10_000, 1.0, stop_pips=stop)["stop_pips"] == 20.0

    def test_lots_have_a_floor(self):
        """残高が極端に小さくても最小ロット 0.01 を下回らないこと"""
        result = calculate_position_size("EURUSD", 1.08, 10, 0.1, stop_pips=100)
        assert result["recommended_lots"] == 0.01

    def test_lots_have_a_ceiling(self):
        """残高が極端に大きくても 100 ロットで頭打ちにすること"""
        result = calculate_position_size("EURUSD", 1.08, 1_000_000_000, 10.0, stop_pips=1)
        assert result["recommended_lots"] == 100.0

    def test_take_profit_is_twice_the_stop(self):
        """利確目安はストップの 2 倍（リスクリワード 1:2）であること"""
        result = calculate_position_size("EURUSD", 1.08, 10_000, 1.0, stop_pips=25)
        assert result["suggested_take_profit_pips"] == 50.0

    def test_notional_reflects_lot_size(self):
        """名目金額は 1 ロット = 100,000 通貨で計算すること"""
        result = calculate_position_size("EURUSD", 1.08, 10_000, 1.0, stop_pips=20)
        assert result["position_notional_usd"] == result["recommended_lots"] * 100_000

    def test_symbol_is_normalized_to_uppercase(self):
        """シンボルは大文字に正規化して返すこと"""
        assert calculate_position_size("eurusd", 1.08, 10_000, 1.0)["symbol"] == "EURUSD"

    def test_zero_price_does_not_crash(self):
        """レート 0 でも例外を投げず最小ロットを返すこと"""
        result = calculate_position_size("USDJPY", 0, 10_000, 1.0, stop_pips=30)
        assert result["recommended_lots"] == 0.01

    def test_result_contains_all_expected_keys(self):
        """レスポンスのキーが揃っていること（フロントエンドの表示項目）"""
        result = calculate_position_size("USDJPY", 150.0, 10_000, 1.0)
        assert set(result) == {
            "symbol", "price", "account_balance", "risk_percent", "risk_amount_usd",
            "stop_pips", "pip_size", "pip_value_per_lot_usd", "recommended_lots",
            "position_notional_usd", "max_loss_usd", "atr_based_stop",
            "suggested_take_profit_pips",
        }

    def test_max_loss_stays_near_the_risk_budget(self):
        """実際の最大損失がリスク許容額を大きく超えないこと（丸め誤差の範囲）"""
        result = calculate_position_size("USDJPY", 150.0, 10_000, 1.0, stop_pips=30)
        assert result["max_loss_usd"] <= result["risk_amount_usd"] * 1.05
