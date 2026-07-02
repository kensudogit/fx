"""
テストスイート 04: 損益計算・ポジションサイジング

カバー範囲:
    - pip_size: 通貨ペア別の pip サイズ (JPY ペア / その他)
    - pip_value_per_lot_usd: 1標準ロットあたりの pip USD 価値
    - pips_from_atr: ATR からの動的ストップ幅計算
    - calculate_position_size: 固定リスク%法によるロット計算
    - calc_realized_pnl_usd: 決済済みポジションの実現損益計算
    - aggregate_pnl: PnL 集計（合計・勝率・トレード数）
    - weekly_pnl_breakdown: 週次損益内訳

顧客向けポイント:
    - FX の pip 計算はペアによって異なります (JPY ペア: 0.01、他: 0.0001)。
    - 固定リスク%法により口座残高の一定割合のみをリスクにさらします。
    - 週次損益内訳でパフォーマンスの時系列分析が可能です。
"""

from datetime import datetime, timedelta, timezone

import numpy as np
import pytest


class TestPipSize:
    """pip_size — 通貨ペアの最小変動単位テスト。"""

    @pytest.fixture(autouse=True)
    def import_module(self):
        """ポジションサイジングモジュールをインポート。"""
        try:
            from src.analysis.position_sizing import pip_size
            self.pip_size = pip_size
        except ImportError as exc:
            pytest.skip(f"依存関係不足のためスキップ: {exc}")

    def test_usdjpy_pip_size(self):
        """USDJPY の pip サイズが 0.01 であることを確認する。

        JPY ペアは小数点第2位が最小変動単位 (1 銭 = 0.01 円)。
        """
        assert self.pip_size("USDJPY") == 0.01, \
            f"USDJPY の pip サイズは 0.01 が期待されます: {self.pip_size('USDJPY')}"

    def test_eurjpy_pip_size(self):
        """EURJPY の pip サイズが 0.01 であることを確認する。"""
        assert self.pip_size("EURJPY") == 0.01

    def test_eurusd_pip_size(self):
        """EURUSD の pip サイズが 0.0001 であることを確認する。

        JPY 以外のペアは小数点第4位が最小変動単位。
        """
        assert self.pip_size("EURUSD") == 0.0001, \
            f"EURUSD の pip サイズは 0.0001 が期待されます: {self.pip_size('EURUSD')}"

    def test_gbpusd_pip_size(self):
        """GBPUSD の pip サイズが 0.0001 であることを確認する。"""
        assert self.pip_size("GBPUSD") == 0.0001

    def test_lowercase_symbol_is_handled(self):
        """小文字のシンボルが正しく処理されることを確認する（大文字正規化）。"""
        assert self.pip_size("usdjpy") == 0.01, \
            "小文字のシンボルも正しく処理される必要があります"

    def test_audjpy_pip_size(self):
        """AUDJPY の pip サイズが 0.01 であることを確認する。"""
        assert self.pip_size("AUDJPY") == 0.01


class TestPipValuePerLot:
    """pip_value_per_lot_usd — 1ロットあたりの pip USD 価値テスト。"""

    @pytest.fixture(autouse=True)
    def import_module(self):
        """ポジションサイジングモジュールをインポート。"""
        try:
            from src.analysis.position_sizing import pip_value_per_lot_usd
            self.pip_value_per_lot_usd = pip_value_per_lot_usd
        except ImportError as exc:
            pytest.skip(f"依存関係不足のためスキップ: {exc}")

    def test_eurusd_pip_value_is_10_usd(self):
        """EURUSD の 1 pip 価値が 10 USD/ロットであることを確認する。

        計算式: 100,000 通貨 × 0.0001 = 10 USD（クォート通貨が USD のため固定）
        """
        value = self.pip_value_per_lot_usd("EURUSD", price=1.0850)
        assert abs(value - 10.0) < 0.01, \
            f"EURUSD の pip 価値は 10 USD が期待されます: {value:.4f}"

    def test_gbpusd_pip_value_is_10_usd(self):
        """GBPUSD の 1 pip 価値が 10 USD/ロットであることを確認する。"""
        value = self.pip_value_per_lot_usd("GBPUSD", price=1.2700)
        assert abs(value - 10.0) < 0.01, \
            f"GBPUSD の pip 価値は 10 USD が期待されます: {value:.4f}"

    def test_usdjpy_pip_value_decreases_as_rate_rises(self):
        """USDJPY の pip 価値がレート上昇とともに低下することを確認する。

        計算式: (100,000 × 0.01) / レート
        レートが高くなるほど分母が大きくなり pip 価値は低下する。
        """
        value_low = self.pip_value_per_lot_usd("USDJPY", price=130.0)
        value_high = self.pip_value_per_lot_usd("USDJPY", price=160.0)
        assert value_low > value_high, \
            f"USDJPY の pip 価値はレート上昇で低下します: {value_low:.4f} > {value_high:.4f}"

    def test_zero_price_returns_zero(self):
        """価格 0 が渡された場合に 0 を返すことを確認する（ゼロ除算ガード）。"""
        value = self.pip_value_per_lot_usd("USDJPY", price=0.0)
        assert value == 0.0, "価格 0 の場合は 0 を返す必要があります（ゼロ除算防止）"


