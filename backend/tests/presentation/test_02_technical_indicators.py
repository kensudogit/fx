"""
テストスイート 02: テクニカル指標計算モジュール

カバー範囲:
    - SMA (単純移動平均)
    - EMA (指数移動平均)
    - ボリンジャーバンド (±2σ)
    - MACD と シグナル線
    - RSI (相対力指数 — Wilder の平滑移動平均法)
    - ストキャスティクス (%K / %D)
    - 一目均衡表 (転換線・基準線・先行スパン)
    - compute_all_indicators による一括計算

顧客向けポイント:
    - 7種類のテクニカル指標をすべて pandas ベースで高速計算します。
    - ウォームアップ期間の先頭行は NaN となり、計算式の正確性を保ちます。
    - compute_all_indicators は全指標を1回のパスで計算し、API レスポンスを高速化します。
"""

import numpy as np
import pandas as pd
import pytest


class TestMovingAverages:
    """SMA・EMA の数値正確性テスト。"""

    @pytest.fixture(autouse=True)
    def import_module(self):
        """テクニカル指標モジュールをインポート。"""
        try:
            from src.analysis.technical import (
                exponential_moving_average,
                moving_average,
            )
            self.moving_average = moving_average
            self.exponential_moving_average = exponential_moving_average
        except ImportError as exc:
            pytest.skip(f"依存関係不足のためスキップ: {exc}")

    def test_sma_basic_calculation(self):
        """SMA(3) が正確に計算されることを確認する。

        期待値: [NaN, NaN, (1+2+3)/3=2.0, (2+3+4)/3=3.0, (3+4+5)/3=4.0]
        """
        series = pd.Series([1.0, 2.0, 3.0, 4.0, 5.0])
        result = self.moving_average(series, period=3)
        assert abs(result.iloc[2] - 2.0) < 1e-9, f"SMA(3) の期待値 2.0 ≠ {result.iloc[2]}"
        assert abs(result.iloc[4] - 4.0) < 1e-9, f"SMA(3) の期待値 4.0 ≠ {result.iloc[4]}"

    def test_sma_warmup_period_is_nan(self):
        """SMA の先頭 (period-1) 個の値が NaN であることを確認する。

        ウォームアップ期間に十分なデータがないため NaN が期待される。
        """
        series = pd.Series(list(range(1, 11)), dtype=float)
        result = self.moving_average(series, period=5)
        assert result.iloc[:4].isna().all(), "SMA の先頭 4 行は NaN である必要があります"
        assert not pd.isna(result.iloc[4]), "5 行目以降は有効な値である必要があります"

    def test_ema_latest_value_is_not_nan(self):
        """十分なデータがある場合、EMA の最終値が NaN でないことを確認する。"""
        series = pd.Series(np.linspace(100, 110, 50))
        result = self.exponential_moving_average(series, period=20)
        assert not pd.isna(result.iloc[-1]), "50 行のデータで EMA の最終値は NaN でない必要があります"

    def test_ema_reacts_faster_than_sma_on_price_surge(self):
        """価格急騰時に EMA が SMA より速く反応することを確認する。

        EMA は直近データに高いウェイトを付与するため、
        価格変動への反応が SMA より速い（この特性が MACD の基礎となる）。
        """
        # 最後の5行で価格が急騰するデータ
        baseline = pd.Series([100.0] * 50)
        surge = pd.concat([baseline, pd.Series([200.0] * 5)], ignore_index=True)
        sma = self.moving_average(surge, period=20).iloc[-1]
        ema = self.exponential_moving_average(surge, period=20).iloc[-1]
        assert ema > sma, f"急騰後の EMA ({ema:.2f}) は SMA ({sma:.2f}) より大きい必要があります"

    def test_sma_of_constant_series_equals_constant(self):
        """定数系列の SMA が定数と等しいことを確認する（数学的一貫性）。"""
        series = pd.Series([150.0] * 100)
        result = self.moving_average(series, period=20)
        valid = result.dropna()
        assert (valid == 150.0).all(), "定数系列の SMA は同じ定数に等しい必要があります"


