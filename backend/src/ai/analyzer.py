"""OpenAI による経済指標分析・売買判断・リスク管理"""

import asyncio
import logging

import pandas as pd

from src.ai.client import _safe_number, chat_json
from src.ai.news import analyze_news
from src.analysis.fundamental import EVENT_LABELS, EventType, get_fundamental_data, get_upcoming_events
from src.analysis.technical import compute_all_indicators
from src.data.market_data import get_ohlcv_data

logger = logging.getLogger(__name__)

CURRENCY_MAP = {
    "USDJPY": ("USD", "JPY"),
    "EURUSD": ("EUR", "USD"),
    "GBPUSD": ("GBP", "USD"),
    "AUDUSD": ("AUD", "USD"),
}


def _calc_volatility(df: pd.DataFrame, period: int = 14) -> dict:
    high = df["high"]
    low = df["low"]
    close = df["close"]
    tr = pd.concat(
        [high - low, (high - close.shift()).abs(), (low - close.shift()).abs()],
        axis=1,
    ).max(axis=1)
    atr = tr.rolling(period).mean().iloc[-1]
    daily_returns = close.pct_change().dropna()
    atr_val = float(atr) if pd.notna(atr) else 0.0
    close_val = float(close.iloc[-1])
    return {
        "atr": round(atr_val, 4),
        "atr_percent": round(atr_val / close_val * 100, 3) if close_val else 0,
        "daily_volatility": round(float(daily_returns.std() * 100), 3) if len(daily_returns) else 0,
        "max_drawdown_30d": round(
            float((close / close.rolling(30).max() - 1).iloc[-1] * 100), 2
        )
        if len(close) >= 30
        else None,
    }


def _safe_round(val, digits=4):
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return None
    return round(float(val), digits)


def _build_technical_context(symbol: str, days: int = 200) -> dict:
    df, source = get_ohlcv_data(symbol, days)
    result = compute_all_indicators(df)
    latest = result.iloc[-1]

    buy_signals = 0
    sell_signals = 0
    rsi = latest["rsi"]
    if pd.notna(rsi):
        if rsi < 30:
            buy_signals += 1
        elif rsi > 70:
            sell_signals += 1
    if pd.notna(latest["macd"]) and pd.notna(latest["macd_signal"]):
        if latest["macd"] > latest["macd_signal"]:
            buy_signals += 1
        elif latest["macd"] < latest["macd_signal"]:
            sell_signals += 1

    return {
        "source": source,
        "price": _safe_round(latest["close"], 4),
        "rsi": _safe_round(rsi, 2),
        "macd": _safe_round(latest["macd"], 4),
        "macd_signal": _safe_round(latest["macd_signal"], 4),
        "sma_20": _safe_round(latest["sma_20"], 4),
        "sma_50": _safe_round(latest["sma_50"], 4),
        "bb_upper": _safe_round(latest["bb_upper"], 4),
        "bb_lower": _safe_round(latest["bb_lower"], 4),
        "stoch_k": _safe_round(latest["stoch_k"], 2),
        "buy_signals": buy_signals,
        "sell_signals": sell_signals,
        "volatility": _calc_volatility(result),
    }


async def analyze_fundamentals(symbol: str) -> dict:
    base, quote = CURRENCY_MAP.get(symbol.upper(), (symbol[:3], symbol[3:]))
    fund_data = await get_fundamental_data()
    calendar = get_upcoming_events()

    relevant_events = {}
    for key, data in fund_data.items():
        try:
            label = EVENT_LABELS[EventType(key)]
        except ValueError:
            label = data.get("label", key)
        relevant_events[label] = data.get("data", [])[:3]

    result = await asyncio.to_thread(
        chat_json,
        """あなたはマクロ経済アナリストです。経済指標データを分析し、JSONのみで回答してください。
出力形式:
{
  "overview": "総合評価（3-5文、日本語）",
  "base_currency_analysis": "基軸通貨の経済状況分析",
  "quote_currency_analysis": "決済通貨の経済状況分析",
  "key_indicators": [
    {"name": "指標名", "impact": "positive|negative|neutral", "comment": "解説"}
  ],
  "upcoming_risks": ["リスク1", "リスク2"],
  "pair_bias": "bullish|bearish|neutral",
  "confidence": 0
}""",
        f"""通貨ペア: {symbol} ({base}/{quote})

経済指標データ:
{relevant_events}

今後のイベント:
{calendar[:5]}""",
    )

    return {"symbol": symbol, "base": base, "quote": quote, **result}


