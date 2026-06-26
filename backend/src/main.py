from contextlib import asynccontextmanager
import logging

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, Response

from src.analysis.chart import generate_technical_chart
from src.analysis.fundamental import (
    EVENT_LABELS,
    EventType,
    get_event_alerts,
    get_fundamental_data,
    get_upcoming_events,
)
from src.analysis.multi_timeframe import analyze_multi_timeframe
from src.analysis.position_sizing import calculate_position_size
from src.analysis.signals import backtest_signals, signals_from_row
from src.analysis.volatility import calc_atr
from src.analysis.technical import compute_all_indicators, series_to_list
from src.data.market_data import get_ohlcv_data, sync_symbol_data
from src.data.sample_data import SYMBOL_BASE_PRICES
from src.db.database import dynamodb_client, init_database
from src.ml.deep_learning import check_ml_frameworks
from src.ai.analyzer import (
    analyze_fundamentals,
    assess_risk,
    generate_full_report,
    make_trading_decision,
)
from src.ai.client import resolve_openai_api_key
from src.ai.news import analyze_news, fetch_rss_news
from src.api.ai_pro import router as ai_pro_router
from src.api.autotrade import router as autotrade_router
from src.api.broker import router as broker_router
from src.api.dashboard import build_dashboard
from src.api.prices import router as prices_router
from src.autotrade.scheduler import start_scheduler
from src.analysis.market_deep import build_market_analysis
from src.analysis.risk_advanced import build_risk_report
from src.api.intelligence import build_intelligence
from src.analysis.economic import analyze_economic
from src.analysis.sns import analyze_sns
from src.backtest.backtrader_runner import run_backtrader_backtest
from src.broker.oanda import get_account_summary, list_orders, place_market_order
from src.config import settings
from src.ml.news_sentiment import analyze_headlines_ml
from src.ml.predictor import train_price_predictor
from src.ml.trend_predictor import predict_trend
from src.ml.volatility_predictor import predict_volatility
from src.auth.middleware import SaaSAuthMiddleware
from src.auth.router import router as auth_router
from src.auth.service import bootstrap_auth
from src.auth.context import get_tenant_id
from src.tradingview.service import list_signals, save_signal

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_database()
    bootstrap_auth()
    if settings.autotrade_enabled:
        start_scheduler()
    yield


app = FastAPI(
    title="FX Tool API",
    description="テクニカル分析・ファンダメンタル分析 API（SaaS対応）",
    version="2.1.0",
    lifespan=lifespan,
)

app.add_middleware(SaaSAuthMiddleware)
app.include_router(auth_router)
app.include_router(ai_pro_router)
app.include_router(autotrade_router)
app.include_router(broker_router)
app.include_router(prices_router)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.get_cors_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _validate_symbol(symbol: str) -> str:
    symbol = symbol.upper()
    if symbol not in SYMBOL_BASE_PRICES:
        raise HTTPException(status_code=404, detail=f"Symbol {symbol} not found")
    return symbol


