"""統合ダッシュボード API"""

from src.ai.client import resolve_openai_api_key
from src.ai.news import fetch_rss_news
from src.analysis.multi_timeframe import analyze_multi_timeframe
from src.analysis.signals import backtest_signals, signals_from_row
from src.analysis.technical import compute_all_indicators
from src.backtest.backtrader_runner import run_backtrader_backtest
from src.auth.context import get_tenant_id
from src.broker.oanda import get_account_summary, is_oanda_configured, list_orders
from src.data.market_data import get_ohlcv_data
from src.ml.news_sentiment import analyze_headlines_ml
from src.tradingview.service import list_signals


async def build_dashboard(symbol: str, days: int = 200) -> dict:
    df, source = get_ohlcv_data(symbol, days)
    result_df = compute_all_indicators(df)
    latest = result_df.iloc[-1]
    signals = signals_from_row(latest)
    articles = await fetch_rss_news(symbol, 8)
    headlines = [a["title"] for a in articles]
    ml_news = analyze_headlines_ml(headlines)

    mtf = analyze_multi_timeframe(symbol)
    simple_bt = backtest_signals(result_df)
    bt = run_backtrader_backtest(symbol, days)

    return {
        "symbol": symbol.upper(),
        "price": round(float(latest["close"]), 4),
        "source": source,
        "signals": signals,
        "multi_timeframe": mtf,
        "news_ml": {**ml_news, "article_count": len(articles)},
        "openai_configured": bool(resolve_openai_api_key()),
        "backtest_simple": simple_bt,
        "backtest_backtrader": bt,
        "tradingview_signals": list_signals(symbol, 5, get_tenant_id()),
        "oanda": get_account_summary(),
        "recent_orders": list_orders(5, get_tenant_id()),
        "stack": {
            "api": "FastAPI (Python)",
            "frontend": "Next.js / React",
            "note": "Spring Boot 相当の API 層は FastAPI で実装",
        },
    }
