"""ポジションサイズ・pip 計算"""

from src.analysis.volatility import calc_atr


def pip_size(symbol: str) -> float:
    """1 pip の価格幅"""
    return 0.01 if symbol.upper().endswith("JPY") else 0.0001


def pip_value_per_lot_usd(symbol: str, price: float) -> float:
    """標準ロット（100,000通貨）あたりの 1 pip の USD 価値"""
    sym = symbol.upper()
    pip = pip_size(sym)
    if sym.endswith("JPY"):
        # USDJPY: 100k USD × 0.01 JPY / rate
        return (100_000 * pip) / price if price else 0.0
    if sym.endswith("USD"):
        # EURUSD, GBPUSD, AUDUSD
        return 100_000 * pip
    return 100_000 * pip


def pips_from_atr(atr: float, symbol: str, multiplier: float = 1.5) -> float:
    pip = pip_size(symbol)
    return round(atr * multiplier / pip, 1) if pip else 0.0


def calculate_position_size(
    symbol: str,
    price: float,
    account_balance: float,
    risk_percent: float,
    stop_pips: float | None = None,
    atr: float | None = None,
    atr_multiplier: float = 1.5,
) -> dict:
    """リスク%とストップ幅から推奨ロットサイズを算出"""
    sym = symbol.upper()
    pip_val = pip_value_per_lot_usd(sym, price)

    if stop_pips is None or stop_pips <= 0:
        if atr and atr > 0:
            stop_pips = pips_from_atr(atr, sym, atr_multiplier)
        else:
            stop_pips = 30.0 if sym.endswith("JPY") else 20.0

    risk_amount = account_balance * (risk_percent / 100)
    risk_per_lot = stop_pips * pip_val
    lots = round(risk_amount / risk_per_lot, 2) if risk_per_lot > 0 else 0.0
    lots = max(0.01, min(lots, 100.0))

    return {
        "symbol": sym,
        "price": round(price, 4),
        "account_balance": account_balance,
        "risk_percent": risk_percent,
        "risk_amount_usd": round(risk_amount, 2),
        "stop_pips": stop_pips,
        "pip_size": pip_size(sym),
        "pip_value_per_lot_usd": round(pip_val, 2),
        "recommended_lots": lots,
        "position_notional_usd": round(lots * 100_000, 0),
        "max_loss_usd": round(lots * risk_per_lot, 2),
        "atr_based_stop": atr is not None and (stop_pips == pips_from_atr(atr, sym, atr_multiplier)),
        "suggested_take_profit_pips": round(stop_pips * 2, 1),
    }
