"""
テクニカルシグナル抽出・バックテストモジュール

このモジュールは複数のテクニカル指標から売買シグナルを抽出し、
シグナルの集計バイアス判定と簡易バックテストを提供する。

【シグナル生成の基本方針】
複数の独立したテクニカル指標（RSI・MACD・BB・Stochastic）を
組み合わせることで、単一指標よりもノイズを低減した売買判断を行う。
各指標の買いシグナル数と売りシグナル数を比較し、多数決で方向性を決定する。

【バックテストについて】
- 評価方法: シグナル発生の翌日終値への方向一致率（勝率）を算出
- 制約: 取引コスト（スプレッド）・スリッページは未考慮
- 用途: 戦略の有効性の簡易確認（本番環境での利用前に詳細検証が必要）
"""

import pandas as pd


def signals_from_row(row: pd.Series) -> list[dict]:
    """1 行分の指標値から売買シグナルリストを生成する。

    対応指標と判定閾値:

    【RSI（相対力指数）】
    - RSI < 30: 買いシグナル（「売られ過ぎ」状態 — 反発を期待）
    - RSI > 70: 売りシグナル（「買われ過ぎ」状態 — 下落を期待）
    - 閾値根拠: Wilder（1978）が提唱した標準的な水準。
               極端な価格乖離は平均回帰する傾向があるため。

    【MACD（移動平均収束拡散法）】
    - MACD > シグナル線: 買いシグナル（短期 EMA が長期 EMA を上回る勢い）
    - MACD < シグナル線: 売りシグナル（短期 EMA が長期 EMA を下回る勢い）
    - ゴールデンクロス（下から上抜け）/デッドクロス（上から下抜け）を簡易判定

    【ボリンジャーバンド（BB）】
    - 終値 < 下限バンド: 買いシグナル（統計的に安い水準）
    - 終値 > 上限バンド: 売りシグナル（統計的に高い水準）
    - バンドは ±2σ（標準偏差）であり、約 95% の価格がこの範囲に収まる。
      バンドタッチは統計的異常を示すため、平均回帰を期待したシグナル。

    【ストキャスティクス（%K・%D）】
    - %K < 20 かつ %D < 20: 買いシグナル（売られ過ぎ圏）
    - %K > 80 かつ %D > 80: 売りシグナル（買われ過ぎ圏）
    - %K と %D の両方が閾値を超えることを条件とし、
      ダマシのシグナルを減らすため両線の一致を必須とする。

    Args:
        row: `compute_all_indicators` で計算済みの指標を含む DataFrame の 1 行。
             "rsi"・"macd"・"macd_signal"・"bb_lower"・"bb_upper"・
             "close"・"stoch_k"・"stoch_d" の列を使用。

    Returns:
        シグナルを表す dict のリスト。各 dict は以下のキーを持つ:
        - indicator: 指標名（"RSI" | "MACD" | "Bollinger Bands" | "Stochastic"）
        - signal: 方向（"buy" | "sell"）
        - value: 指標値（RSI のみ。他は省略可）
        - reason: シグナル根拠の説明（日本語）
        シグナルなしの場合は空リストを返す。
    """
    signals = []

    # RSI シグナル: 30 以下で売られ過ぎ（買い）、70 以上で買われ過ぎ（売り）
    if pd.notna(row.get("rsi")):
        if row["rsi"] < 30:
            signals.append({"indicator": "RSI", "signal": "buy", "value": round(row["rsi"], 2), "reason": "売られ過ぎ"})
        elif row["rsi"] > 70:
            signals.append({"indicator": "RSI", "signal": "sell", "value": round(row["rsi"], 2), "reason": "買われ過ぎ"})

    # MACD シグナル: MACD 線とシグナル線の大小関係で判定
    # 両値が NaN でないことを確認してから比較
    if pd.notna(row.get("macd")) and pd.notna(row.get("macd_signal")):
        if row["macd"] > row["macd_signal"]:
            signals.append({"indicator": "MACD", "signal": "buy", "reason": "MACDがシグナル線を上抜け"})
        elif row["macd"] < row["macd_signal"]:
            signals.append({"indicator": "MACD", "signal": "sell", "reason": "MACDがシグナル線を下抜け"})

    # ボリンジャーバンド シグナル: 終値がバンド外に出た場合に平均回帰を期待
    if pd.notna(row.get("bb_lower")) and pd.notna(row.get("bb_upper")):
        if row["close"] < row["bb_lower"]:
            signals.append({"indicator": "Bollinger Bands", "signal": "buy", "reason": "下限バンドタッチ"})
        elif row["close"] > row["bb_upper"]:
            signals.append({"indicator": "Bollinger Bands", "signal": "sell", "reason": "上限バンドタッチ"})

    # ストキャスティクス シグナル: %K・%D 両方が閾値を超えた場合のみシグナル発生
    # 20/80 は標準的な売られ過ぎ/買われ過ぎの閾値（0〜100 スケール）
    if pd.notna(row.get("stoch_k")) and pd.notna(row.get("stoch_d")):
        if row["stoch_k"] < 20 and row["stoch_d"] < 20:
            signals.append({"indicator": "Stochastic", "signal": "buy", "reason": "売られ過ぎ圏"})
        elif row["stoch_k"] > 80 and row["stoch_d"] > 80:
            signals.append({"indicator": "Stochastic", "signal": "sell", "reason": "買われ過ぎ圏"})

    return signals