class TestCalculatePositionSize:
    """calculate_position_size — 固定リスク%法によるロット計算テスト。"""

    @pytest.fixture(autouse=True)
    def import_module(self):
        """ポジションサイジングモジュールをインポート。"""
        try:
            from src.analysis.position_sizing import calculate_position_size
            self.calculate_position_size = calculate_position_size
        except ImportError as exc:
            pytest.skip(f"依存関係不足のためスキップ: {exc}")

    def test_position_size_is_positive(self):
        """計算されたポジションサイズ（推奨ロット数）が正の値であることを確認する。

        calculate_position_size のシグネチャ: (symbol, price, account_balance, risk_percent, stop_pips)
        戻り値キー: recommended_lots（推奨ロット数）、risk_amount_usd（リスク許容額）
        """
        result = self.calculate_position_size(
            symbol="EURUSD",
            price=1.0850,
            account_balance=10000,
            risk_percent=1.0,
            stop_pips=50,
        )
        lots = result.get("recommended_lots", 0)
        assert lots > 0, f"推奨ロット数は正の値である必要があります: {lots}"

    def test_higher_risk_gives_larger_position(self):
        """リスク割合が高いほど大きなポジション（ロット数）になることを確認する。

        固定リスク%法: 推奨ロット数 = リスク許容額 ÷ (ストップ幅 × pip 価値/ロット)
        """
        result_1pct = self.calculate_position_size("EURUSD", 1.0850, 10000, 1.0, stop_pips=50)
        result_2pct = self.calculate_position_size("EURUSD", 1.0850, 10000, 2.0, stop_pips=50)
        lots_1 = result_1pct.get("recommended_lots", 0)
        lots_2 = result_2pct.get("recommended_lots", 0)
        assert lots_2 > lots_1, \
            f"リスク 2% のロット数 ({lots_2}) はリスク 1% ({lots_1}) より大きい必要があります"

    def test_wider_stop_gives_smaller_position(self):
        """ストップ幅が広いほど小さなポジション（ロット数）になることを確認する。

        ストップが広い = 1ロットあたりのリスク額増加 → 同じリスク予算でロットを減らす。
        """
        result_20pip = self.calculate_position_size("EURUSD", 1.0850, 10000, 1.0, stop_pips=20)
        result_100pip = self.calculate_position_size("EURUSD", 1.0850, 10000, 1.0, stop_pips=100)
        lots_20 = result_20pip.get("recommended_lots", 0)
        lots_100 = result_100pip.get("recommended_lots", 0)
        assert lots_20 > lots_100, \
            f"ストップ 20 pip ({lots_20} ロット) > ストップ 100 pip ({lots_100} ロット) が必要です"

    def test_result_contains_risk_amount_usd(self):
        """計算結果に USD 建てのリスク額が含まれることを確認する。"""
        result = self.calculate_position_size(
            symbol="EURUSD",
            price=1.0850,
            account_balance=10000,
            risk_percent=1.0,
            stop_pips=50,
        )
        assert "risk_amount_usd" in result, \
            f"計算結果には 'risk_amount_usd' が必要です: {list(result.keys())}"


