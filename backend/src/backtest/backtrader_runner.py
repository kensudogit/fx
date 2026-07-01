"""
Backtrader フレームワークを使った戦略バックテストモジュール

Backtrader ライブラリを使って RSI + MACD クロスオーバー戦略を
過去データでバックテストし、収益性を評価するモジュール。

使用戦略:
    RsiMacdStrategy:
        - エントリー条件: RSI < 30（売られすぎ）かつ MACD がシグナルラインを上抜け
        - 決済条件: RSI > 70（買われすぎ）または MACD がシグナルラインを下抜け
        - 取引コスト: 0.02%（片道）

依存ライブラリ:
    backtrader は任意インストール。未インストールの場合はエラーメッセージを返す。
"""

import pandas as pd

# テクニカル指標計算（RSI, MACD, ボリンジャーバンド等）
from src.analysis.technical import compute_all_indicators
# 過去 OHLCV データ取得（OANDA / Yahoo / サンプルデータのフォールバック付き）
from src.data.market_data import get_ohlcv_data


def run_backtrader_backtest(symbol: str, days: int = 200, cash: float = 10000) -> dict:
    """Backtrader を使って RSI + MACD 戦略のバックテストを実行する。

    実行フロー:
        1. backtrader ライブラリのインポートを試みる（未インストール時はエラー返却）
        2. 過去 OHLCV データを取得してテクニカル指標を計算
        3. Backtrader の PandasData フィードとして読み込む
        4. RSI + MACD クロスオーバー戦略を設定して実行
        5. 初期資金と最終資産を比較してトータルリターンを算出

    戦略の詳細 (RsiMacdStrategy):
        next() メソッドが各バーで呼ばれる:
            ポジション保有中:
                - RSI > 70（買われすぎ）または MACD < シグナルライン → 決済（sell）
            ポジション未保有:
                - RSI < 30（売られすぎ）かつ MACD > シグナルライン → 買いエントリー（buy）

    Args:
        symbol: 通貨ペアコード（例: "USDJPY"）
        days: バックテスト期間（日数、最低60日分のデータが必要）
        cash: 初期資金（USD、デフォルト: 10,000）

    Returns:
        バックテスト結果の辞書:
            成功時:
                - status: "success"
                - engine: "backtrader"
                - symbol: 通貨ペア
                - source: データ取得元
                - initial_cash: 初期資金
                - final_value: 最終資産額
                - total_return_pct: トータルリターン（%）
                - bars: 使用したバー数
                - strategy: 戦略説明
            失敗時:
                - status: "error"
                - message: エラーメッセージ
    """
    # backtrader は任意依存のため動的インポート
    try:
        import backtrader as bt
    except ImportError:
        return {"status": "error", "message": "backtrader がインストールされていません"}

    try:
        # 過去データを取得してテクニカル指標を計算
        df, source = get_ohlcv_data(symbol, days)
        # データが少なすぎる場合はエラー（RSI/MACD 計算に最低60バー必要）
        if len(df) < 60:
            return {"status": "error", "message": "データ不足"}

        # テクニカル指標を追加したデータフレームを生成
        result_df = compute_all_indicators(df)

        # Backtrader が必要とするカラムを選択して NaN を除去
        data = result_df[["timestamp", "open", "high", "low", "close", "volume", "rsi", "macd", "macd_signal"]].copy()
        data = data.dropna(subset=["close", "rsi", "macd", "macd_signal"])
        # timestamp をインデックスに設定（PandasData の要件）
        data = data.set_index("timestamp")
        data.index = pd.to_datetime(data.index)

        class RsiMacdStrategy(bt.Strategy):
            """RSI + MACD クロスオーバーを組み合わせた売買戦略。

            パラメータ:
                rsi_low: 買いシグナルの RSI 閾値（デフォルト: 30、売られすぎゾーン）
                rsi_high: 売りシグナルの RSI 閾値（デフォルト: 70、買われすぎゾーン）

            エントリー:
                RSI が売られすぎゾーンで MACD がシグナルを上抜けた場合に買いエントリー

            エグジット:
                RSI が買われすぎゾーンに達するか、MACD がシグナルを下抜けた場合に決済
            """

            params = dict(rsi_low=30, rsi_high=70)

            def __init__(self):
                """インジケーターを初期化する。

                Backtrader の組み込みインジケーターを使用:
                    - RSI: 14期間の相対力指数
                    - MACD: 終値ベースの MACD ラインとシグナルライン
                """
                # 14期間 RSI（オーバーソールド/オーバーバウト判定用）
                self.rsi = bt.indicators.RSI(self.data.close, period=14)
                # MACD インジケーター（EMA12 - EMA26、シグナルは EMA9）
                self.macd = bt.indicators.MACD(self.data.close)

            def next(self):
                """各バー（ローソク足）で呼び出される売買ロジック。

                Backtrader のコールバックメソッド。データが蓄積されるたびに
                最新バーのデータで売買判定を行う。

                ポジション保有中の決済判定:
                    - RSI > 70（買われすぎ）→ 利確/損切り
                    - MACD ラインがシグナルラインを下抜け → トレンド転換による決済

                ポジション未保有時のエントリー判定:
                    - RSI < 30（売られすぎ）かつ MACD > シグナル → 買いエントリー
                """
                if self.position:
                    # ポジション保有中: 決済条件を確認
                    if self.rsi[0] > self.params.rsi_high or self.macd.macd[0] < self.macd.signal[0]:
                        # RSI が過熱 または MACD デッドクロス → ポジション決済
                        self.close()
                elif self.rsi[0] < self.params.rsi_low and self.macd.macd[0] > self.macd.signal[0]:
                    # ポジション未保有: 売られすぎ + MACD ゴールデンクロス → 買いエントリー
                    self.buy()

        # Cerebro エンジンを作成してコンポーネントを設定
        cerebro = bt.Cerebro()
        # Pandas DataFrame をフィードとして追加
        feed = bt.feeds.PandasData(dataname=data)
        cerebro.adddata(feed)
        # RSI + MACD 戦略を追加
        cerebro.addstrategy(RsiMacdStrategy)
        # 初期資金と手数料を設定（0.02% = FX スプレッドの概算）
        cerebro.broker.setcash(cash)
        cerebro.broker.setcommission(commission=0.0002)

        # バックテスト開始前の資産を記録
        start_value = cerebro.broker.getvalue()
        # バックテストを実行（全バーにわたって next() が順次呼ばれる）
        cerebro.run()
        # バックテスト終了後の資産を取得
        end_value = cerebro.broker.getvalue()

        # トータルリターンを計算（%）
        total_return = (end_value - start_value) / start_value * 100
        return {
            "status": "success",
            "engine": "backtrader",
            "symbol": symbol.upper(),
            "source": source,
            "initial_cash": cash,
            "final_value": round(end_value, 2),
            "total_return_pct": round(total_return, 2),
            "bars": len(data),
            "strategy": "RSI(30/70) + MACD crossover",
        }
    except Exception as e:
        return {"status": "error", "message": f"バックテスト失敗: {e}"}
