"""自動売買の損益計算 — src.autotrade.pnl のテスト"""

from datetime import datetime, timedelta, timezone

import pytest

from src.analysis.position_sizing import pip_value_per_lot_usd
from src.autotrade.pnl import aggregate_pnl, calc_realized_pnl_usd, weekly_pnl_breakdown


def closed(symbol="USDJPY", side="buy", units=10_000, entry=150.0, close=151.0,
           pnl=None, closed_at=None) -> dict:
    """決済済みポジションの辞書を組み立てる。"""
    row = {"symbol": symbol, "side": side, "units": units,
           "entry_price": entry, "close_price": close}
    if pnl is not None:
        row["realized_pnl_usd"] = pnl
    if closed_at is not None:
        row["closed_at"] = closed_at
    return row


class TestCalcRealizedPnlUsd:
    """calc_realized_pnl_usd() のテスト"""

    def test_long_profit(self):
        """買いポジションで価格上昇なら利益になること

        USDJPY を 150.00 → 151.00（100 pips）、0.1 ロット。
        1 pip 価値 = 100,000 × 0.01 ÷ 151.00 ≈ 6.62 USD/ロット。
        """
        expected = 100 * pip_value_per_lot_usd("USDJPY", 151.0) * 0.1
        assert calc_realized_pnl_usd("USDJPY", "buy", 10_000, 150.0, 151.0) == pytest.approx(
            round(expected, 2))

    def test_long_loss_is_negative(self):
        """買いポジションで価格下落なら損失になること"""
        assert calc_realized_pnl_usd("USDJPY", "buy", 10_000, 151.0, 150.0) < 0

    def test_short_profit(self):
        """売りポジションで価格下落なら利益になること"""
        assert calc_realized_pnl_usd("USDJPY", "sell", 10_000, 151.0, 150.0) > 0

    def test_short_loss(self):
        """売りポジションで価格上昇なら損失になること"""
        assert calc_realized_pnl_usd("USDJPY", "sell", 10_000, 150.0, 151.0) < 0

    def test_long_and_short_are_mirror_images(self):
        """同条件の買いと売りは符号が反転するだけであること"""
        long_pnl = calc_realized_pnl_usd("USDJPY", "buy", 10_000, 150.0, 151.0)
        short_pnl = calc_realized_pnl_usd("USDJPY", "sell", 10_000, 150.0, 151.0)
        assert long_pnl == pytest.approx(-short_pnl)

    def test_flat_close_is_zero(self):
        """同値決済なら損益ゼロであること"""
        assert calc_realized_pnl_usd("USDJPY", "buy", 10_000, 150.0, 150.0) == 0.0

    def test_scales_with_units(self):
        """数量が倍なら損益もほぼ倍になること

        戻り値はセント単位に丸められるため、丸め後の値を 2 倍した数値とは
        最大 1 セントずれうる。許容誤差を持たせて比較する。
        """
        small = calc_realized_pnl_usd("USDJPY", "buy", 10_000, 150.0, 151.0)
        large = calc_realized_pnl_usd("USDJPY", "buy", 20_000, 150.0, 151.0)
        assert large == pytest.approx(small * 2, abs=0.02)

    def test_usd_quoted_pair(self):
        """ドルストレートでは 1 pip = 10 USD/ロットで計算すること"""
        # EURUSD 1.0800 → 1.0850（50 pips）、0.1 ロット → 50 × 10 × 0.1 = 50 USD
        assert calc_realized_pnl_usd("EURUSD", "buy", 10_000, 1.0800, 1.0850) == pytest.approx(50.0)

    @pytest.mark.parametrize("entry,close", [(0, 150.0), (150.0, 0), (-1, 150.0)])
    def test_invalid_prices_return_zero(self, entry, close):
        """不正な価格では 0 を返すこと（0 除算や誤集計を防ぐ）"""
        assert calc_realized_pnl_usd("USDJPY", "buy", 10_000, entry, close) == 0.0

    def test_symbol_is_case_insensitive(self):
        """小文字のシンボルでも計算できること"""
        assert calc_realized_pnl_usd("usdjpy", "buy", 10_000, 150.0, 151.0) == \
            calc_realized_pnl_usd("USDJPY", "buy", 10_000, 150.0, 151.0)

    def test_result_is_rounded_to_cents(self):
        """セント単位に丸めること"""
        value = calc_realized_pnl_usd("USDJPY", "buy", 12_345, 150.0, 150.37)
        assert value == round(value, 2)