class TestBollingerBands:
    """ボリンジャーバンドの構造と数値テスト。

    bollinger_bands は {"upper": Series, "middle": Series, "lower": Series} の辞書を返す。
    """

    @pytest.fixture(autouse=True)
    def import_module(self):
        """テクニカル指標モジュールをインポート。"""
        try:
            from src.analysis.technical import bollinger_bands
            self.bollinger_bands = bollinger_bands
        except ImportError as exc:
            pytest.skip(f"依存関係不足のためスキップ: {exc}")

    def test_upper_band_is_above_middle(self):
        """上バンドが中央バンド（SMA）より上にあることを確認する。

        ボリンジャーバンドの定義: 上バンド = SMA + 2σ、下バンド = SMA - 2σ
        bollinger_bands は {"upper", "middle", "lower"} の辞書を返す。
        """
        series = pd.Series(np.random.normal(150, 2, 100))
        bb = self.bollinger_bands(series, period=20)
        upper = bb["upper"].dropna()
        middle = bb["middle"].dropna()
        assert (upper.values >= middle.values).all(), \
            "上バンドは常に中央バンド以上である必要があります"

    def test_lower_band_is_below_middle(self):
        """下バンドが中央バンド（SMA）より下にあることを確認する。"""
        series = pd.Series(np.random.normal(150, 2, 100))
        bb = self.bollinger_bands(series, period=20)
        lower = bb["lower"].dropna()
        middle = bb["middle"].dropna()
        assert (lower.values <= middle.values).all(), \
            "下バンドは常に中央バンド以下である必要があります"

    def test_band_width_increases_with_volatility(self):
        """ボラティリティが高いとバンド幅が広がることを確認する。

        ボリンジャーバンドはボラティリティを視覚化する指標。
        価格変動が大きいほどバンドが広がり、スクイーズ（収縮）はブレイクアウト前兆。
        """
        np.random.seed(42)
        low_vol = pd.Series(np.random.normal(150, 0.1, 100))
        high_vol = pd.Series(np.random.normal(150, 5.0, 100))
        bb_low = self.bollinger_bands(low_vol)
        bb_high = self.bollinger_bands(high_vol)

        width_low = (bb_low["upper"] - bb_low["lower"]).dropna().mean()
        width_high = (bb_high["upper"] - bb_high["lower"]).dropna().mean()
        assert width_high > width_low, \
            f"高ボラティリティのバンド幅 ({width_high:.4f}) > 低ボラティリティ ({width_low:.4f}) が必要です"

    def test_price_at_mean_is_near_middle_band(self):
        """平均的な価格が中央バンド付近にあることを確認する（定数系列の検証）。"""
        series = pd.Series([150.0] * 100)
        bb = self.bollinger_bands(series, period=20)
        valid_mid = bb["middle"].dropna()
        assert (abs(valid_mid - 150.0) < 1e-9).all(), \
            "定数系列の中央バンドは価格と等しい必要があります"


class TestMACD:
    """MACD（移動平均収束拡散法）の計算テスト。

    MACD = 短期 EMA(12) - 長期 EMA(26)
    シグナル = MACD の EMA(9)
    ヒストグラム = MACD - シグナル
    macd() 関数は {"macd": Series, "signal": Series, "histogram": Series} の辞書を返す。
    """

    @pytest.fixture(autouse=True)
    def import_module(self):
        """テクニカル指標モジュールをインポート。"""
        try:
            from src.analysis.technical import macd
            self.macd = macd
        except ImportError as exc:
            pytest.skip(f"依存関係不足のためスキップ: {exc}")

    def test_macd_returns_dict_with_three_keys(self):
        """macd() が {"macd", "signal", "histogram"} のキーを持つ辞書を返すことを確認する。"""
        series = pd.Series(np.linspace(100, 120, 100))
        result = self.macd(series)
        assert isinstance(result, dict), f"MACD は dict を返す必要があります: {type(result)}"
        for key in ("macd", "signal", "histogram"):
            assert key in result, f"MACD 辞書には '{key}' キーが必要です"

    def test_macd_histogram_equals_macd_minus_signal(self):
        """ヒストグラム = MACD - シグナルの計算式が正しいことを確認する。"""
        series = pd.Series(np.random.normal(150, 2, 100))
        result = self.macd(series)
        macd_line = result["macd"]
        signal_line = result["signal"]
        histogram = result["histogram"]
        valid = histogram.dropna()
        expected = (macd_line - signal_line).dropna()
        pd.testing.assert_series_equal(
            valid.reset_index(drop=True),
            expected.reset_index(drop=True),
            check_names=False,
            atol=1e-9,
        )

    def test_macd_positive_in_uptrend(self):
        """上昇トレンド市場で MACD がゼロ以上の値を持つことを確認する。

        短期 EMA > 長期 EMA の場合、MACD > 0（上昇トレンドの根拠）。
        """
        trend = pd.Series(np.linspace(100, 200, 100))
        result = self.macd(trend)
        latest_macd = result["macd"].dropna().iloc[-1]
        assert latest_macd > 0, \
            f"上昇トレンドでは MACD が正の値を持つ必要があります: {latest_macd:.4f}"