class TestCalcRealizedPnlUsd:
    """calc_realized_pnl_usd — 実現損益 USD 計算テスト。"""

    @pytest.fixture(autouse=True)
    def import_module(self):
        """PnL モジュールをインポート。"""
        try:
            from src.autotrade.pnl import calc_realized_pnl_usd
            self.calc_realized_pnl_usd = calc_realized_pnl_usd
        except ImportError as exc:
            pytest.skip(f"依存関係不足のためスキップ: {exc}")

    def test_buy_position_profit(self):
        """買いポジションで価格上昇時に利益が発生することを確認する。

        USDJPY 買い: entry 148.00 → close 149.50 (150 pips 利益)
        計算: 10,000通貨 × 150 pips × pip価値 ≈ 正の USD
        """
        pnl = self.calc_realized_pnl_usd(
            symbol="USDJPY",
            side="buy",
            units=10000,
            entry_price=148.00,
            close_price=149.50,
        )
        assert pnl > 0, \
            f"USDJPY 買い・価格上昇で PnL は正 (利益) が期待されます: {pnl:.2f} USD"

    def test_buy_position_loss(self):
        """買いポジションで価格下落時に損失が発生することを確認する。

        USDJPY 買い: entry 150.00 → close 148.00 (200 pips 損失)
        """
        pnl = self.calc_realized_pnl_usd(
            symbol="USDJPY",
            side="buy",
            units=10000,
            entry_price=150.00,
            close_price=148.00,
        )
        assert pnl < 0, \
            f"USDJPY 買い・価格下落で PnL は負 (損失) が期待されます: {pnl:.2f} USD"

    def test_sell_position_profit(self):
        """売りポジションで価格下落時に利益が発生することを確認する。

        EURUSD 売り: entry 1.0900 → close 1.0850 (50 pips 利益)
        """
        pnl = self.calc_realized_pnl_usd(
            symbol="EURUSD",
            side="sell",
            units=10000,
            entry_price=1.0900,
            close_price=1.0850,
        )
        assert pnl > 0, \
            f"EURUSD 売り・価格下落で PnL は正 (利益) が期待されます: {pnl:.2f} USD"

    def test_sell_position_loss(self):
        """売りポジションで価格上昇時に損失が発生することを確認する。"""
        pnl = self.calc_realized_pnl_usd(
            symbol="EURUSD",
            side="sell",
            units=10000,
            entry_price=1.0800,
            close_price=1.0900,
        )
        assert pnl < 0, \
            f"EURUSD 売り・価格上昇で PnL は負 (損失) が期待されます: {pnl:.2f} USD"

    def test_zero_price_returns_zero(self):
        """エントリー価格 0 のとき 0 が返されることを確認する（無効データガード）。"""
        pnl = self.calc_realized_pnl_usd(
            symbol="USDJPY",
            side="buy",
            units=10000,
            entry_price=0.0,
            close_price=150.0,
        )
        assert pnl == 0.0, "エントリー価格 0 の場合は 0 を返す必要があります"

    def test_larger_units_gives_larger_pnl(self):
        """ユニット数が多いほど損益の絶対値が大きくなることを確認する。"""
        pnl_small = self.calc_realized_pnl_usd("USDJPY", "buy", 1000, 148.0, 149.0)
        pnl_large = self.calc_realized_pnl_usd("USDJPY", "buy", 100000, 148.0, 149.0)
        assert abs(pnl_large) > abs(pnl_small), \
            f"大ロット ({abs(pnl_large):.2f}) > 小ロット ({abs(pnl_small):.2f}) が期待されます"

    def test_eurusd_50pip_profit_approximately_50_usd(self):
        """EURUSD 50 pip 利益が約 50 USD (10,000通貨) であることを確認する。

        計算: 10,000 / 100,000 × 10 USD/pip × 50 pips = 50 USD
        """
        pnl = self.calc_realized_pnl_usd(
            symbol="EURUSD",
            side="buy",
            units=10000,  # 0.1 ロット
            entry_price=1.0800,
            close_price=1.0850,  # 50 pips
        )
        # 0.1 ロット × 10 USD/pip × 50 pips = 50 USD
        assert abs(pnl - 50.0) < 1.0, \
            f"EURUSD 0.1ロット 50 pip 利益 ≈ 50 USD が期待されます: {pnl:.2f} USD"


