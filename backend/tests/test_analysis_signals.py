"""テクニカルシグナル抽出とバックテスト — src.analysis.signals のテスト"""

import numpy as np
import pandas as pd
import pytest

from src.analysis.signals import aggregate_bias, backtest_signals, signals_from_row


def row(**values) -> pd.Series:
    """指標値を持つ 1 行を組み立てる。指定しない指標は NaN（＝判定不能）。"""
    base = {
        "close": 100.0, "rsi": np.nan, "macd": np.nan, "macd_signal": np.nan,
        "bb_lower": np.nan, "bb_upper": np.nan, "stoch_k": np.nan, "stoch_d": np.nan,
    }
    base.update(values)
    return pd.Series(base)


def indicators_of(signals: list[dict]) -> set:
    """シグナルリストから指標名の集合を取り出す。"""
    return {s["indicator"] for s in signals}


def by_indicator(signals: list[dict], name: str) -> dict:
    """指定指標のシグナルを取り出す。"""
    return next(s for s in signals if s["indicator"] == name)


class TestRsiSignals:
    """RSI シグナルのテスト"""

    def test_oversold_is_a_buy(self):
        """RSI 30 未満は買いシグナルになること"""
        s = by_indicator(signals_from_row(row(rsi=25.0)), "RSI")
        assert s["signal"] == "buy"
        assert s["reason"] == "売られ過ぎ"
        assert s["value"] == 25.0

    def test_overbought_is_a_sell(self):
        """RSI 70 超は売りシグナルになること"""
        s = by_indicator(signals_from_row(row(rsi=75.0)), "RSI")
        assert s["signal"] == "sell"
        assert s["reason"] == "買われ過ぎ"

    @pytest.mark.parametrize("value", [30.0, 50.0, 70.0])
    def test_neutral_zone_emits_nothing(self, value):
        """境界値を含む中立域ではシグナルを出さないこと"""
        assert "RSI" not in indicators_of(signals_from_row(row(rsi=value)))

    def test_value_is_rounded(self):
        """指標値は小数 2 桁に丸めること"""
        assert by_indicator(signals_from_row(row(rsi=25.6789)), "RSI")["value"] == 25.68

    def test_missing_rsi_is_skipped(self):
        """RSI が NaN なら判定をスキップすること"""
        assert "RSI" not in indicators_of(signals_from_row(row()))


class TestMacdSignals:
    """MACD シグナルのテスト"""

    def test_macd_above_signal_is_a_buy(self):
        """MACD がシグナル線より上なら買いになること"""
        s = by_indicator(signals_from_row(row(macd=0.5, macd_signal=0.2)), "MACD")
        assert s["signal"] == "buy"

    def test_macd_below_signal_is_a_sell(self):
        """MACD がシグナル線より下なら売りになること"""
        s = by_indicator(signals_from_row(row(macd=0.1, macd_signal=0.4)), "MACD")
        assert s["signal"] == "sell"

    def test_equal_values_emit_nothing(self):
        """完全に一致する場合はシグナルを出さないこと"""
        assert "MACD" not in indicators_of(signals_from_row(row(macd=0.3, macd_signal=0.3)))

    def test_requires_both_values(self):
        """片方が欠けていれば判定しないこと"""
        assert "MACD" not in indicators_of(signals_from_row(row(macd=0.5)))
        assert "MACD" not in indicators_of(signals_from_row(row(macd_signal=0.2)))


class TestBollingerSignals:
    """ボリンジャーバンドシグナルのテスト"""

    def test_below_lower_band_is_a_buy(self):
        """下限バンド割れは買いになること"""
        s = by_indicator(
            signals_from_row(row(close=95.0, bb_lower=98.0, bb_upper=110.0)), "Bollinger Bands")
        assert s["signal"] == "buy"
        assert s["reason"] == "下限バンドタッチ"

    def test_above_upper_band_is_a_sell(self):
        """上限バンド超えは売りになること"""
        s = by_indicator(
            signals_from_row(row(close=115.0, bb_lower=98.0, bb_upper=110.0)), "Bollinger Bands")
        assert s["signal"] == "sell"

    def test_inside_the_bands_emits_nothing(self):
        """バンド内ならシグナルを出さないこと"""
        signals = signals_from_row(row(close=100.0, bb_lower=98.0, bb_upper=110.0))
        assert "Bollinger Bands" not in indicators_of(signals)

    def test_exact_touch_emits_nothing(self):
        """バンドちょうどでは（厳密な不等号のため）シグナルを出さないこと"""
        signals = signals_from_row(row(close=98.0, bb_lower=98.0, bb_upper=110.0))
        assert "Bollinger Bands" not in indicators_of(signals)


