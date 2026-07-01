"""
実現損益（PnL）計算モジュール

FX 自動売買システムにおける損益計算の中核モジュール。
ポジション決済時の pips 損益を USD 換算し、集計・週次内訳を提供する。

主な責務:
    - pips → USD 換算による実現損益の算出
    - 決済済みポジション一覧からの PnL 集計（勝率・トレード数）
    - 週次（月曜始まり）の損益内訳生成
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

# pip サイズ（通貨ペアごとの最小変動単位）と
# 1 ロット（100,000 通貨）あたりの pip 価値（USD 建て）を取得するユーティリティ
from src.analysis.position_sizing import pip_size, pip_value_per_lot_usd


def calc_realized_pnl_usd(
    symbol: str,
    side: str,
    units: int,
    entry_price: float,
    close_price: float,
) -> float:
    """決済済みポジションの実現損益を USD で算出する。

    損益計算フロー:
        1. pip サイズを取得（例: USDJPY=0.01、EURUSD=0.0001）
        2. 方向（buy/sell）に応じて pips 差を計算
        3. ユニット数をロット換算（1 ロット = 100,000 通貨）
        4. pip 価値（USD/ロット）を掛けて USD 損益を算出

    Args:
        symbol: 通貨ペアコード（例: "USDJPY", "EURUSD"）
        side: ポジション方向。"buy" または "sell"
        units: 通貨単位数（例: 10000 = 0.1 ロット）
        entry_price: エントリー（建値）価格
        close_price: 決済価格

    Returns:
        実現損益（USD）。小数第2位まで丸め。
        価格が無効または pip サイズが取得できない場合は 0.0 を返す。
    """
    sym = symbol.upper()
    # 通貨ペアに対応する pip サイズを取得（例: USDJPY → 0.01）
    pip = pip_size(sym)
    # pip サイズが取得できない、またはエントリー・決済価格が不正な場合はゼロを返す
    if not pip or entry_price <= 0 or close_price <= 0:
        return 0.0

    # 方向に応じた pips 差の計算
    # buy: 決済価格 - エントリー価格（上昇で利益）
    # sell: エントリー価格 - 決済価格（下落で利益）
    if side == "buy":
        pips = (close_price - entry_price) / pip
    else:
        pips = (entry_price - close_price) / pip

    # ユニット数をロット数に換算（1 ロット = 100,000 通貨）
    lots = units / 100_000

    # 1 ロットあたりの pip 価値（USD）を取得
    # 例: USDJPY は決済時のレートで換算、USD建て通貨ペアは固定 $10/pip
    pip_val = pip_value_per_lot_usd(sym, close_price)

    # 実現損益 = pips × pip価値(USD/lot) × ロット数
    return round(pips * pip_val * lots, 2)


def aggregate_pnl(closed_positions: list[dict]) -> dict:
    """決済済みポジション一覧から損益を集計する。

    各ポジションに realized_pnl_usd が格納されていれば直接使用し、
    なければ calc_realized_pnl_usd を呼び出してオンザフライで計算する。

    Args:
        closed_positions: 決済済みポジション情報のリスト。
            各辞書には以下のキーを含む:
                - realized_pnl_usd (float, オプション): 事前計算済み損益
                - symbol (str): 通貨ペア
                - side (str): "buy" または "sell"
                - units (int/str): 通貨単位数
                - entry_price (float/str): エントリー価格
                - close_price (float/str): 決済価格

    Returns:
        損益集計辞書:
            - total_realized_usd: 合計実現損益（USD）
            - closed_trades: 決済トレード総数
            - wins: 利益トレード数
            - losses: 損失トレード数
            - win_rate_pct: 勝率（%、小数第1位）
    """
    total = 0.0
    wins = 0
    losses = 0

    for pos in closed_positions:
        # 事前計算済みの損益を優先使用（ない場合はオンデマンド計算）
        pnl = pos.get("realized_pnl_usd")
        if pnl is None:
            pnl = calc_realized_pnl_usd(
                pos["symbol"],
                pos["side"],
                int(pos["units"]),
                float(pos["entry_price"]),
                float(pos["close_price"]),
            )
        total += pnl

        # 勝敗を分類（ゼロはドローとして wins/losses 両方に含めない）
        if pnl > 0:
            wins += 1
        elif pnl < 0:
            losses += 1

    closed_count = len(closed_positions)
    # 決済済みトレードがある場合のみ勝率を計算（ゼロ除算回避）
    win_rate = round(wins / closed_count * 100, 1) if closed_count else 0.0
    return {
        "total_realized_usd": round(total, 2),
        "closed_trades": closed_count,
        "wins": wins,
        "losses": losses,
        "win_rate_pct": win_rate,
    }


def weekly_pnl_breakdown(closed_positions: list[dict], weeks: int = 4) -> list[dict]:
    """決済済みポジション一覧を週次（月曜始まり）に集計して内訳を返す。

    直近 weeks 週分のバケットを事前に生成し、各ポジションを
    決済日時（closed_at）に基づいて適切な週バケットに振り分ける。
    バケット外（weeks 週より古い）のポジションはスキップされる。

    Args:
        closed_positions: 決済済みポジション情報のリスト。
            各辞書に closed_at（ISO 形式の UTC 日時文字列）を含む必要がある。
        weeks: 集計する週数（デフォルト: 4 週 = 約1ヶ月）

    Returns:
        週次損益リスト（新しい週順）。各要素:
            - week_start: 週の開始日（月曜、ISO 日付文字列）
            - realized_usd: その週の合計実現損益（USD）
            - trades: その週のトレード数
            - wins: その週の利益トレード数
    """
    now = datetime.now(timezone.utc)
    buckets: dict[str, dict] = {}

    # 直近 weeks 週分のバケットを月曜日基準で生成
    for i in range(weeks):
        # now.weekday() で今週の月曜日を求め、7*i 日前の週に遡る
        start = (now - timedelta(days=now.weekday() + 7 * i)).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        key = start.date().isoformat()
        buckets[key] = {"week_start": key, "realized_usd": 0.0, "trades": 0, "wins": 0}

    for pos in closed_positions:
        # 決済日時がないポジションはスキップ
        closed_at = pos.get("closed_at")
        if not closed_at:
            continue

        # ISO 形式の日時文字列をパース（"Z" を "+00:00" に変換して対応）
        try:
            dt = datetime.fromisoformat(closed_at.replace("Z", "+00:00"))
        except ValueError:
            continue
        # タイムゾーン情報がない場合は UTC として扱う
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)

        # 損益の取得（事前計算済みがなければオンデマンド計算）
        pnl = pos.get("realized_pnl_usd")
        if pnl is None:
            pnl = calc_realized_pnl_usd(
                pos["symbol"],
                pos["side"],
                int(pos["units"]),
                float(pos["entry_price"]),
                float(pos["close_price"]),
            )

        # 決済日時から「その週の月曜日」を求めてバケットキーを生成
        week_start = (dt - timedelta(days=dt.weekday())).date().isoformat()
        # 集計対象週の範囲外（古い週）はスキップ
        if week_start not in buckets:
            continue

        # バケットに損益・トレード数・勝ち数を加算
        buckets[week_start]["realized_usd"] = round(
            buckets[week_start]["realized_usd"] + pnl, 2
        )
        buckets[week_start]["trades"] += 1
        if pnl > 0:
            buckets[week_start]["wins"] += 1

    # 週の開始日の降順（新しい週が先頭）でソートして返す
    return sorted(buckets.values(), key=lambda x: x["week_start"], reverse=True)
