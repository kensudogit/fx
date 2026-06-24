"""市場データ取得・永続化サービス"""

import logging
from datetime import datetime, timezone

import httpx
import pandas as pd
import yfinance as yf
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from src.data.sample_data import SYMBOL_BASE_PRICES, generate_sample_ohlcv
from src.db.database import OHLCVRecord, SessionLocal

logger = logging.getLogger(__name__)

YAHOO_TICKERS = {
    "USDJPY": "USDJPY=X",
    "EURUSD": "EURUSD=X",
    "GBPUSD": "GBPUSD=X",
    "AUDUSD": "AUDUSD=X",
}

YAHOO_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
}


def fetch_from_yahoo_chart_api(symbol: str, days: int = 200, interval: str = "1d") -> pd.DataFrame:
    """Yahoo Finance Chart API から OHLCV を取得"""
    ticker = YAHOO_TICKERS.get(symbol.upper())
    if not ticker:
        raise ValueError(f"Unknown symbol: {symbol}")

    if interval == "4h":
        range_param = "60d"
        interval_param = "4h"
        tail = min(days * 6, 360)
    else:
        range_param = "2y" if days > 365 else "1y"
        interval_param = "1d"
        tail = days

    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
    params = {"interval": interval_param, "range": range_param}

    with httpx.Client(timeout=30.0, headers=YAHOO_HEADERS) as client:
        response = client.get(url, params=params)
        response.raise_for_status()
        payload = response.json()

    result = payload.get("chart", {}).get("result")
    if not result:
        raise ValueError(f"No chart data for {symbol}")

    chart = result[0]
    timestamps = chart.get("timestamp", [])
    quote = chart["indicators"]["quote"][0]

    if not timestamps:
        raise ValueError(f"Empty timestamps for {symbol}")

    df = pd.DataFrame(
        {
            "timestamp": [datetime.fromtimestamp(ts, tz=timezone.utc) for ts in timestamps],
            "open": quote.get("open", []),
            "high": quote.get("high", []),
            "low": quote.get("low", []),
            "close": quote.get("close", []),
            "volume": quote.get("volume", [0] * len(timestamps)),
        }
    )
    df = df.dropna(subset=["close"]).reset_index(drop=True)
    df["volume"] = df["volume"].fillna(0).astype(int)

    if df.empty:
        raise ValueError(f"No valid OHLCV rows for {symbol}")

    return df.tail(tail).reset_index(drop=True)


def fetch_from_yfinance(symbol: str, days: int = 200, interval: str = "1d") -> pd.DataFrame:
    """yfinance ライブラリから OHLCV を取得"""
    ticker = YAHOO_TICKERS.get(symbol.upper())
    if not ticker:
        raise ValueError(f"Unknown symbol: {symbol}")

    period = "60d" if interval == "4h" else ("2y" if days > 365 else "1y")
    raw = yf.download(ticker, period=period, interval=interval, progress=False, auto_adjust=True)

    if raw.empty:
        raise ValueError(f"No data returned for {symbol}")

    if isinstance(raw.columns, pd.MultiIndex):
        raw.columns = raw.columns.get_level_values(0)

    df = raw.reset_index()
    rename = {c: c.lower() if isinstance(c, str) else c for c in df.columns}
    df = df.rename(columns=rename)
    date_col = "date" if "date" in df.columns else df.columns[0]

    result = pd.DataFrame(
        {
            "timestamp": pd.to_datetime(df[date_col]),
            "open": df["open"].astype(float),
            "high": df["high"].astype(float),
            "low": df["low"].astype(float),
            "close": df["close"].astype(float),
            "volume": df.get("volume", 0).fillna(0).astype(int),
        }
    )
    tail = min(days * 6, 360) if interval == "4h" else days
    return result.tail(tail).reset_index(drop=True)


def fetch_from_yahoo(symbol: str, days: int = 200, interval: str = "1d") -> pd.DataFrame:
    """Yahoo Finance から OHLCV を取得（Chart API → yfinance の順で試行）"""
    errors = []
    for fetcher in (fetch_from_yahoo_chart_api, fetch_from_yfinance):
        try:
            return fetcher(symbol, days, interval)
        except Exception as e:
            errors.append(str(e))
            logger.warning("%s failed for %s: %s", fetcher.__name__, symbol, e)
    raise ValueError(f"All fetchers failed for {symbol}: {'; '.join(errors)}")