def _build_technical_response(symbol: str, result_df, source: str) -> dict:
    timestamps = [t.isoformat() for t in result_df["timestamp"]]
    return {
        "symbol": symbol,
        "source": source,
        "timestamps": timestamps,
        "ohlcv": {
            "open": series_to_list(result_df["open"]),
            "high": series_to_list(result_df["high"]),
            "low": series_to_list(result_df["low"]),
            "close": series_to_list(result_df["close"]),
        },
        "indicators": {
            "ma": {
                "sma_20": series_to_list(result_df["sma_20"]),
                "sma_50": series_to_list(result_df["sma_50"]),
                "ema_12": series_to_list(result_df["ema_12"]),
                "ema_26": series_to_list(result_df["ema_26"]),
            },
            "bollinger_bands": {
                "upper": series_to_list(result_df["bb_upper"]),
                "middle": series_to_list(result_df["bb_middle"]),
                "lower": series_to_list(result_df["bb_lower"]),
            },
            "macd": {
                "macd": series_to_list(result_df["macd"]),
                "signal": series_to_list(result_df["macd_signal"]),
                "histogram": series_to_list(result_df["macd_histogram"]),
            },
            "rsi": series_to_list(result_df["rsi"]),
            "stochastic": {
                "k": series_to_list(result_df["stoch_k"]),
                "d": series_to_list(result_df["stoch_d"]),
            },
            "ichimoku": {
                "tenkan": series_to_list(result_df["ichi_tenkan"]),
                "kijun": series_to_list(result_df["ichi_kijun"]),
                "senkou_a": series_to_list(result_df["ichi_senkou_a"]),
                "senkou_b": series_to_list(result_df["ichi_senkou_b"]),
                "chikou": series_to_list(result_df["ichi_chikou"]),
            },
        },
        "latest": {
            "close": float(result_df["close"].iloc[-1]),
            "rsi": float(result_df["rsi"].dropna().iloc[-1]) if result_df["rsi"].notna().any() else None,
            "macd": float(result_df["macd"].dropna().iloc[-1]) if result_df["macd"].notna().any() else None,
        },
    }


@app.get("/health")
async def health():
    frameworks = check_ml_frameworks()
    return {"status": "ok", "ml_frameworks": frameworks}


@app.get("/", response_class=HTMLResponse)
async def root():
    return """<!DOCTYPE html>
<html lang="ja"><head><meta charset="utf-8">
<meta http-equiv="refresh" content="0;url=/docs">
<title>FX Tool API</title></head>
<body><p>FX Tool API — <a href="/docs">API Docs</a></p></body></html>"""


@app.get("/api/symbols")
async def list_symbols():
    return {"symbols": list(SYMBOL_BASE_PRICES.keys())}


@app.post("/api/data/sync/{symbol}")
async def sync_data(symbol: str, days: int = Query(default=200, ge=30, le=500)):
    symbol = _validate_symbol(symbol)
    try:
        result = sync_symbol_data(symbol, days)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/ohlcv/{symbol}")
async def get_ohlcv(symbol: str, days: int = Query(default=200, ge=30, le=500)):
    symbol = _validate_symbol(symbol)
    df, source = get_ohlcv_data(symbol, days)

    return {
        "symbol": symbol,
        "source": source,
        "data": [
            {
                "timestamp": row["timestamp"].isoformat(),
                "open": row["open"],
                "high": row["high"],
                "low": row["low"],
                "close": row["close"],
                "volume": row["volume"],
            }
            for _, row in df.iterrows()
        ],
    }


@app.get("/api/technical/{symbol}")
async def get_technical_analysis(
    symbol: str,
    days: int = Query(default=200, ge=30, le=500),
    indicator: str | None = Query(default=None),
):
    symbol = _validate_symbol(symbol)

    cache_key = f"technical:{symbol}:{days}:{indicator or 'all'}"
    cached = dynamodb_client.get(cache_key)
    if cached:
        return cached

    df, source = get_ohlcv_data(symbol, days)
    result_df = compute_all_indicators(df)
    response = _build_technical_response(symbol, result_df, source)

    if indicator:
        valid = ["ma", "bollinger_bands", "macd", "rsi", "stochastic", "ichimoku"]
        if indicator not in valid:
            raise HTTPException(status_code=400, detail=f"Invalid indicator. Choose from: {valid}")
        response = {
            "symbol": symbol,
            "source": source,
            "indicator": indicator,
            "timestamps": response["timestamps"],
            "data": response["indicators"][indicator],
        }

    dynamodb_client.put(cache_key, response)
    return response


@app.get("/api/technical/{symbol}/signals")
async def get_trading_signals(symbol: str, days: int = Query(default=200, ge=30, le=500)):
    symbol = _validate_symbol(symbol)
    df, source = get_ohlcv_data(symbol, days)
    result_df = compute_all_indicators(df)
    latest = result_df.iloc[-1]
    signals = signals_from_row(latest)

    return {"symbol": symbol, "source": source, "signals": signals, "price": round(float(latest["close"]), 4)}


