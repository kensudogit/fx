"""実現損益（PnL）計算"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from src.analysis.position_sizing import pip_size, pip_value_per_lot_usd


def calc_realized_pnl_usd(
    symbol: str,
    side: str,
    units: int,
    entry_price: float,
    close_price: float,
) -> float:
    """決済済みポジションの実現損益（USD）"""
    sym = symbol.upper()
    pip = pip_size(sym)
    if not pip or entry_price <= 0 or close_price <= 0:
        return 0.0
    if side == "buy":
        pips = (close_price - entry_price) / pip
    else:
        pips = (entry_price - close_price) / pip
    lots = units / 100_000
    pip_val = pip_value_per_lot_usd(sym, close_price)
    return round(pips * pip_val * lots, 2)


def aggregate_pnl(closed_positions: list[dict]) -> dict:
    """決済ポジション一覧から PnL 集計"""
    total = 0.0
    wins = 0
    losses = 0
    for pos in closed_positions:
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
        if pnl > 0:
            wins += 1
        elif pnl < 0:
            losses += 1

    closed_count = len(closed_positions)
    win_rate = round(wins / closed_count * 100, 1) if closed_count else 0.0
    return {
        "total_realized_usd": round(total, 2),
        "closed_trades": closed_count,
        "wins": wins,
        "losses": losses,
        "win_rate_pct": win_rate,
    }


def weekly_pnl_breakdown(closed_positions: list[dict], weeks: int = 4) -> list[dict]:
    """週次の実現損益内訳（月曜始まり）"""
    now = datetime.now(timezone.utc)
    buckets: dict[str, dict] = {}

    for i in range(weeks):
        start = (now - timedelta(days=now.weekday() + 7 * i)).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        key = start.date().isoformat()
        buckets[key] = {"week_start": key, "realized_usd": 0.0, "trades": 0, "wins": 0}

    for pos in closed_positions:
        closed_at = pos.get("closed_at")
        if not closed_at:
            continue
        try:
            dt = datetime.fromisoformat(closed_at.replace("Z", "+00:00"))
        except ValueError:
            continue
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)

        pnl = pos.get("realized_pnl_usd")
        if pnl is None:
            pnl = calc_realized_pnl_usd(
                pos["symbol"],
                pos["side"],
                int(pos["units"]),
                float(pos["entry_price"]),
                float(pos["close_price"]),
            )

        week_start = (dt - timedelta(days=dt.weekday())).date().isoformat()
        if week_start not in buckets:
            continue
        buckets[week_start]["realized_usd"] = round(
            buckets[week_start]["realized_usd"] + pnl, 2
        )
        buckets[week_start]["trades"] += 1
        if pnl > 0:
            buckets[week_start]["wins"] += 1

    return sorted(buckets.values(), key=lambda x: x["week_start"], reverse=True)
