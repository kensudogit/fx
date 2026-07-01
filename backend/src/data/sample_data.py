"""
サンプル市場データ生成モジュール — data/sample_data

外部 API（Yahoo Finance / PostgreSQL）が利用できない環境でも
テクニカル分析・ML 予測機能が動作するように、リアルな FX レートを模擬した
OHLCV データを確定的（再現可能）なアルゴリズムで生成します。

生成されるデータの特性:
    - 幾何ブラウン運動（対数正規分布）に基づく価格推移
    - 実際の FX 市場に近いボラティリティ（日次リターン標準偏差 約 0.5%）
    - 日中値動きを模擬した高値・安値・始値の生成
    - 営業日（平日）のみのデータ点（週末・祝日除外）

使用場面:
    - ローカル開発環境（DB / Yahoo Finance 未設定時）
    - テスト・デモ環境でのデータ補完
    - 統合テストにおける決定論的データの確保
"""

import numpy as np
import pandas as pd


def generate_sample_ohlcv(
    symbol: str = "USDJPY",
    days: int = 200,
    base_price: float = 150.0,
) -> pd.DataFrame:
    """
    指定シンボルのサンプル OHLCV データを生成する。

    幾何ブラウン運動モデルに基づいて価格系列を生成し、
    各営業日の始値・高値・安値を確率的に決定する。
    np.random.seed(42) により同じ引数では常に同一データが生成される（決定論的）。

    アルゴリズム:
        1. 日次リターン = 正規分布 N(0.0002, 0.005) をサンプリング
           （年率換算: 期待リターン ≈ 5%、ボラティリティ ≈ 8%）
        2. 累積積（cumprod）で終値系列を生成（対数正規分布に従う価格推移）
        3. 日中値動き幅 = 終値 × U(0.003, 0.012)（0.3% 〜 1.2% の日中レンジ）
        4. 高値 = 終値 + 値動き幅 × U(0.3, 0.7)（終値より高い位置）
        5. 安値 = 終値 - 値動き幅 × U(0.3, 0.7)（終値より低い位置）
        6. 始値 = 安値 + (高値 - 安値) × U(0.2, 0.8)（高値・安値の間）

    Args:
        symbol: 通貨ペアシンボル（現在は生成ロジックに影響しない。将来の拡張用）
        days: 生成する営業日数（デフォルト: 200 日）
        base_price: 価格系列の基準値（例: USDJPY なら 150.0、EURUSD なら 1.08）

    Returns:
        以下の列を持つ pandas DataFrame:
            - timestamp: 営業日の日付時刻（pd.Timestamp）
            - open: 始値（小数点 3 桁に丸め）
            - high: 高値（小数点 3 桁に丸め）
            - low: 安値（小数点 3 桁に丸め）
            - close: 終値（小数点 3 桁に丸め）
            - volume: 出来高（100,000〜500,000 の整数乱数）
    """
    # シードを固定して再現可能な乱数系列を生成（テスト・開発の一貫性確保）
    np.random.seed(42)
    # pd.date_range(freq="B"): 週末を除いた営業日（Business Day）系列を生成
    dates = pd.date_range(end=pd.Timestamp.now(), periods=days, freq="B")

    # 日次リターンを正規分布からサンプリング
    # mean=0.0002: わずかな上昇バイアス（年率換算で約 +5%）
    # std=0.005: 日次ボラティリティ（年率換算で約 ±8%、実際の FX に近い値）
    returns = np.random.normal(0.0002, 0.005, days)
    # 累積積で終値系列を生成（対数正規過程: 価格が負にならない性質を持つ）
    # base_price × (1 + r1) × (1 + r2) × ... × (1 + rN)
    close_prices = base_price * np.cumprod(1 + returns)

    data = []
    for i, date in enumerate(dates):
        close = close_prices[i]
        # 日中値動き幅: 終値の 0.3% 〜 1.2% の範囲でランダム決定
        # 実際の FX 市場の日中変動幅を模擬
        daily_range = close * np.random.uniform(0.003, 0.012)
        # 高値は終値より上（値動き幅の 30%〜70% を加算）
        high = close + daily_range * np.random.uniform(0.3, 0.7)
        # 安値は終値より下（値動き幅の 30%〜70% を減算）
        low = close - daily_range * np.random.uniform(0.3, 0.7)
        # 始値は安値〜高値の範囲内でランダムに配置（20%〜80% の位置）
        open_price = low + (high - low) * np.random.uniform(0.2, 0.8)
        # 出来高: FX では参考値として 10 万〜50 万の整数乱数を使用
        volume = int(np.random.uniform(100000, 500000))

        data.append(
            {
                "timestamp": date,
                "open": round(open_price, 3),   # 小数点 3 桁（pip 精度に相当）
                "high": round(high, 3),
                "low": round(low, 3),
                "close": round(close, 3),
                "volume": volume,
            }
        )

    return pd.DataFrame(data)


# ── サポート対象通貨ペアと基準価格 ──────────────────────
# サンプルデータ生成時の初期価格として使用する。
# 実際の市場レートに近い値を設定することで、リアルな分析結果を模擬できる。
SYMBOL_BASE_PRICES = {
    "USDJPY": 150.0,  # 米ドル / 日本円（単位: 円）
    "EURUSD": 1.08,   # ユーロ / 米ドル（単位: USD）
    "GBPUSD": 1.27,   # 英ポンド / 米ドル（単位: USD）
    "AUDUSD": 0.65,   # 豪ドル / 米ドル（単位: USD）
}
