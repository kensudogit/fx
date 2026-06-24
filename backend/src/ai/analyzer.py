"""OpenAI による経済指標分析・売買判断・リスク管理"""

import logging
from typing import Any

import pandas as pd

from src.ai.client import chat_json
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
    """ATR ベースのボラティリティ指標"""
    high = df["high"]
    low = df["low"]
    close = df["close"]
    tr = pd.concat(
        [high - low, (high - close.shift()).abs(), (low - close.shift()).abs()],
        axis=1,
    ).max(axis=1)
    atr = tr.rolling(period).mean().iloc[-1]
    daily_returns = close.pct_change().dropna()
    return {
        "atr": round(float(atr), 4),
        "atr_percent": round(float(atr / close.iloc[-1] * 100), 3),
        "daily_volatility": round(float(daily_returns.std() * 100), 3),
        "max_drawdown_30d": round(
            float((close / close.rolling(30).max() - 1).iloc[-1] * 100), 2
        )
        if len(close) >= 30
        else None,
    }


def _build_technical_context(symbol: str, days: int = 200) -> dict:
    df, source = get_ohlcv_data(symbol, days)
    result = compute_all_indicators(df)
    latest = result.iloc[-1]

    buy_signals = 0
    sell_signals = 0
    if latest["rsi"] < 30:
        buy_signals += 1
    elif latest["rsi"] > 70:
        sell_signals += 1
    if latest["macd"] > latest["macd_signal"]:
        buy_signals += 1
    elif latest["macd"] < latest["macd_signal"]:
        sell_signals += 1

    return {
        "source": source,
        "price": round(float(latest["close"]), 4),
        "rsi": round(float(latest["rsi"]), 2) if pd.notna(latest["rsi"]) else None,
        "macd": round(float(latest["macd"]), 4) if pd.notna(latest["macd"]) else None,
        "macd_signal": round(float(latest["macd_signal"]), 4) if pd.notna(latest["macd_signal"]) else None,
        "sma_20": round(float(latest["sma_20"]), 4) if pd.notna(latest["sma_20"]) else None,
        "sma_50": round(float(latest["sma_50"]), 4) if pd.notna(latest["sma_50"]) else None,
        "bb_upper": round(float(latest["bb_upper"]), 4) if pd.notna(latest["bb_upper"]) else None,
        "bb_lower": round(float(latest["bb_lower"]), 4) if pd.notna(latest["bb_lower"]) else None,
        "stoch_k": round(float(latest["stoch_k"]), 2) if pd.notna(latest["stoch_k"]) else None,
        "buy_signals": buy_signals,
        "sell_signals": sell_signals,
        "volatility": _calc_volatility(result),
    }


async def analyze_fundamentals(symbol: str) -> dict:
    """経済指標の AI 分析"""
    base, quote = CURRENCY_MAP.get(symbol.upper(), (symbol[:3], symbol[3:]))
    fund_data = await get_fundamental_data()
    calendar = get_upcoming_events()

    relevant_events = {}
    for key, data in fund_data["events"].items():
        label = EVENT_LABELS.get(EventType(key), key)
        relevant_events[label] = data["data"][:3]

    result = chat_json(
        system="""あなたはマクロ経済アナリストです。経済指標データを分析し、JSONのみで回答してください。
出力形式:
{
  "overview": "総合評価（3-5文、日本語）",
  "base_currency_analysis": "基軸通貨の経済状況分析",
  "quote_currency_analysis": "決済通貨の経済状況分析",
  "key_indicators": [
    {"name": "指標名", "impact": "positive|negative|neutral", "comment": "解説"}
  ],
  "upcoming_risks": ["リスク1", "リスク2"],
  "pair_bias": "bullish|bearish|neutral（通貨ペア全体のバイアス）",
  "confidence": 0-100
}""",
        user=f"""通貨ペア: {symbol} ({base}/{quote})

経済指標データ:
{relevant_events}

今後のイベント:
{calendar[:5]}""",
    )

    return {"symbol": symbol, "base": base, "quote": quote, **result}


