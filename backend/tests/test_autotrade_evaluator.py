"""自動取引 evaluator のユニットテスト"""

from unittest.mock import patch

from src.autotrade.evaluator import compute_order_size, fuse_signals
from src.analysis.position_sizing import pip_size


def test_pip_size_usdjpy():
    assert pip_size("USDJPY") == 0.01


def test_pip_size_eurusd():
    assert pip_size("EURUSD") == 0.0001


@patch("src.autotrade.evaluator.get_account_summary")
def test_compute_order_size_buy_usdjpy(mock_account):
    mock_account.return_value = {"balance": 10000}
    context = {"price": 150.0, "atr": 0.5}
    config = {
        "account_balance": 10000,
        "risk_percent": 1.0,
        "min_units": 1000,
        "use_stop_loss": True,
        "use_take_profit": True,
        "risk_reward": 2.0,
    }

    plan = compute_order_size("USDJPY", config, context, "buy")

    assert plan["units"] >= 1000
    assert plan["side"] == "buy"
    assert plan["entry_price"] == 150.0
    assert plan["stop_loss"] is not None
    assert plan["take_profit"] is not None
    assert plan["take_profit"] > plan["entry_price"]
    assert plan["stop_loss"] < plan["entry_price"]


@patch("src.autotrade.evaluator.get_account_summary")
def test_compute_order_size_sell_eurusd(mock_account):
    mock_account.return_value = {"balance": 5000}
    context = {"price": 1.085, "atr": 0.002}
    config = {
        "risk_percent": 1.0,
        "min_units": 1000,
        "use_stop_loss": True,
        "use_take_profit": True,
        "risk_reward": 2.0,
    }

    plan = compute_order_size("EURUSD", config, context, "sell")

    assert plan["side"] == "sell"
    assert plan["stop_loss"] > plan["entry_price"]
    assert plan["take_profit"] < plan["entry_price"]


def test_fuse_signals_buy_majority():
    context = {
        "ai": {"action": "buy", "confidence": 80},
        "technical": {"action": "buy", "confidence": 70},
        "intelligence": {"action": "hold", "confidence": 40},
        "mtf": {"action": "buy", "confidence": 70},
    }
    config = {"sources": ["ai", "technical", "intelligence", "mtf"]}

    fused = fuse_signals(context, config)

    assert fused["action"] == "buy"
    assert fused["confidence"] >= 30
    assert fused["breakdown"]


def test_fuse_signals_hold_when_neutral():
    context = {
        "ai": {"action": "hold", "confidence": 40},
        "technical": {"action": "hold", "confidence": 40},
        "intelligence": {"action": "hold", "confidence": 40},
        "mtf": {"action": "hold", "confidence": 45},
    }
    config = {}

    fused = fuse_signals(context, config)

    assert fused["action"] == "hold"