class TestStochasticSignals:
    """ストキャスティクスシグナルのテスト"""

    def test_both_below_20_is_a_buy(self):
        """%K・%D がともに 20 未満なら買いになること"""
        s = by_indicator(signals_from_row(row(stoch_k=15.0, stoch_d=18.0)), "Stochastic")
        assert s["signal"] == "buy"

    def test_both_above_80_is_a_sell(self):
        """%K・%D がともに 80 超なら売りになること"""
        s = by_indicator(signals_from_row(row(stoch_k=85.0, stoch_d=82.0)), "Stochastic")
        assert s["signal"] == "sell"

    def test_requires_agreement_between_k_and_d(self):
        """片方だけが閾値を超えてもシグナルを出さないこと（ダマシ低減）"""
        assert "Stochastic" not in indicators_of(signals_from_row(row(stoch_k=15.0, stoch_d=50.0)))
        assert "Stochastic" not in indicators_of(signals_from_row(row(stoch_k=85.0, stoch_d=50.0)))


class TestSignalsFromRow:
    """signals_from_row() 全体のテスト"""

    def test_no_indicators_yields_no_signals(self):
        """指標が揃っていなければ空リストを返すこと"""
        assert signals_from_row(row()) == []

    def test_combines_all_indicators(self):
        """複数指標が同時に条件を満たせばすべて返すこと"""
        signals = signals_from_row(row(
            close=95.0, rsi=25.0, macd=0.5, macd_signal=0.2,
            bb_lower=98.0, bb_upper=110.0, stoch_k=15.0, stoch_d=18.0,
        ))
        assert indicators_of(signals) == {"RSI", "MACD", "Bollinger Bands", "Stochastic"}
        assert all(s["signal"] == "buy" for s in signals)

    def test_every_signal_has_required_keys(self):
        """すべてのシグナルが indicator / signal / reason を持つこと"""
        signals = signals_from_row(row(rsi=25.0, macd=0.5, macd_signal=0.2))
        for s in signals:
            assert {"indicator", "signal", "reason"} <= set(s)
            assert s["signal"] in ("buy", "sell")

    def test_works_on_real_indicator_data(self, latest_row):
        """実際に計算した指標データでも例外なく動くこと"""
        for s in signals_from_row(latest_row):
            assert s["signal"] in ("buy", "sell")


class TestAggregateBias:
    """aggregate_bias() のテスト"""

    def test_empty_is_neutral(self):
        """シグナルが無ければ中立になること"""
        assert aggregate_bias([]) == "neutral"

    def test_majority_buy(self):
        """買いが多数なら buy になること"""
        signals = [{"signal": "buy"}, {"signal": "buy"}, {"signal": "sell"}]
        assert aggregate_bias(signals) == "buy"

    def test_majority_sell(self):
        """売りが多数なら sell になること"""
        signals = [{"signal": "sell"}, {"signal": "sell"}, {"signal": "buy"}]
        assert aggregate_bias(signals) == "sell"

    def test_tie_is_neutral(self):
        """同数なら中立になること（曖昧な状況で取引しない）"""
        assert aggregate_bias([{"signal": "buy"}, {"signal": "sell"}]) == "neutral"

    def test_single_signal_decides(self):
        """シグナルが 1 つならその方向になること"""
        assert aggregate_bias([{"signal": "buy"}]) == "buy"