def save_ohlcv_to_db(db: Session, symbol: str, df: pd.DataFrame, timeframe: str = "1d") -> int:
    """OHLCV を PostgreSQL に upsert"""
    symbol = symbol.upper()
    rows = []
    for _, row in df.iterrows():
        rows.append(
            {
                "symbol": symbol,
                "timestamp": row["timestamp"],
                "open": float(row["open"]),
                "high": float(row["high"]),
                "low": float(row["low"]),
                "close": float(row["close"]),
                "volume": int(row["volume"]),
                "timeframe": timeframe,
            }
        )

    if not rows:
        return 0

    stmt = insert(OHLCVRecord).values(rows)
    stmt = stmt.on_conflict_do_update(
        index_elements=["symbol", "timestamp", "timeframe"],
        set_={
            "open": stmt.excluded.open,
            "high": stmt.excluded.high,
            "low": stmt.excluded.low,
            "close": stmt.excluded.close,
            "volume": stmt.excluded.volume,
        },
    )
    db.execute(stmt)
    db.commit()
    return len(rows)


def load_ohlcv_from_db(db: Session, symbol: str, days: int = 200, timeframe: str = "1d") -> pd.DataFrame | None:
    """PostgreSQL から OHLCV を読み込み"""
    records = (
        db.query(OHLCVRecord)
        .filter(OHLCVRecord.symbol == symbol.upper(), OHLCVRecord.timeframe == timeframe)
        .order_by(OHLCVRecord.timestamp.desc())
        .limit(days)
        .all()
    )
    if not records:
        return None

    data = [
        {
            "timestamp": r.timestamp,
            "open": float(r.open),
            "high": float(r.high),
            "low": float(r.low),
            "close": float(r.close),
            "volume": int(r.volume),
        }
        for r in reversed(records)
    ]
    return pd.DataFrame(data)


def get_ohlcv_data(symbol: str, days: int = 200, timeframe: str = "1d") -> tuple[pd.DataFrame, str]:
    """
    OHLCV データを取得（優先順位: DB → Yahoo Finance → サンプル）
    timeframe: 1d（日足）, 4h（4時間足）
    """
    symbol = symbol.upper()
    if symbol not in SYMBOL_BASE_PRICES:
        raise ValueError(f"Unknown symbol: {symbol}")

    if timeframe != "1d":
        try:
            df = fetch_from_yahoo(symbol, days, interval=timeframe)
            return df, "yahoo_finance"
        except Exception as e:
            logger.warning("Yahoo %s fetch failed for %s: %s", timeframe, symbol, e)
            base_price = SYMBOL_BASE_PRICES[symbol]
            return generate_sample_ohlcv(symbol, min(days, 90), base_price), "sample"

    db = SessionLocal()
    try:
        df = load_ohlcv_from_db(db, symbol, days)
        if df is not None and len(df) >= min(days, 30):
            return df, "database"
    except Exception as e:
        logger.warning("DB read failed for %s: %s", symbol, e)
    finally:
        db.close()

    try:
        df = fetch_from_yahoo(symbol, days)
        db = SessionLocal()
        try:
            save_ohlcv_to_db(db, symbol, df)
        except Exception as e:
            logger.warning("DB write failed for %s: %s", symbol, e)
        finally:
            db.close()
        return df, "yahoo_finance"
    except Exception as e:
        logger.warning("Yahoo fetch failed for %s: %s", symbol, e)

    base_price = SYMBOL_BASE_PRICES[symbol]
    return generate_sample_ohlcv(symbol, days, base_price), "sample"


def sync_symbol_data(symbol: str, days: int = 200) -> dict:
    """Yahoo Finance からデータを取得して DB に同期"""
    symbol = symbol.upper()
    df = fetch_from_yahoo(symbol, days)
    db = SessionLocal()
    try:
        count = save_ohlcv_to_db(db, symbol, df)
    finally:
        db.close()
    return {
        "symbol": symbol,
        "rows_synced": count,
        "latest_close": float(df["close"].iloc[-1]),
        "latest_date": df["timestamp"].iloc[-1].isoformat(),
        "source": "yahoo_finance",
    }
