"""
ウォークフォワード分析モジュール

過去データを「学習期間（In-Sample/IS）」と「検証期間（Out-of-Sample/OOS）」に
時系列で分割し、戦略の過学習度合い（堅牢性）を評価するモジュール。

ウォークフォワード分析の概念:
    - In-Sample (IS): 戦略パラメータを最適化・学習する期間
    - Out-of-Sample (OOS): 学習結果の汎化性能を検証する期間
    - IS と OOS の勝率乖離が小さいほど過学習が少なく「堅牢」と判断できる

ウィンドウ構成:
    ┌──── train_bars ──────┬─ test_bars ─┐
    │  In-Sample (IS)       │ OOS         │
    └──────────────────────┴─────────────┘
                       ↓ step_bars 分スライド
    ┌──── train_bars ──────┬─ test_bars ─┐
    │  In-Sample (IS)       │ OOS         │
    └──────────────────────┴─────────────┘

堅牢性評価基準:
    - good    : IS/OOS 乖離 < 10% かつ OOS 勝率 >= 45%
    - moderate: IS/OOS 乖離 < 20%
    - weak    : IS/OOS 乖離 >= 20%（過学習の可能性大）
"""

import pandas as pd

# シグナルベースのバックテスト（勝率・トレード数・平均リターン算出）
from src.analysis.signals import backtest_signals
# テクニカル指標計算
from src.analysis.technical import compute_all_indicators
# 過去 OHLCV データ取得
from src.data.market_data import get_ohlcv_data