class TestBacktestSignals:
    """backtest_signals() のテスト"""

    def flat_frame(self, n: int = 100) -> pd.DataFrame:
        """シグナルが一切出ない（全指標 NaN）フレームを作る。"""
        return pd.DataFrame({
            "close": [100.0] * n,
            "rsi": [np.nan] * n, "macd": [np.nan] * n, "macd_signal": [np.nan] * n,
            "bb_lower": [np.nan] * n, "bb_upper": [np.nan] * n,
            "stoch_k": [np.nan] * n, "stoch_d": [np.nan] * n,
        })

    def test_no_signals_returns_zeroed_summary(self):
        """シグナルが無い場合は 0 とメッセージを返すこと"""
        result = backtest_signals(self.flat_frame())
        assert result["total_trades"] == 0
        assert result["win_rate"] == 0
        assert result["message"] == "十分なシグナルがありません"

    def test_skips_the_first_50_warmup_bars(self):
        """先頭 50 本はウォームアップとして評価しないこと"""
        df = self.flat_frame(55)
        # 全バーで買いシグナルが出る状態にする
        df["macd"] = 1.0
        df["macd_signal"] = 0.0
        result = backtest_signals(df)
        # 50〜53 の 4 本のみ評価される（最終バーは翌日が無いため除外）
        assert result["total_trades"] == 4

    def test_counts_wins_for_correct_direction(self):
        """買いシグナル後に上昇したら勝ちと数えること"""
        n = 60
        df = self.flat_frame(n)
        df["macd"] = 1.0
        df["macd_signal"] = 0.0
        df["close"] = [100.0 + i for i in range(n)]  # 一貫して上昇
        result = backtest_signals(df)

        assert result["win_rate"] == 100.0
        assert result["buy_trades"] == result["total_trades"]

    def test_counts_losses_for_wrong_direction(self):
        """買いシグナル後に下落したら負けと数えること"""
        n = 60
        df = self.flat_frame(n)
        df["macd"] = 1.0
        df["macd_signal"] = 0.0
        df["close"] = [200.0 - i for i in range(n)]  # 一貫して下落
        assert backtest_signals(df)["win_rate"] == 0.0

    def test_sell_signal_wins_when_price_falls(self):
        """売りシグナル後に下落したら勝ちと数えること（空売り想定）"""
        n = 60
        df = self.flat_frame(n)
        df["macd"] = 0.0
        df["macd_signal"] = 1.0  # 売りシグナル
        df["close"] = [200.0 - i for i in range(n)]
        result = backtest_signals(df)

        assert result["win_rate"] == 100.0
        assert result["sell_trades"] == result["total_trades"]

    def test_sell_return_is_sign_flipped(self):
        """売りのリターンは符号を反転して集計すること"""
        n = 60
        df = self.flat_frame(n)
        df["macd"] = 0.0
        df["macd_signal"] = 1.0
        df["close"] = [200.0 - i for i in range(n)]
        # 下落局面の売りなので平均リターンは正になる
        assert backtest_signals(df)["avg_return_pct"] > 0

    def test_reports_period_length(self):
        """評価対象の総バー数を返すこと"""
        df = self.flat_frame(80)
        df["macd"] = 1.0
        df["macd_signal"] = 0.0
        assert backtest_signals(df)["period_bars"] == 80

    def test_short_frame_yields_no_trades(self):
        """ウォームアップに満たない長さでは取引が発生しないこと"""
        assert backtest_signals(self.flat_frame(20))["total_trades"] == 0

    def test_zero_price_bars_are_skipped(self):
        """終値 0 のバーは 0 除算を避けてスキップすること"""
        n = 60
        df = self.flat_frame(n)
        df["macd"] = 1.0
        df["macd_signal"] = 0.0
        df.loc[52, "close"] = 0.0
        # 例外を出さずに集計できること
        assert backtest_signals(df)["total_trades"] >= 0

    def test_works_on_real_indicator_data(self, indicators_df):
        """実際に計算した指標データでも整合した結果を返すこと"""
        result = backtest_signals(indicators_df)
        assert 0 <= result["win_rate"] <= 100
        if result["total_trades"]:
            assert result["buy_trades"] + result["sell_trades"] == result["total_trades"]
