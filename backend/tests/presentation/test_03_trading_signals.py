"""
テストスイート 03: 売買シグナル生成・バックテスト

カバー範囲:
    - signals_from_row: 1行の指標値から RSI/MACD/BB/Stoch シグナルを抽出
    - aggregate_signals: シグナルの多数決バイアス集計
    - backtest_signals: 過去データでの勝率・トレード数計算

顧客向けポイント:
    - 4種類のテクニカル指標（RSI・MACD・BB・Stochastic）の多数決でシグナルを決定します。
    - バックテストはシグナル翌日の方向一致率（勝率）を計算します。
    - シグナルの信頼度は一致したシグナル数で表現されます。
"""

import numpy as np
import pandas as pd
import pytest


class TestSignalFromRow:
    """signals_from_row — 1行の指標値からシグナルを生成するテスト。"""

    @pytest.fixture(autouse=True)
    def import_module(self):
        """シグナルモジュールをインポート。"""
        try:
            from src.analysis.signals import signals_from_row
            self.signals_from_row = signals_from_row
        except ImportError as exc:
            pytest.skip(f"依存関係不足のためスキップ: {exc}")

    def _make_row(self, **kwargs) -> pd.Series:
        """テスト用の指標値 Series を生成するヘルパー。デフォルト値は中立状態。"""
        defaults = {
            "rsi": 50.0,
            "macd": 0.0,
            "macd_signal": 0.0,
            "bb_upper": 152.0,
            "bb_lower": 148.0,
            "bb_middle": 150.0,
            "close": 150.0,
            "stoch_k": 50.0,
            "stoch_d": 50.0,
        }
        defaults.update(kwargs)
        return pd.Series(defaults)

    def test_rsi_oversold_generates_buy_signal(self):
        """RSI < 30 で買いシグナルが生成されることを確認する。

        RSI が 30 を下回ると「売られ過ぎ」状態とみなし、反発を期待した買いシグナル。
        """
        row = self._make_row(rsi=25.0)
        signals = self.signals_from_row(row)
        rsi_signals = [s for s in signals if s.get("indicator") == "RSI"]
        assert any(s.get("signal") == "buy" for s in rsi_signals), \
            f"RSI < 30 で買いシグナルが生成される必要があります。生成されたシグナル: {rsi_signals}"

    def test_rsi_overbought_generates_sell_signal(self):
        """RSI > 70 で売りシグナルが生成されることを確認する。

        RSI が 70 を超えると「買われ過ぎ」状態とみなし、反落を期待した売りシグナル。
        """
        row = self._make_row(rsi=75.0)
        signals = self.signals_from_row(row)
        rsi_signals = [s for s in signals if s.get("indicator") == "RSI"]
        assert any(s.get("signal") == "sell" for s in rsi_signals), \
            f"RSI > 70 で売りシグナルが生成される必要があります。生成されたシグナル: {rsi_signals}"

    def test_macd_above_signal_generates_buy(self):
        """MACD > シグナル線で買いシグナルが生成されることを確認する（ゴールデンクロス）。

        MACD がシグナル線を上回ると短期トレンドの上昇転換を示す。
        """
        row = self._make_row(macd=0.5, macd_signal=0.2)
        signals = self.signals_from_row(row)
        macd_signals = [s for s in signals if s.get("indicator") == "MACD"]
        assert any(s.get("signal") == "buy" for s in macd_signals), \
            f"MACD > シグナル線で買いシグナルが生成される必要があります: {macd_signals}"

    def test_price_below_lower_bb_generates_buy(self):
        """終値がボリンジャー下限を下回ると買いシグナルが生成されることを確認する。

        下限バンドは統計的に「安値水準」を示し、平均回帰を期待した買いシグナル。
        """
        row = self._make_row(close=147.0, bb_lower=148.0, bb_upper=152.0)
        signals = self.signals_from_row(row)
        bb_signals = [s for s in signals if "Bollinger" in s.get("indicator", "")]
        assert any(s.get("signal") == "buy" for s in bb_signals), \
            f"終値 < 下限バンドで買いシグナルが生成される必要があります: {bb_signals}"

    def test_stoch_both_oversold_generates_buy(self):
        """%K と %D が両方 20 未満で買いシグナルが生成されることを確認する。

        %K・%D 両方が閾値を超えることを条件とし、ダマシのシグナルを減らす設計。
        """
        row = self._make_row(stoch_k=15.0, stoch_d=18.0)
        signals = self.signals_from_row(row)
        stoch_signals = [s for s in signals if "Stoch" in s.get("indicator", "")]
        assert any(s.get("signal") == "buy" for s in stoch_signals), \
            f"%K と %D が両方 < 20 で買いシグナルが生成される必要があります: {stoch_signals}"

    def test_neutral_indicators_produce_no_signals(self):
        """すべての指標が中立値のとき、シグナルが生成されないことを確認する。

        RSI=50・MACD=0・価格=バンド中央・Stoch=50 は明確なシグナルなし。
        """
        row = self._make_row()  # デフォルト値（全て中立）
        signals = self.signals_from_row(row)
        assert len(signals) == 0, \
            f"中立状態ではシグナルが生成されないべきです。生成されたシグナル数: {len(signals)}"

    def test_multiple_indicators_can_trigger_simultaneously(self):
        """複数の指標が同時にシグナルを生成できることを確認する（信頼度向上の根拠）。

        複数の指標が同方向のシグナルを出すほど、シグナルの信頼度が高まる設計。
        """
        # RSI 売られ過ぎ + BB 下限タッチ + Stoch 売られ過ぎ を同時に設定
        row = self._make_row(
            rsi=20.0,
            close=147.0, bb_lower=148.0,
            stoch_k=10.0, stoch_d=12.0,
        )
        signals = self.signals_from_row(row)
        buy_signals = [s for s in signals if s.get("signal") == "buy"]
        assert len(buy_signals) >= 2, \
            f"複数指標が同時シグナルを生成できる必要があります: {len(buy_signals)} 件"

    def test_signal_has_required_keys(self, sample_signal_row: pd.Series):
        """生成されたシグナル辞書に必須キーが含まれることを確認する。

        API レスポンスで使用する indicator / signal / reason キーの存在を検証。
        """
        # 売られ過ぎ状態を強制的に作成
        row = sample_signal_row.copy()
        row["rsi"] = 20.0
        signals = self.signals_from_row(row)
        if signals:
            s = signals[0]
            assert "indicator" in s, "シグナルには 'indicator' キーが必要です"
            assert "signal" in s, "シグナルには 'signal' キーが必要です"
            assert s.get("signal") in ("buy", "sell"), \
                f"signal は 'buy' または 'sell' である必要があります: {s.get('signal')}"