async def make_trading_decision(symbol: str, days: int = 200) -> dict:
    """テクニカル + ファンダメンタル + ニュースを統合した売買判断"""
    technical = _build_technical_context(symbol, days)
    news = await analyze_news(symbol, limit=6)
    fund = await analyze_fundamentals(symbol)

    result = chat_json(
        system="""あなたはプロのFXトレーダーです。テクニカル・ファンダメンタル・ニュースを統合し、売買判断をJSONで出力してください。
出力形式:
{
  "action": "buy|sell|hold",
  "confidence": 0-100,
  "entry_price": 推奨エントリー価格（数値）,
  "take_profit": 利確目標（数値）,
  "stop_loss": 損切りライン（数値）,
  "timeframe": "短期|中期|長期",
  "reasoning": "判断理由（5-8文、日本語）",
  "technical_view": "テクニカル面の見解（2-3文）",
  "fundamental_view": "ファンダメンタル面の見解（2-3文）",
  "news_view": "ニュース面の見解（2-3文）",
  "risk_reward_ratio": リスクリワード比（数値）,
  "warnings": ["注意点1", "注意点2"]
}""",
        user=f"""通貨ペア: {symbol}
現在価格: {technical['price']}

テクニカル指標:
{technical}

ニュース分析:
要約: {news.get('summary')}
センチメント: {news.get('sentiment')} (score: {news.get('sentiment_score')})
トピック: {news.get('key_topics')}

ファンダメンタル:
概要: {fund.get('overview')}
バイアス: {fund.get('pair_bias')}""",
    )

    return {
        "symbol": symbol,
        "current_price": technical["price"],
        "technical": technical,
        "news_sentiment": news.get("sentiment"),
        **result,
    }


async def assess_risk(symbol: str, days: int = 200, account_balance: float = 10000) -> dict:
    """リスク管理評価"""
    technical = _build_technical_context(symbol, days)
    price = technical["price"]
    vol = technical["volatility"]

    result = chat_json(
        system="""あなたはリスク管理の専門家です。FXトレードのリスク評価をJSONで出力してください。
出力形式:
{
  "risk_level": "low|medium|high|extreme",
  "risk_score": 0-100,
  "position_size_percent": 推奨ポジションサイズ（口座の%、1-5）,
  "max_loss_percent": 1トレードあたり最大損失（口座の%、0.5-2）,
  "recommended_leverage": 推奨レバレッジ（1-10）,
  "stop_loss_price": 損切り価格（数値）,
  "take_profit_price": 利確価格（数値）,
  "risk_reward_ratio": リスクリワード比,
  "volatility_assessment": "ボラティリティ評価（2-3文）",
  "market_conditions": "現在の市場環境（2-3文）",
  "recommendations": ["推奨事項1", "推奨事項2", "推奨事項3"],
  "do_not_trade_if": ["避けるべき条件1", "条件2"]
}""",
        user=f"""通貨ペア: {symbol}
現在価格: {price}
口座残高: ${account_balance:,.0f}
ATR: {vol['atr']} ({vol['atr_percent']}%)
日次ボラティリティ: {vol['daily_volatility']}%
30日最大ドローダウン: {vol.get('max_drawdown_30d')}%
RSI: {technical['rsi']}
テクニカル買いシグナル: {technical['buy_signals']}
テクニカル売りシグナル: {technical['sell_signals']}""",
    )

    position_pct = result.get("position_size_percent", 2)
    max_loss_pct = result.get("max_loss_percent", 1)
    result["position_size_usd"] = round(account_balance * position_pct / 100, 2)
    result["max_loss_usd"] = round(account_balance * max_loss_pct / 100, 2)

    return {
        "symbol": symbol,
        "account_balance": account_balance,
        "current_price": price,
        "volatility": vol,
        **result,
    }


async def generate_full_report(symbol: str, days: int = 200, account_balance: float = 10000) -> dict:
    """全機能を統合したレポート"""
    news = await analyze_news(symbol)
    fundamentals = await analyze_fundamentals(symbol)
    decision = await make_trading_decision(symbol, days)
    risk = await assess_risk(symbol, days, account_balance)

    return {
        "symbol": symbol,
        "news": news,
        "fundamentals": fundamentals,
        "trading_decision": decision,
        "risk_management": risk,
    }