def run_walk_forward(
    symbol: str,
    days: int = 365,
    train_bars: int = 120,
    test_bars: int = 40,
    step_bars: int = 40,
) -> dict:
    """ウォークフォワード分析を実行して戦略の堅牢性を評価する。

    時系列データを IS（学習）/ OOS（検証）ウィンドウに分割し、
    各ウィンドウでバックテストを実行して IS と OOS の成績を比較する。
    IS/OOS 間の勝率乖離から過学習度合いを定量化する。

    必要データ量:
        train_bars + test_bars + 20 バー以上（ウィンドウ生成に最低限必要）

    Args:
        symbol: 通貨ペアコード（例: "USDJPY"）
        days: 取得する過去データの日数（デフォルト: 365日）
        train_bars: IS（学習）期間のバー数（デフォルト: 120バー = 約4ヶ月）
        test_bars: OOS（検証）期間のバー数（デフォルト: 40バー = 約1.5ヶ月）
        step_bars: ウィンドウのスライド幅（デフォルト: 40バー）

    Returns:
        分析結果の辞書:
            成功時:
                - status: "success"
                - symbol: 通貨ペア
                - source: データ取得元
                - train_bars / test_bars / step_bars: ウィンドウ設定
                - windows: 各ウィンドウの詳細結果リスト
                - summary: 集計サマリー（平均勝率・堅牢性評価等）
            失敗時:
                - status: "error"
                - message: エラーメッセージ
    """
    # 過去データを取得してテクニカル指標を計算
    df, source = get_ohlcv_data(symbol, days)
    result_df = compute_all_indicators(df)

    # 最低必要バー数のチェック（ウィンドウを1つも生成できない場合はエラー）
    if len(result_df) < train_bars + test_bars + 20:
        return {"status": "error", "message": "データ不足（ウォークフォワードには最低約180日必要）"}

    windows: list[dict] = []
    start = 0  # 現在のウィンドウの開始インデックス
    idx = 0    # ウィンドウの通し番号

    # === ウィンドウのスライド処理 ===
    # start が train_bars + test_bars のスペースを確保できる間ループ
    while start + train_bars + test_bars <= len(result_df):
        # In-Sample（IS）スライス: 学習・最適化に使用するデータ
        train_slice = result_df.iloc[start : start + train_bars]
        # Out-of-Sample（OOS）スライス: IS で最適化された戦略の汎化検証データ
        test_slice = result_df.iloc[start + train_bars : start + train_bars + test_bars]

        # IS と OOS それぞれでバックテストを実行
        train_bt = backtest_signals(train_slice)
        test_bt = backtest_signals(test_slice)

        # ウィンドウ結果を記録（日付はタイムスタンプの最初の10文字 = YYYY-MM-DD）
        windows.append({
            "window": idx + 1,
            # IS（学習）期間の開始・終了日
            "train_start": str(train_slice["timestamp"].iloc[0])[:10],
            "train_end": str(train_slice["timestamp"].iloc[-1])[:10],
            # OOS（検証）期間の開始・終了日
            "test_start": str(test_slice["timestamp"].iloc[0])[:10],
            "test_end": str(test_slice["timestamp"].iloc[-1])[:10],
            # IS の成績
            "in_sample": {
                "win_rate": train_bt["win_rate"],
                "total_trades": train_bt["total_trades"],
                "avg_return_pct": train_bt["avg_return_pct"],
            },
            # OOS の成績（IS と比較して過学習を評価）
            "out_of_sample": {
                "win_rate": test_bt["win_rate"],
                "total_trades": test_bt["total_trades"],
                "avg_return_pct": test_bt["avg_return_pct"],
            },
        })

        # step_bars 分スライドして次のウィンドウへ
        start += step_bars
        idx += 1

    # ウィンドウが1件も生成できなかった場合
    if not windows:
        return {"status": "error", "message": "ウィンドウを生成できませんでした"}

    # === IS / OOS 統計の集計 ===
    # OOS 勝率の一覧（トレードが1件以上あるウィンドウのみ）
    oos_win = [w["out_of_sample"]["win_rate"] for w in windows if w["out_of_sample"]["total_trades"] > 0]
    # IS 勝率の一覧
    is_win = [w["in_sample"]["win_rate"] for w in windows if w["in_sample"]["total_trades"] > 0]
    # OOS 平均リターンの一覧
    oos_ret = [w["out_of_sample"]["avg_return_pct"] for w in windows if w["out_of_sample"]["total_trades"] > 0]

    # 平均勝率を計算
    avg_oos = sum(oos_win) / len(oos_win) if oos_win else 0
    avg_is = sum(is_win) / len(is_win) if is_win else 0

    # IS/OOS 乖離 = IS の平均勝率 - OOS の平均勝率
    # 乖離が大きいほど過学習の可能性が高い
    degradation = round(avg_is - avg_oos, 1)

    # === 堅牢性評価 ===
    if degradation < 10 and avg_oos >= 45:
        # IS と OOS の乖離が小さく、OOS 勝率も十分 → 堅牢な戦略
        robustness = "good"
        label = "堅牢 — OOSパフォーマンス良好"
    elif degradation < 20:
        # 乖離が中程度 → 一定の過学習リスクあり
        robustness = "moderate"
        label = "中程度 — 過学習の可能性あり"
    else:
        # IS と OOS の乖離が大きい → 過学習の強い疑いあり
        robustness = "weak"
        label = "弱い — IS/OOS乖離が大きい"

    return {
        "status": "success",
        "symbol": symbol.upper(),
        "source": source,
        "train_bars": train_bars,
        "test_bars": test_bars,
        "step_bars": step_bars,
        "windows": windows,
        "summary": {
            "window_count": len(windows),
            "avg_in_sample_win_rate": round(avg_is, 1),
            "avg_out_of_sample_win_rate": round(avg_oos, 1),
            # OOS の平均リターン（実運用パフォーマンスの指標）
            "avg_oos_return_pct": round(sum(oos_ret) / len(oos_ret), 4) if oos_ret else 0,
            # IS/OOS 勝率の乖離（過学習の指標）
            "is_oos_degradation_pct": degradation,
            "robustness": robustness,
            "robustness_label": label,
        },
    }
