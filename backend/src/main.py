from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, Response

from src.analysis.chart import generate_technical_chart
from src.analysis.fundamental import (
    EVENT_LABELS,
    EventType,
    get_fundamental_data,
    get_upcoming_events,
)
from src.analysis.technical import compute_all_indicators, series_to_list
from src.data.market_data import get_ohlcv_data, sync_symbol_data
from src.data.sample_data import SYMBOL_BASE_PRICES
from src.db.database import dynamodb_client, init_database
from src.ml.deep_learning import check_ml_frameworks
from src.config import settings
from src.ml.predictor import train_price_predictor


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_database()
    yield


app = FastAPI(
    title="FX Tool API",
    description="テクニカル分析・ファンダメンタル分析 API",
    version="1.2.0",
    lifespan=lifespan,
)

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

    signals = []

    if latest["rsi"] < 30:
        signals.append({"indicator": "RSI", "signal": "buy", "value": round(latest["rsi"], 2), "reason": "売られ過ぎ"})
    elif latest["rsi"] > 70:
        signals.append({"indicator": "RSI", "signal": "sell", "value": round(latest["rsi"], 2), "reason": "買われ過ぎ"})

    if latest["macd"] > latest["macd_signal"]:
        signals.append({"indicator": "MACD", "signal": "buy", "reason": "MACDがシグナル線を上抜け"})
    elif latest["macd"] < latest["macd_signal"]:
        signals.append({"indicator": "MACD", "signal": "sell", "reason": "MACDがシグナル線を下抜け"})

    if latest["close"] < latest["bb_lower"]:
        signals.append({"indicator": "Bollinger Bands", "signal": "buy", "reason": "下限バンドタッチ"})
    elif latest["close"] > latest["bb_upper"]:
        signals.append({"indicator": "Bollinger Bands", "signal": "sell", "reason": "上限バンドタッチ"})

    if latest["stoch_k"] < 20 and latest["stoch_d"] < 20:
        signals.append({"indicator": "Stochastic", "signal": "buy", "reason": "売られ過ぎ圏"})
    elif latest["stoch_k"] > 80 and latest["stoch_d"] > 80:
        signals.append({"indicator": "Stochastic", "signal": "sell", "reason": "買われ過ぎ圏"})

    return {"symbol": symbol, "source": source, "signals": signals, "price": round(float(latest["close"]), 4)}


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


@app.get("/api/ml/predict/{symbol}")
async def predict_price(symbol: str, days: int = Query(default=200, ge=50, le=500)):
    symbol = _validate_symbol(symbol)
    df, source = get_ohlcv_data(symbol, days)
    result_df = compute_all_indicators(df)
    prediction = train_price_predictor(result_df)

    return {"symbol": symbol, "source": source, **prediction}