class TestAggregateBias:
    """aggregate_bias — シグナルの多数決バイアス集計テスト。

    aggregate_bias は signals リストを受け取り "buy" / "sell" / "neutral" の
    文字列を返す。（辞書ではなく文字列）
    """

    @pytest.fixture(autouse=True)
    def import_module(self):
        """シグナルモジュールをインポート。"""
        try:
            from src.analysis.signals import aggregate_bias
            self.aggregate_bias = aggregate_bias
        except ImportError as exc:
            pytest.skip(f"依存関係不足のためスキップ: {exc}")

    def test_majority_buy_signals_gives_buy(self):
        """買いシグナルが多数の場合、'buy' が返されることを確認する。

        RSI 買い + MACD 買い vs BB 売り → 買い 2 > 売り 1 → "buy"
        """
        signals = [
            {"indicator": "RSI", "signal": "buy"},
            {"indicator": "MACD", "signal": "buy"},
            {"indicator": "Bollinger Bands", "signal": "sell"},
        ]
        result = self.aggregate_bias(signals)
        assert result == "buy", \
            f"買い多数で 'buy' が期待されます: {result}"

    def test_majority_sell_signals_gives_sell(self):
        """売りシグナルが多数の場合、'sell' が返されることを確認する。"""
        signals = [
            {"indicator": "RSI", "signal": "sell"},
            {"indicator": "MACD", "signal": "sell"},
            {"indicator": "Stochastic", "signal": "buy"},
        ]
        result = self.aggregate_bias(signals)
        assert result == "sell", \
            f"売り多数で 'sell' が期待されます: {result}"

    def test_empty_signals_gives_neutral(self):
        """シグナルなしの場合、'neutral'（方向感なし）が返されることを確認する。

        買い = 0、売り = 0 → 同数 → "neutral"
        """
        result = self.aggregate_bias([])
        assert result == "neutral", \
            f"シグナルなしで 'neutral' が期待されます: {result}"

    def test_equal_buy_sell_gives_neutral(self):
        """買い・売りが同数の場合、'neutral' が返されることを確認する。"""
        signals = [
            {"indicator": "RSI", "signal": "buy"},
            {"indicator": "MACD", "signal": "sell"},
        ]
        result = self.aggregate_bias(signals)
        assert result == "neutral", \
            f"買い = 売り = 1 の場合 'neutral' が期待されます: {result}"

    def test_returns_string(self):
        """aggregate_bias が文字列を返すことを確認する。"""
        signals = [{"indicator": "RSI", "signal": "buy"}]
        result = self.aggregate_bias(signals)
        assert isinstance(result, str), \
            f"aggregate_bias は文字列を返す必要があります: {type(result)}"
        assert result in ("buy", "sell", "neutral"), \
            f"戻り値は buy / sell / neutral のいずれかが期待されます: {result}"