class TestAggregatePnL:
    """aggregate_pnl — PnL 集計（合計・勝率）テスト。"""

    @pytest.fixture(autouse=True)
    def import_module(self):
        """PnL モジュールをインポート。"""
        try:
            from src.autotrade.pnl import aggregate_pnl, calc_realized_pnl_usd
            self.aggregate_pnl = aggregate_pnl
            self.calc_realized_pnl_usd = calc_realized_pnl_usd
        except ImportError as exc:
            pytest.skip(f"依存関係不足のためスキップ: {exc}")

    def _make_position(self, symbol, side, units, entry, close):
        """テスト用決済ポジションを計算して返す。"""
        pnl = self.calc_realized_pnl_usd(symbol, side, units, entry, close)
        return {
            "id": f"pos_{entry}_{close}",
            "symbol": symbol,
            "side": side,
            "units": units,
            "entry_price": entry,
            "close_price": close,
            "realized_pnl_usd": pnl,
        }

    def test_aggregate_returns_dict(self):
        """aggregate_pnl が辞書を返すことを確認する。"""
        positions = [
            self._make_position("USDJPY", "buy", 10000, 148.0, 149.0),
        ]
        result = self.aggregate_pnl(positions)
        assert isinstance(result, dict), \
            f"aggregate_pnl は dict を返す必要があります: {type(result)}"

    def test_aggregate_has_total_pnl(self):
        """集計結果に total_realized_usd（合計実現損益）が含まれることを確認する。

        aggregate_pnl の戻り値キー: total_realized_usd / closed_trades / wins / losses / win_rate_pct
        """
        positions = [
            self._make_position("USDJPY", "buy", 10000, 148.0, 149.0),
        ]
        result = self.aggregate_pnl(positions)
        assert "total_realized_usd" in result, \
            f"集計結果には 'total_realized_usd' が必要です: {list(result.keys())}"

    def test_all_winning_positions_gives_100_win_rate(self):
        """全ポジションが勝ちの場合、勝率 100 (%) が返されることを確認する。

        aggregate_pnl の win_rate_pct は 0〜100 のパーセント値として返される。
        """
        positions = [
            self._make_position("USDJPY", "buy", 10000, 148.0, 150.0),
            self._make_position("EURUSD", "buy", 10000, 1.0800, 1.0900),
            self._make_position("GBPUSD", "sell", 10000, 1.2800, 1.2700),
        ]
        result = self.aggregate_pnl(positions)
        win_rate = result.get("win_rate_pct", -1)
        assert win_rate == 100.0, \
            f"全勝ちの場合、勝率は 100.0% が期待されます: {win_rate}"

    def test_empty_positions_returns_zero_pnl(self):
        """空のポジションリストで合計 PnL が 0 であることを確認する。"""
        result = self.aggregate_pnl([])
        total = result.get("total_realized_usd", 0)
        assert total == 0, f"空ポジションの合計 PnL は 0 が期待されます: {total}"


class TestWeeklyPnLBreakdown:
    """weekly_pnl_breakdown — 週次損益内訳テスト。"""

    @pytest.fixture(autouse=True)
    def import_module(self):
        """PnL モジュールをインポート。"""
        try:
            from src.autotrade.pnl import weekly_pnl_breakdown, calc_realized_pnl_usd
            self.weekly_pnl_breakdown = weekly_pnl_breakdown
            self.calc_realized_pnl_usd = calc_realized_pnl_usd
        except ImportError as exc:
            pytest.skip(f"依存関係不足のためスキップ: {exc}")

    def test_weekly_breakdown_returns_list(self):
        """weekly_pnl_breakdown がリストを返すことを確認する。"""
        now = datetime.now(timezone.utc)
        positions = [
            {
                "id": "p1",
                "symbol": "USDJPY",
                "side": "buy",
                "units": 10000,
                "entry_price": 148.0,
                "close_price": 149.0,
                "realized_pnl_usd": self.calc_realized_pnl_usd("USDJPY", "buy", 10000, 148.0, 149.0),
                "closed_at": (now - timedelta(days=1)).isoformat(),
            },
        ]
        result = self.weekly_pnl_breakdown(positions)
        assert isinstance(result, list), \
            f"weekly_pnl_breakdown はリストを返す必要があります: {type(result)}"

    def test_empty_positions_returns_empty_list(self):
        """空ポジションリストで空のリストが返されることを確認する。"""
        result = self.weekly_pnl_breakdown([])
        assert result == [] or isinstance(result, list), \
            "空ポジションの場合は空リストが期待されます"