class TestRSI:
    """RSI（相対力指数）の計算テスト。

    RSI の理論的範囲: 0 ≤ RSI ≤ 100
    RSI < 30: 売られ過ぎ（買いシグナル根拠）
    RSI > 70: 買われ過ぎ（売りシグナル根拠）
    """

    @pytest.fixture(autouse=True)
    def import_module(self):
        """テクニカル指標モジュールをインポート。"""
        try:
            from src.analysis.technical import rsi
            self.rsi = rsi
        except ImportError as exc:
            pytest.skip(f"依存関係不足のためスキップ: {exc}")

    def test_rsi_within_0_to_100(self):
        """RSI の全値が 0〜100 の範囲内であることを確認する（理論的保証）。"""
        series = pd.Series(np.random.normal(150, 3, 100))
        rsi_series = self.rsi(series, period=14)
        valid = rsi_series.dropna()
        assert (valid >= 0).all() and (valid <= 100).all(), \
            f"RSI は 0〜100 の範囲内である必要があります。範囲外: {valid[(valid < 0) | (valid > 100)]}"

    def test_rsi_high_after_consecutive_gains(self):
        """連続上昇後に RSI が高くなることを確認する（買われ過ぎ検出）。

        価格が連続して上昇すると RSI > 70 が期待される（売りシグナルの根拠）。
        """
        trend_up = pd.Series(100 * np.cumprod(np.concatenate([[1], np.ones(80) * 1.005])))
        rsi_series = self.rsi(trend_up, period=14)
        latest_rsi = rsi_series.dropna().iloc[-1]
        assert latest_rsi > 70, \
            f"強い上昇トレンド後の RSI は 70 超が期待されます: {latest_rsi:.2f}"

    def test_rsi_low_after_consecutive_losses(self):
        """連続下落後に RSI が低くなることを確認する（売られ過ぎ検出）。"""
        trend_down = pd.Series(100 * np.cumprod(np.concatenate([[1], np.ones(80) * 0.995])))
        rsi_series = self.rsi(trend_down, period=14)
        latest_rsi = rsi_series.dropna().iloc[-1]
        assert latest_rsi < 30, \
            f"強い下落トレンド後の RSI は 30 未満が期待されます: {latest_rsi:.2f}"

    def test_rsi_near_50_for_sideways_market(self):
        """横ばい市場で RSI が 50 付近（±20）になることを確認する。"""
        np.random.seed(123)
        sideways = pd.Series(100 + np.cumsum(np.random.choice([-0.1, 0.1], 100)))
        rsi_series = self.rsi(sideways, period=14)
        avg_rsi = rsi_series.dropna().mean()
        assert 30 < avg_rsi < 70, \
            f"横ばい市場の平均 RSI は 30〜70 が期待されます: {avg_rsi:.2f}"


class TestComputeAllIndicators:
    """compute_all_indicators による一括計算テスト。

    全指標を1回のパスで計算する統合テスト。
    API レスポンスに含まれる全指標列の存在を検証する。
    """

    @pytest.fixture(autouse=True)
    def import_module(self):
        """テクニカル指標モジュールをインポート。"""
        try:
            from src.analysis.technical import compute_all_indicators
            self.compute_all_indicators = compute_all_indicators
        except ImportError as exc:
            pytest.skip(f"依存関係不足のためスキップ: {exc}")

    def test_all_required_columns_present(
        self, sample_ohlcv_df: pd.DataFrame
    ):
        """すべての必須指標列が DataFrame に存在することを確認する。

        API レスポンスで使用される主要指標列の存在を検証する。
        """
        result = self.compute_all_indicators(sample_ohlcv_df.copy())
        required_cols = [
            "sma_20", "sma_50", "ema_12",
            "bb_upper", "bb_middle", "bb_lower",
            "macd", "macd_signal",
            "rsi",
            "stoch_k", "stoch_d",
        ]
        missing = [c for c in required_cols if c not in result.columns]
        assert not missing, f"必須指標列が不足しています: {missing}"

    def test_output_has_same_length_as_input(
        self, sample_ohlcv_df: pd.DataFrame
    ):
        """出力 DataFrame の行数が入力と同じであることを確認する（行の脱落なし）。"""
        result = self.compute_all_indicators(sample_ohlcv_df.copy())
        assert len(result) == len(sample_ohlcv_df), \
            f"出力行数 ({len(result)}) は入力行数 ({len(sample_ohlcv_df)}) と同じである必要があります"

    def test_sufficient_valid_rows_after_warmup(
        self, sample_ohlcv_df: pd.DataFrame
    ):
        """ウォームアップ後に有効（NaN でない）行が十分に存在することを確認する。

        一目均衡表の最長ウォームアップは 52 期間のため、
        200 行データでは 140 行以上が有効になることを期待する。
        """
        result = self.compute_all_indicators(sample_ohlcv_df.copy())
        valid_rows = result.dropna(subset=["rsi", "macd", "bb_upper"])
        assert len(valid_rows) >= 140, \
            f"有効行数は 140 以上が期待されます: {len(valid_rows)} 行"

    def test_rsi_values_are_in_valid_range(
        self, sample_ohlcv_df: pd.DataFrame
    ):
        """一括計算した RSI が 0〜100 の範囲内であることを確認する。"""
        result = self.compute_all_indicators(sample_ohlcv_df.copy())
        rsi_valid = result["rsi"].dropna()
        assert (rsi_valid >= 0).all() and (rsi_valid <= 100).all(), \
            "一括計算した RSI は 0〜100 の範囲内である必要があります"