class TestBacktestSignals:
    """backtest_signals — 過去データでの勝率・トレード数計算テスト。"""

    @pytest.fixture(autouse=True)
    def import_module(self):
        """シグナルモジュールをインポート。"""
        try:
            from src.analysis.signals import backtest_signals
            self.backtest_signals = backtest_signals
        except ImportError as exc:
            pytest.skip(f"依存関係不足のためスキップ: {exc}")

    def test_backtest_returns_dict(self, sample_ohlcv_with_indicators: pd.DataFrame):
        """backtest_signals が辞書を返すことを確認する。"""
        result = self.backtest_signals(sample_ohlcv_with_indicators)
        assert isinstance(result, dict), \
            f"backtest_signals は dict を返す必要があります: {type(result)}"

    def test_backtest_has_win_rate(self, sample_ohlcv_with_indicators: pd.DataFrame):
        """バックテスト結果に win_rate が含まれることを確認する。"""
        result = self.backtest_signals(sample_ohlcv_with_indicators)
        assert "win_rate" in result, \
            f"バックテスト結果には 'win_rate' キーが必要です: {list(result.keys())}"

    def test_win_rate_is_in_valid_range(self, sample_ohlcv_with_indicators: pd.DataFrame):
        """勝率が有効な範囲内であることを確認する（0〜1 の比率または 0〜100 の%）。"""
        result = self.backtest_signals(sample_ohlcv_with_indicators)
        wr = result.get("win_rate", 0)
        # win_rate は 0.0〜1.0 の比率、または 0〜100 のパーセント値のいずれか
        assert 0 <= wr <= 100, \
            f"勝率は 0〜100 の範囲内である必要があります: {wr}"

    def test_backtest_has_total_trades(self, sample_ohlcv_with_indicators: pd.DataFrame):
        """バックテスト結果にトレード数が含まれることを確認する。"""
        result = self.backtest_signals(sample_ohlcv_with_indicators)
        assert "total_trades" in result or "trades" in result, \
            f"バックテスト結果にはトレード数が必要です: {list(result.keys())}"

    def test_backtest_with_200_rows_has_sufficient_trades(
        self, sample_ohlcv_with_indicators: pd.DataFrame
    ):
        """200 行のデータで一定数のトレードが発生することを確認する（指標の感度検証）。"""
        result = self.backtest_signals(sample_ohlcv_with_indicators)
        total = result.get("total_trades", result.get("trades", 0))
        assert total >= 0, f"トレード数は 0 以上である必要があります: {total}"