@app.get("/api/technical/{symbol}/multi-timeframe")
async def get_multi_timeframe(symbol: str):
    symbol = _validate_symbol(symbol)
    try:
        return analyze_multi_timeframe(symbol)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/technical/{symbol}/backtest")
async def get_signal_backtest(symbol: str, days: int = Query(default=200, ge=90, le=500)):
    symbol = _validate_symbol(symbol)
    df, source = get_ohlcv_data(symbol, days)
    result_df = compute_all_indicators(df)
    stats = backtest_signals(result_df)
    return {"symbol": symbol, "source": source, **stats}


@app.get("/api/position-size/{symbol}")
async def get_position_size(
    symbol: str,
    days: int = Query(default=200, ge=30, le=500),
    account_balance: float = Query(default=10000, ge=100),
    risk_percent: float = Query(default=1.0, ge=0.1, le=10),
    stop_pips: float | None = Query(default=None, ge=1),
    use_atr_stop: bool = Query(default=True),
):
    symbol = _validate_symbol(symbol)
    df, _ = get_ohlcv_data(symbol, days)
    price = float(df["close"].iloc[-1])
    atr = calc_atr(compute_all_indicators(df)) if use_atr_stop else None
    return calculate_position_size(
        symbol, price, account_balance, risk_percent,
        stop_pips=stop_pips, atr=atr,
    )


@app.get("/api/chart/{symbol}")
async def get_chart(symbol: str, days: int = Query(default=200, ge=30, le=500)):
    symbol = _validate_symbol(symbol)
    df, _ = get_ohlcv_data(symbol, days)
    png_bytes = generate_technical_chart(df, symbol, indicator="all")
    return Response(content=png_bytes, media_type="image/png")


@app.get("/api/fundamental")
async def get_fundamental(event_type: str | None = None):
    et = None
    if event_type:
        try:
            et = EventType(event_type)
        except ValueError:
            valid = [e.value for e in EventType]
            raise HTTPException(status_code=400, detail=f"Invalid event_type. Choose from: {valid}")

    data = await get_fundamental_data(et)
    return {"events": data, "labels": {e.value: EVENT_LABELS[e] for e in EventType}}


@app.get("/api/fundamental/calendar")
async def get_calendar():
    return {"events": get_upcoming_events()}


@app.get("/api/fundamental/alerts")
async def get_alerts(hours: int = Query(default=48, ge=1, le=168)):
    return {"alerts": get_event_alerts(hours), "within_hours": hours}


def _require_openai():
    if not resolve_openai_api_key():
        raise HTTPException(
            status_code=503,
            detail="OPENAI_API_KEY が未設定です。Railway の Variables に OPENAI_API_KEY を登録してください。",
        )


@app.get("/api/ai/status")
async def ai_status():
    key = resolve_openai_api_key()
    return {
        "configured": bool(key),
        "model": settings.openai_model,
        "key_preview": f"{key[:8]}..." if len(key) > 8 else None,
    }


@app.get("/api/ml/predict/{symbol}")
async def predict_price(symbol: str, days: int = Query(default=200, ge=50, le=500)):
    symbol = _validate_symbol(symbol)
    df, source = get_ohlcv_data(symbol, days)
    result_df = compute_all_indicators(df)
    prediction = train_price_predictor(result_df)

    return {"symbol": symbol, "source": source, **prediction}


@app.get("/api/ai/news/{symbol}")
async def ai_news(symbol: str, limit: int = Query(default=8, ge=3, le=15)):
    _require_openai()
    symbol = _validate_symbol(symbol)
    try:
        return await analyze_news(symbol, limit)
    except ValueError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"ニュース分析エラー: {e}")


@app.get("/api/ai/fundamental-analysis/{symbol}")
async def ai_fundamental_analysis(symbol: str):
    _require_openai()
    symbol = _validate_symbol(symbol)
    try:
        return await analyze_fundamentals(symbol)
    except ValueError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"経済指標分析エラー: {e}")


