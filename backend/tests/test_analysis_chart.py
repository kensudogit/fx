"""matplotlib チャート生成 — src.analysis.chart のテスト

実際に PNG を生成し、バイト列の妥当性と Figure の後始末を検証する。
"""

import matplotlib.pyplot as plt
import pandas as pd
import pytest

from src.analysis.chart import generate_technical_chart

# PNG ファイルのマジックナンバー（先頭 8 バイト）
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


@pytest.fixture
def chart_df(ohlcv) -> pd.DataFrame:
    """チャート生成に必要な timestamp 列を備えた OHLCV を返す。"""
    df = ohlcv.copy()
    df["timestamp"] = df.index
    return df


class TestGenerateTechnicalChart:
    """generate_technical_chart() のテスト"""

    def test_returns_png_bytes(self, chart_df):
        """PNG のバイト列を返すこと"""
        png = generate_technical_chart(chart_df, "USDJPY")
        assert isinstance(png, bytes)
        assert png.startswith(PNG_SIGNATURE)

    def test_output_is_not_empty(self, chart_df):
        """実際に描画された十分なサイズの画像であること"""
        assert len(generate_technical_chart(chart_df, "USDJPY")) > 10_000

    def test_all_indicator_mode_produces_a_taller_image(self, chart_df):
        """indicator='all' では RSI・MACD を加えた 3 段構成になること"""
        price_only = generate_technical_chart(chart_df, "USDJPY", indicator="price")
        with_all = generate_technical_chart(chart_df, "USDJPY", indicator="all")
        # 3 段構成のほうが縦に長く、データ量も大きくなる
        assert len(with_all) > len(price_only)

    @pytest.mark.parametrize("indicator", ["price", "all", "unknown"])
    def test_accepts_indicator_variants(self, chart_df, indicator):
        """未知の指標名でも price 相当にフォールバックして描画できること"""
        assert generate_technical_chart(chart_df, "USDJPY", indicator).startswith(PNG_SIGNATURE)

    def test_symbol_is_used_without_error(self, chart_df):
        """任意のシンボル名でタイトルを描画できること"""
        assert generate_technical_chart(chart_df, "EUR/USD テスト").startswith(PNG_SIGNATURE)

    def test_closes_the_figure(self, chart_df):
        """Figure を閉じてメモリリークを防ぐこと"""
        plt.close("all")
        generate_technical_chart(chart_df, "USDJPY", indicator="all")
        assert plt.get_fignums() == []

    def test_does_not_mutate_the_input(self, chart_df):
        """入力 DataFrame に指標列を書き足さないこと"""
        before = list(chart_df.columns)
        generate_technical_chart(chart_df, "USDJPY")
        assert list(chart_df.columns) == before

    def test_uses_a_headless_backend(self):
        """GUI のないサーバーでも動くよう Agg バックエンドを使うこと"""
        import matplotlib
        assert matplotlib.get_backend().lower() == "agg"

    def test_repeated_calls_are_stable(self, chart_df):
        """繰り返し呼んでも Figure が蓄積しないこと"""
        plt.close("all")
        for _ in range(3):
            generate_technical_chart(chart_df, "USDJPY")
        assert plt.get_fignums() == []
