"""
マーケットコンテキスト管理モジュール

1リクエスト内で同一シンボルの OHLCV データおよびテクニカル指標計算結果を
共有・再利用するためのデータクラスを提供する。

目的:
  - 同一リクエスト内で複数の分析モジュールが OHLCV データや指標を参照する際に、
    重複した DB 問い合わせや計算コストを削減する（インメモリキャッシュの役割）。
  - MarketContext オブジェクトを1度生成すれば、price・atr などの
    プロパティ経由で指標値に手軽にアクセスできる。

使用例:
    ctx = MarketContext.load("USDJPY", days=200)
    current_price = ctx.price
    atr_value = ctx.atr
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from src.analysis.technical import compute_all_indicators
from src.analysis.volatility import calc_atr
from src.data.market_data import get_ohlcv_data


@dataclass
class MarketContext:
    """シンボル単位の市場データとテクニカル指標を保持するコンテキストクラス。

    1リクエストのライフサイクル内で同一シンボルのデータを共有する目的で使用する。
    通常は MarketContext.load() クラスメソッドを通じてインスタンスを生成する。

    Attributes:
        symbol: 通貨ペアシンボル（大文字）。例: "USDJPY"。
        days: データ取得日数。デフォルトは 200 日分。
        source: OHLCV データのソース識別文字列（"oanda", "sample" など）。
        result_df: テクニカル指標を計算済みの pandas DataFrame。
                   カラム: close, open, high, low, volume, timestamp,
                           sma_20, sma_50, ema_12, ema_26, rsi,
                           macd, macd_signal, macd_histogram,
                           bb_upper, bb_lower, atr 等。
    """

    symbol: str
    days: int
    source: str
    result_df: pd.DataFrame

    @property
    def price(self) -> float:
        """最新の終値（現在価格）を返す。

        result_df の最終行の close カラムから取得する。
        日足データの場合は当日の終値、リアルタイムデータの場合は最新のティック価格に近い値。

        Returns:
            最新終値（float）。
        """
        return float(self.result_df["close"].iloc[-1])

    @property
    def atr(self) -> float | None:
        """ATR（Average True Range: 平均真の値幅）を返す。

        ATR は価格のボラティリティを数値化した指標で、以下の計算式で算出される:
          True Range (TR) = max(
              High - Low,                   # 当日の値幅
              |High - 前日Close|,            # 上方ギャップを考慮した値幅
              |Low  - 前日Close|             # 下方ギャップを考慮した値幅
          )
          ATR = TR の期間（通常14）の単純移動平均

        ATR が大きいほどボラティリティが高く、損切り幅や利確目標の設定に使用される。

        Returns:
            ATR 値（float）。計算不能な場合は None。
        """
        return calc_atr(self.result_df)

    @classmethod
    def load(cls, symbol: str, days: int = 200) -> MarketContext:
        """OHLCV データを取得し、テクニカル指標を計算して MarketContext を生成する。

        データ取得から指標計算までを一括で実行するファクトリメソッド。
        get_ohlcv_data() が返す生の OHLCV DataFrame に対して
        compute_all_indicators() を適用し、指標付きの DataFrame を作成する。

        Args:
            symbol: 通貨ペアシンボル（大文字・小文字どちらでも可）。例: "usdjpy"。
            days: 取得する日数。デフォルト 200 日。
                  テクニカル指標（特に SMA50）の計算には最低50本以上のデータが必要。

        Returns:
            指標計算済みの MarketContext インスタンス。

        Raises:
            ValueError: シンボルが存在しない場合や市場データが取得できない場合。
        """
        # OHLCV データを取得する（ブローカー API またはサンプルデータ）
        df, source = get_ohlcv_data(symbol, days)
        # SMA・EMA・RSI・MACD・ボリンジャーバンド等を一括計算する
        result_df = compute_all_indicators(df)
        # シンボルを大文字に正規化してインスタンスを生成する
        return cls(symbol.upper(), days, source, result_df)