def aggregate_bias(signals: list[dict]) -> str:
    """シグナルリストを集計し、全体的な売買バイアスを判定する。

    複数のテクニカル指標シグナルを多数決で集計する。
    買いシグナル数と売りシグナル数を比較し、多い方の方向を採用。

    判定ロジック:
    - 買いシグナル数 > 売りシグナル数 → "buy"
    - 売りシグナル数 > 買いシグナル数 → "sell"
    - 同数（タイ）→ "neutral"（方向感なし）

    例: RSI が売り、MACD が買い、BB がシグナルなし、Stoch が買い
        → buy: 2, sell: 1 → バイアス = "buy"

    Args:
        signals: `signals_from_row` の戻り値のシグナルリスト。

    Returns:
        集計バイアス文字列: "buy" | "sell" | "neutral"
    """
    buy = sum(1 for s in signals if s["signal"] == "buy")
    sell = sum(1 for s in signals if s["signal"] == "sell")
    if buy > sell:
        return "buy"
    if sell > buy:
        return "sell"
    return "neutral"


def backtest_signals(result_df: pd.DataFrame) -> dict:
    """ルールベースシグナルの簡易バックテストを実施する（翌日終値方向で評価）。

    【バックテスト方法論】
    - エントリー: 各バーでシグナルが "buy" または "sell" に確定した時点
    - エグジット: 翌バーの終値（ホールド期間 = 1 バー固定）
    - 勝ち条件:
        - buy シグナル かつ 翌日終値が上昇 → 勝ち
        - sell シグナル かつ 翌日終値が下落 → 勝ち
    - リターン計算:
        ret_pct = (翌終値 - 現終値) / 現終値 × 100
        buy の場合はそのまま、sell の場合は符号を反転（空売り想定）

    【制約・注意事項】
    - スプレッド・手数料・スリッページ未考慮（実際の損益はこれより悪化する）
    - ウォームアップ期間として最初の 50 バーはスキップ
      （SMA50 等の指標が収束するのに最低 50 バー必要）
    - 1 バーホールドのみ（複数バー保有戦略の評価は不可）
    - 過去へのカーブフィッティングのリスクに注意

    Args:
        result_df: `compute_all_indicators` の戻り値（全指標計算済み DataFrame）。
                   "close" 列と各指標列が必要。

    Returns:
        以下のキーを持つ dict:
        - total_trades: 総トレード数（シグナル発生バー数）
        - win_rate: 勝率（%）
        - avg_return_pct: 平均リターン（%）
        - buy_trades: 買いトレード数
        - sell_trades: 売りトレード数
        - period_bars: 評価期間のバー数
        シグナルが発生しなかった場合は各値 0 と message を返す。
    """
    trades: list[dict] = []

    # 最初の 50 バーはスキップ（SMA50 等の指標ウォームアップ期間）
    # 最後のバーは「翌バー」が存在しないためスキップ（len - 1 まで）
    for i in range(50, len(result_df) - 1):
        row = result_df.iloc[i]
        next_close = float(result_df.iloc[i + 1]["close"])
        current_close = float(row["close"])
        # 終値が 0 の場合はデータ異常としてスキップ
        if current_close == 0:
            continue

        signals = signals_from_row(row)
        bias = aggregate_bias(signals)
        # neutral（方向感なし）の場合はトレードなし
        if bias == "neutral":
            continue

        # リターン計算: (翌終値 - 現終値) / 現終値 × 100
        ret_pct = (next_close - current_close) / current_close * 100
        # 勝ち判定: バイアス方向と実際の価格変動が一致したか
        win = (bias == "buy" and ret_pct > 0) or (bias == "sell" and ret_pct < 0)
        # sell の場合はリターンを反転（空売り想定: 下落が利益）
        trades.append({"bias": bias, "return_pct": round(ret_pct if bias == "buy" else -ret_pct, 4), "win": win})

    # シグナルが全く発生しなかった場合はデフォルト値を返す
    if not trades:
        return {
            "total_trades": 0,
            "win_rate": 0,
            "avg_return_pct": 0,
            "buy_trades": 0,
            "sell_trades": 0,
            "message": "十分なシグナルがありません",
        }

    wins = sum(1 for t in trades if t["win"])
    return {
        "total_trades": len(trades),
        # 勝率 = 勝ちトレード数 ÷ 総トレード数 × 100
        "win_rate": round(wins / len(trades) * 100, 1),
        # 平均リターン = 全トレードのリターン合計 ÷ トレード数
        "avg_return_pct": round(sum(t["return_pct"] for t in trades) / len(trades), 4),
        "buy_trades": sum(1 for t in trades if t["bias"] == "buy"),
        "sell_trades": sum(1 for t in trades if t["bias"] == "sell"),
        "period_bars": len(result_df),
    }