@app.get("/api/ai/trading-decision/{symbol}")
async def ai_trading_decision(symbol: str, days: int = Query(default=200, ge=30, le=500)):
    _require_openai()
    symbol = _validate_symbol(symbol)
    try:
        return await make_trading_decision(symbol, days)
    except ValueError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"売買判断エラー: {e}")


@app.get("/api/ai/risk/{symbol}")
async def ai_risk(
    symbol: str,
    days: int = Query(default=200, ge=30, le=500),
    account_balance: float = Query(default=10000, ge=100),
):
    _require_openai()
    symbol = _validate_symbol(symbol)
    try:
        return await assess_risk(symbol, days, account_balance)
    except ValueError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"リスク管理エラー: {e}")


@app.get("/api/ai/report/{symbol}")
async def ai_full_report(
    symbol: str,
    days: int = Query(default=200, ge=30, le=500),
    account_balance: float = Query(default=10000, ge=100),
):
    _require_openai()
    symbol = _validate_symbol(symbol)
    try:
        return await generate_full_report(symbol, days, account_balance)
    except ValueError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"レポート生成エラー: {e}")


# ── TradingView Webhook ──
@app.post("/api/tradingview/webhook")
async def tradingview_webhook(request: Request):
    """TradingView アラート → Webhook URL（SaaS: X-API-Key でテナント特定）"""
    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    tenant_id = get_tenant_id()
    if settings.saas_enabled:
        if not tenant_id:
            from src.auth.service import resolve_api_key
            from src.db.database import SessionLocal

            api_key = request.headers.get("X-API-Key", "").strip()
            if api_key:
                db = SessionLocal()
                try:
                    ctx = resolve_api_key(db, api_key)
                    tenant_id = ctx.tenant_id if ctx else None
                finally:
                    db.close()
        if not tenant_id:
            raise HTTPException(
                status_code=401,
                detail="TradingView Webhook には X-API-Key ヘッダーが必要です",
            )
    else:
        secret = settings.tradingview_webhook_secret
        if secret:
            header = request.headers.get("X-Webhook-Secret", "")
            if header != secret and payload.get("secret") != secret:
                raise HTTPException(status_code=401, detail="Invalid webhook secret")

    signal = save_signal(payload, tenant_id)

    autotrade_result = None
    autotrade_error = None
    try:
        from src.autotrade.engine import process_tradingview_signal

        autotrade_result = await process_tradingview_signal(signal, tenant_id)
    except Exception as e:
        logger.exception("TradingView autotrade failed for tenant %s: %s", tenant_id, e)
        autotrade_error = str(e)

    return {
        "ok": True,
        "signal": signal,
        "autotrade": autotrade_result,
        "autotrade_error": autotrade_error,
    }


@app.get("/api/tradingview/signals")
async def tradingview_signals(symbol: str | None = None, limit: int = Query(default=20, le=100)):
    return {"signals": list_signals(symbol, limit, get_tenant_id())}


# ── ニュース分析（ML + OpenAI）──
@app.get("/api/news/analysis/{symbol}")
async def news_analysis(symbol: str, limit: int = Query(default=8, ge=3, le=15)):
    symbol = _validate_symbol(symbol)
    articles = await fetch_rss_news(symbol, limit)
    headlines = [a["title"] for a in articles]
    result = {
        "symbol": symbol,
        "articles": articles,
        "ml": analyze_headlines_ml(headlines),
        "openai": None,
    }
    if resolve_openai_api_key():
        try:
            ai = await analyze_news(symbol, limit)
            result["openai"] = {
                "summary": ai.get("summary"),
                "sentiment": ai.get("sentiment"),
                "sentiment_score": ai.get("sentiment_score"),
                "key_topics": ai.get("key_topics"),
                "market_impact": ai.get("market_impact"),
            }
        except Exception as e:
            result["openai_error"] = str(e)
    return result