def _trading_decision_from_context(
    symbol: str, technical: dict, news: dict, fund: dict
) -> dict:
    result = chat_json(
        system="""あなたはプロのFXトレーダーです。売買判断をJSONで出力してください。
{
  "action": "buy|sell|hold",
  "confidence": 0,
  "entry_price": 0,
  "take_profit": 0,
  "stop_loss": 0,
  "timeframe": "短期|中期|長期",
  "reasoning": "判断理由（日本語）",
  "technical_view": "テクニカル見解",
  "fundamental_view": "ファンダメンタル見解",
  "news_view": "ニュース見解",
  "risk_reward_ratio": 0,
  "warnings": ["注意点"]
}""",
        user=f"""通貨ペア: {symbol}
現在価格: {technical['price']}
テクニカル: {technical}
ニュース: 要約={news.get('summary')}, sentiment={news.get('sentiment')}
ファンダメンタル: {fund.get('overview')}, bias={fund.get('pair_bias')}""",
    )
    return {
        "symbol": symbol,
        "current_price": technical["price"],
        "technical": technical,
        "news_sentiment": news.get("sentiment"),
        **result,
    }


def _risk_from_context(symbol: str, technical: dict, account_balance: float) -> dict:
    price = technical["price"]
    vol = technical["volatility"]

    result = chat_json(
        system="""リスク管理評価をJSONで出力してください。
{
  "risk_level": "low|medium|high|extreme",
  "risk_score": 0,
  "position_size_percent": 2,
  "max_loss_percent": 1,
  "recommended_leverage": 3,
  "stop_loss_price": 0,
  "take_profit_price": 0,
  "risk_reward_ratio": 0,
  "volatility_assessment": "評価文",
  "market_conditions": "市場環境",
  "recommendations": ["推奨1"],
  "do_not_trade_if": ["条件1"]
}""",
        user=f"""通貨ペア: {symbol}
現在価格: {price}
口座残高: ${account_balance:,.0f}
ATR: {vol['atr']} ({vol['atr_percent']}%)
RSI: {technical['rsi']}""",
    )

    position_pct = _safe_number(result.get("position_size_percent"), 2)
    max_loss_pct = _safe_number(result.get("max_loss_percent"), 1)
    result["position_size_usd"] = round(account_balance * position_pct / 100, 2)
    result["max_loss_usd"] = round(account_balance * max_loss_pct / 100, 2)

    return {
        "symbol": symbol,
        "account_balance": account_balance,
        "current_price": price,
        "volatility": vol,
        **result,
    }


async def make_trading_decision(symbol: str, days: int = 200) -> dict:
    technical = _build_technical_context(symbol, days)
    news = await analyze_news(symbol, limit=6)
    fund = await analyze_fundamentals(symbol)
    return await asyncio.to_thread(_trading_decision_from_context, symbol, technical, news, fund)


async def assess_risk(symbol: str, days: int = 200, account_balance: float = 10000) -> dict:
    technical = _build_technical_context(symbol, days)
    return await asyncio.to_thread(_risk_from_context, symbol, technical, account_balance)


async def generate_full_report(symbol: str, days: int = 200, account_balance: float = 10000) -> dict:
    """重複API呼び出しを避けた総合レポート"""
    technical = _build_technical_context(symbol, days)

    news, fund = await asyncio.gather(
        analyze_news(symbol, limit=6),
        analyze_fundamentals(symbol),
    )

    decision, risk = await asyncio.gather(
        asyncio.to_thread(_trading_decision_from_context, symbol, technical, news, fund),
        asyncio.to_thread(_risk_from_context, symbol, technical, account_balance),
    )

    return {
        "symbol": symbol,
        "news": news,
        "fundamentals": fund,
        "trading_decision": decision,
        "risk_management": risk,
    }