class TestAggregatePnl:
    """aggregate_pnl() のテスト"""

    def test_empty_input(self):
        """決済履歴が無ければゼロの集計を返すこと"""
        assert aggregate_pnl([]) == {
            "total_realized_usd": 0.0, "closed_trades": 0,
            "wins": 0, "losses": 0, "win_rate_pct": 0.0,
        }

    def test_uses_precomputed_pnl(self):
        """realized_pnl_usd があればそれを使うこと（再計算しない）"""
        result = aggregate_pnl([closed(pnl=100.0), closed(pnl=-40.0)])
        assert result["total_realized_usd"] == 60.0

    def test_computes_missing_pnl(self):
        """realized_pnl_usd が無ければ価格から計算すること"""
        result = aggregate_pnl([closed(entry=150.0, close=151.0)])
        assert result["total_realized_usd"] > 0

    def test_counts_wins_and_losses(self):
        """勝ち負けを数えること"""
        result = aggregate_pnl([closed(pnl=10.0), closed(pnl=-5.0), closed(pnl=20.0)])
        assert result["wins"] == 2
        assert result["losses"] == 1
        assert result["closed_trades"] == 3

    def test_break_even_counts_as_neither(self):
        """損益ゼロの取引は勝ちにも負けにも数えないこと"""
        result = aggregate_pnl([closed(pnl=0.0), closed(pnl=10.0)])
        assert result["wins"] == 1
        assert result["losses"] == 0
        assert result["closed_trades"] == 2

    def test_win_rate_percentage(self):
        """勝率は決済件数に対する割合であること"""
        result = aggregate_pnl([closed(pnl=10.0), closed(pnl=-5.0), closed(pnl=10.0),
                                closed(pnl=-5.0)])
        assert result["win_rate_pct"] == 50.0

    def test_win_rate_includes_break_even_in_denominator(self):
        """引き分けも母数に含めること（実際の取引回数ベース）"""
        result = aggregate_pnl([closed(pnl=10.0), closed(pnl=0.0)])
        assert result["win_rate_pct"] == 50.0

    def test_total_is_rounded(self):
        """合計はセント単位に丸めること"""
        result = aggregate_pnl([closed(pnl=0.111), closed(pnl=0.222)])
        assert result["total_realized_usd"] == 0.33

    def test_mixed_symbols(self):
        """異なる通貨ペアをまとめて集計できること"""
        result = aggregate_pnl([
            closed(symbol="USDJPY", entry=150.0, close=151.0),
            closed(symbol="EURUSD", entry=1.08, close=1.085),
        ])
        assert result["closed_trades"] == 2
        assert result["total_realized_usd"] > 0


class TestWeeklyPnlBreakdown:
    """weekly_pnl_breakdown() のテスト"""

    def _iso(self, days_ago: int) -> str:
        """指定日数前の ISO 8601 文字列を返す。"""
        return (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat()

    def test_returns_requested_number_of_weeks(self):
        """指定した週数分のバケットを返すこと"""
        assert len(weekly_pnl_breakdown([], weeks=4)) == 4
        assert len(weekly_pnl_breakdown([], weeks=8)) == 8

    def test_buckets_are_newest_first(self):
        """新しい週が先頭に来ること"""
        weeks = weekly_pnl_breakdown([], weeks=4)
        starts = [w["week_start"] for w in weeks]
        assert starts == sorted(starts, reverse=True)

    def test_empty_weeks_are_zeroed(self):
        """取引が無い週はゼロで埋めること（グラフの欠損を防ぐ）"""
        for week in weekly_pnl_breakdown([], weeks=4):
            assert week == {"week_start": week["week_start"], "realized_usd": 0.0,
                            "trades": 0, "wins": 0}

    def test_assigns_trades_to_the_right_week(self):
        """決済日時に応じた週へ振り分けること"""
        weeks = weekly_pnl_breakdown([closed(pnl=50.0, closed_at=self._iso(0))], weeks=4)
        assert weeks[0]["trades"] == 1
        assert weeks[0]["realized_usd"] == 50.0
        assert sum(w["trades"] for w in weeks[1:]) == 0

    def test_counts_wins_per_week(self):
        """週ごとの勝ち数を数えること"""
        weeks = weekly_pnl_breakdown([
            closed(pnl=50.0, closed_at=self._iso(0)),
            closed(pnl=-20.0, closed_at=self._iso(0)),
        ], weeks=4)

        assert weeks[0]["trades"] == 2
        assert weeks[0]["wins"] == 1
        assert weeks[0]["realized_usd"] == 30.0

    def test_ignores_positions_without_close_time(self):
        """決済日時が無いポジションは集計対象外にすること"""
        weeks = weekly_pnl_breakdown([closed(pnl=50.0)], weeks=4)
        assert sum(w["trades"] for w in weeks) == 0

    def test_ignores_unparsable_timestamps(self):
        """日時形式が不正でも例外を投げず読み飛ばすこと"""
        weeks = weekly_pnl_breakdown([closed(pnl=50.0, closed_at="not-a-date")], weeks=4)
        assert sum(w["trades"] for w in weeks) == 0

    def test_ignores_trades_outside_the_window(self):
        """対象週より古い取引は無視すること"""
        weeks = weekly_pnl_breakdown([closed(pnl=50.0, closed_at=self._iso(120))], weeks=4)
        assert sum(w["trades"] for w in weeks) == 0

    def test_accepts_zulu_timestamps(self):
        """Z サフィックス付きの UTC 表記を解釈できること"""
        stamp = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
        weeks = weekly_pnl_breakdown([closed(pnl=10.0, closed_at=stamp)], weeks=4)
        assert sum(w["trades"] for w in weeks) == 1

    def test_accepts_naive_timestamps_as_utc(self):
        """タイムゾーン無しの日時は UTC として扱うこと"""
        stamp = datetime.now(timezone.utc).replace(tzinfo=None).isoformat()
        weeks = weekly_pnl_breakdown([closed(pnl=10.0, closed_at=stamp)], weeks=4)
        assert sum(w["trades"] for w in weeks) == 1

    def test_computes_missing_pnl(self):
        """realized_pnl_usd が無ければ価格から計算すること"""
        weeks = weekly_pnl_breakdown(
            [closed(entry=150.0, close=151.0, closed_at=self._iso(0))], weeks=4)
        assert weeks[0]["realized_usd"] > 0