# ── Backtrader バックテスト ──
@app.get("/api/backtest/backtrader/{symbol}")
async def backtrader_backtest(
    symbol: str,
    days: int = Query(default=200, ge=90, le=500),
    cash: float = Query(default=10000, ge=1000),
):
    symbol = _validate_symbol(symbol)
    return run_backtrader_backtest(symbol, days, cash)


# ── OANDA 注文 ──
@app.get("/api/oanda/status")
async def oanda_status():
    return get_account_summary(get_tenant_id())


@app.get("/api/oanda/orders")
async def oanda_orders(limit: int = Query(default=20, le=100)):
    return {"orders": list_orders(limit, get_tenant_id())}


@app.post("/api/oanda/orders")
async def oanda_place_order(
    symbol: str = Query(...),
    side: str = Query(..., pattern="^(buy|sell)$"),
    units: int = Query(default=1000, ge=1, le=1_000_000),
):
    symbol = _validate_symbol(symbol)
    try:
        return place_market_order(symbol, side, units, get_tenant_id())
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"OANDA error: {e}")


# ── 統合ダッシュボード（React 向け BFF）──
@app.get("/api/dashboard")
async def dashboard(symbol: str = Query(default="USDJPY"), days: int = Query(default=200, ge=30, le=500)):
    symbol = _validate_symbol(symbol)
    try:
        return await build_dashboard(symbol, days)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── 5大分析（トレンド / ニュース / SNS / 経済指標 / ボラ）──
@app.get("/api/analysis/trend/{symbol}")
async def analysis_trend(symbol: str, days: int = Query(default=200, ge=60, le=500)):
    symbol = _validate_symbol(symbol)
    return predict_trend(symbol, days)


@app.get("/api/analysis/news/{symbol}")
async def analysis_news(symbol: str, limit: int = Query(default=8, ge=3, le=15)):
    symbol = _validate_symbol(symbol)
    articles = await fetch_rss_news(symbol, limit)
    headlines = [a["title"] for a in articles]
    result = {
        "symbol": symbol,
        "articles": articles,
        "ml": analyze_headlines_ml(headlines),
        "openai": None,
    }
    if resolve_openai_api_key():
        try:
            ai = await analyze_news(symbol, limit)
            result["openai"] = {
                "summary": ai.get("summary"),
                "sentiment": ai.get("sentiment"),
                "sentiment_score": ai.get("sentiment_score"),
                "key_topics": ai.get("key_topics"),
                "market_impact": ai.get("market_impact"),
            }
        except Exception as e:
            result["openai_error"] = str(e)
    return result


@app.get("/api/analysis/sns/{symbol}")
async def analysis_sns(symbol: str, limit: int = Query(default=10, ge=3, le=25)):
    symbol = _validate_symbol(symbol)
    return await analyze_sns(symbol, limit)


@app.get("/api/analysis/economic/{symbol}")
async def analysis_economic(symbol: str):
    symbol = _validate_symbol(symbol)
    return await analyze_economic(symbol)


@app.get("/api/analysis/volatility/{symbol}")
async def analysis_volatility(symbol: str, days: int = Query(default=200, ge=60, le=500)):
    symbol = _validate_symbol(symbol)
    return predict_volatility(symbol, days)


@app.get("/api/analysis/intelligence/{symbol}")
async def analysis_intelligence(symbol: str, days: int = Query(default=200, ge=60, le=500)):
    symbol = _validate_symbol(symbol)
    try:
        return await build_intelligence(symbol, days)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/analysis/market/{symbol}")
async def analysis_market(symbol: str, days: int = Query(default=200, ge=60, le=500)):
    symbol = _validate_symbol(symbol)
    try:
        return build_market_analysis(symbol, days)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/analysis/risk-report/{symbol}")
async def analysis_risk_report(
    symbol: str,
    account_balance: float = Query(default=10000, ge=100),
    risk_percent: float = Query(default=1.0, ge=0.1, le=10),
    days: int = Query(default=200, ge=60, le=500),
):
    symbol = _validate_symbol(symbol)
    try:
        return build_risk_report(symbol, account_balance, risk_percent, days)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
