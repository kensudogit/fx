"""運用前シミュレーション — 過去データバックテスト + 推奨証拠金（トライオートFX 相当）"""

from src.analysis.position_sizing import calculate_position_size, pip_size
from src.analysis.signals import backtest_signals
from src.analysis.technical import compute_all_indicators
from src.analysis.volatility import calc_atr
from src.autotrade.presets import apply_preset
from src.data.market_data import get_ohlcv_data


def simulate_strategy(
    symbol: str,
    days: int = 365,
    account_balance: float = 10000,
    preset_id: str | None = "balanced",
    risk_percent: float = 1.0,
) -> dict:
    """プリセットまたはカスタム設定での過去シミュレーション"""
    config = apply_preset(preset_id) if preset_id else {}
    config["account_balance"] = account_balance
    config["risk_percent"] = risk_percent

    df, source = get_ohlcv_data(symbol, days)
    result_df = compute_all_indicators(df)
    bt = backtest_signals(result_df)

    price = float(result_df["close"].iloc[-1])
    atr = calc_atr(result_df)
    sizing = calculate_position_size(symbol, price, account_balance, risk_percent, atr=atr)

    max_loss_streak = _estimate_max_loss_streak(bt.get("win_rate", 50))
    recommended_margin = round(account_balance * (1 + max_loss_streak * risk_percent / 100 * 0.5), 0)
    safe_margin = round(recommended_margin * 1.5, 0)

    win_rate = bt.get("win_rate", 0)
    grade = "A" if win_rate >= 55 else "B" if win_rate >= 48 else "C" if win_rate >= 42 else "D"

    return {
        "symbol": symbol.upper(),
        "source": source,
        "period_days": days,
        "preset_id": preset_id,
        "backtest": bt,
        "position_sizing": sizing,
        "capital": {
            "input_balance": account_balance,
            "recommended_margin_usd": recommended_margin,
            "safe_margin_usd": safe_margin,
            "note": "推奨証拠金は連敗リスクを考慮。安全運用は推奨の 1.5 倍を目安に。",
        },
        "assessment": {
            "grade": grade,
            "win_rate": win_rate,
            "total_trades": bt.get("total_trades", 0),
            "avg_return_pct": bt.get("avg_return_pct", 0),
            "ready_to_deploy": win_rate >= 45 and bt.get("total_trades", 0) >= 20,
            "summary": _assessment_summary(grade, win_rate, bt.get("total_trades", 0)),
        },
    }


def _estimate_max_loss_streak(win_rate: float) -> int:
    if win_rate >= 60:
        return 3
    if win_rate >= 50:
        return 5
    return 7


def _assessment_summary(grade: str, win_rate: float, trades: int) -> str:
    if trades < 10:
        return "データ不足 — 期間を延長するか別通貨ペアを検討してください。"
    if grade in ("A", "B"):
        return f"勝率 {win_rate}% — シミュレーション上、運用開始の条件を満たしています。"
    return f"勝率 {win_rate}% — プリセット変更または信頼度閾値の引き上げを推奨します。"
