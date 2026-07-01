"""
市場データ取得・永続化サービス — data/market_data

FX 通貨ペアの OHLCV データを外部ソースから取得し、PostgreSQL に保存・読み込みする
データアクセスレイヤーモジュール。

データ取得の優先順位:
    1. PostgreSQL DB（最速・外部 API 呼び出しなし）
    2. Yahoo Finance Chart API（httpx による直接アクセス）
    3. yfinance ライブラリ（Chart API 失敗時のフォールバック）
    4. サンプルデータ（全ての外部取得が失敗した場合）

主な責務:
    - Yahoo Finance からの OHLCV データ取得（複数フォールバック付き）
    - PostgreSQL への OHLCV データ upsert（重複排除）
    - DB からの OHLCV データ読み込み
    - データソースを意識しない統合インターフェースの提供（get_ohlcv_data）
"""

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

# 通貨ペアシンボルから Yahoo Finance ティッカーへのマッピング
# Yahoo Finance では FX レートは "=X" サフィックスで識別される
YAHOO_TICKERS = {
    "USDJPY": "USDJPY=X",
    "EURUSD": "EURUSD=X",
    "GBPUSD": "GBPUSD=X",
    "AUDUSD": "AUDUSD=X",
}

# Yahoo Finance スクレイピング対策の User-Agent ヘッダー
# これがないと 429 Too Many Requests または 403 Forbidden が返る場合がある
YAHOO_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
}


def fetch_from_yahoo_chart_api(symbol: str, days: int = 200, interval: str = "1d") -> pd.DataFrame:
    """
    Yahoo Finance Chart API（v8）から OHLCV データを直接取得する。

    httpx を使用して Yahoo Finance の内部 Chart API エンドポイントにアクセスし、
    JSON レスポンスを解析して pandas DataFrame を構築する。
    yfinance ライブラリより高速で API クォータの制限を受けにくい。

    Args:
        symbol: 通貨ペアシンボル（例: "USDJPY"）
        days: 取得する日数（1d 足の場合）または期間の基準値（4h 足の場合は別途計算）
        interval: データの時間足（"1d" = 日足、"4h" = 4 時間足）

    Returns:
        timestamp / open / high / low / close / volume 列を持つ pandas DataFrame

    Raises:
        ValueError: 未知のシンボル、データなし、または空のレスポンスの場合
        httpx.HTTPError: HTTP リクエストが失敗した場合
    """
    ticker = YAHOO_TICKERS.get(symbol.upper())
    if not ticker:
        raise ValueError(f"Unknown symbol: {symbol}")

    if interval == "4h":
        # 4 時間足: Yahoo Finance では "60d" レンジで 4h データを取得
        # 1 日 = 約 6 本（24h ÷ 4h）なので、days 日分のデータ本数を概算
        range_param = "60d"
        interval_param = "4h"
        tail = min(days * 6, 360)  # 最大 360 本（60 日 × 6 本/日）に制限
    else:
        # 日足: days > 365 の場合は 2 年分、それ以外は 1 年分を取得
        range_param = "2y" if days > 365 else "1y"
        interval_param = "1d"
        tail = days

    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
    params = {"interval": interval_param, "range": range_param}

    with httpx.Client(timeout=30.0, headers=YAHOO_HEADERS) as client:
        response = client.get(url, params=params)
        response.raise_for_status()
        payload = response.json()

    # Chart API レスポンス構造: {"chart": {"result": [...]}}
    result = payload.get("chart", {}).get("result")
    if not result:
        raise ValueError(f"No chart data for {symbol}")

    chart = result[0]
    timestamps = chart.get("timestamp", [])
    # quote データは result[0]["indicators"]["quote"][0] に格納されている
    quote = chart["indicators"]["quote"][0]

    if not timestamps:
        raise ValueError(f"Empty timestamps for {symbol}")

    # Unix タイムスタンプをタイムゾーン付き datetime に変換して DataFrame を構築
    df = pd.DataFrame(
        {
            "timestamp": [datetime.fromtimestamp(ts, tz=timezone.utc) for ts in timestamps],
            "open": quote.get("open", []),
            "high": quote.get("high", []),
            "low": quote.get("low", []),
            "close": quote.get("close", []),
            # volume が含まれない場合はゼロで埋める（FX データでは出来高が提供されないことが多い）
            "volume": quote.get("volume", [0] * len(timestamps)),
        }
    )
    # close が NaN の行（マーケットクローズ時間等）を除外
    df = df.dropna(subset=["close"]).reset_index(drop=True)
    # volume の NaN をゼロに変換し、整数型に変換
    df["volume"] = df["volume"].fillna(0).astype(int)

    if df.empty:
        raise ValueError(f"No valid OHLCV rows for {symbol}")

    # 最新の tail 本分のデータのみを返す（インデックスをリセット）
    return df.tail(tail).reset_index(drop=True)


def fetch_from_yfinance(symbol: str, days: int = 200, interval: str = "1d") -> pd.DataFrame:
    """
    yfinance ライブラリを使用して Yahoo Finance から OHLCV データを取得する。

    fetch_from_yahoo_chart_api の失敗時のフォールバックとして機能する。
    yfinance はライブラリ側でレート制限やリトライを管理するため安定性が高い。

    Args:
        symbol: 通貨ペアシンボル（例: "USDJPY"）
        days: 取得する日数
        interval: データの時間足（"1d" または "4h"）

    Returns:
        timestamp / open / high / low / close / volume 列を持つ pandas DataFrame

    Raises:
        ValueError: 未知のシンボルまたはデータが取得できない場合
    """
    ticker = YAHOO_TICKERS.get(symbol.upper())
    if not ticker:
        raise ValueError(f"Unknown symbol: {symbol}")

    # 4h 足は 60 日分、日足は days > 365 なら 2 年分、それ以外は 1 年分
    period = "60d" if interval == "4h" else ("2y" if days > 365 else "1y")
    # progress=False: ダウンロードプログレスバーを非表示
    # auto_adjust=True: 株式分割・配当調整（FX では実質的に影響なし）
    raw = yf.download(ticker, period=period, interval=interval, progress=False, auto_adjust=True)

    if raw.empty:
        raise ValueError(f"No data returned for {symbol}")

    # マルチティッカー取得時は MultiIndex カラムになるため、第 0 レベルに正規化
    if isinstance(raw.columns, pd.MultiIndex):
        raw.columns = raw.columns.get_level_values(0)

    df = raw.reset_index()
    # カラム名をすべて小文字に統一（yfinance のバージョンによってカラム名が変わるため）
    rename = {c: c.lower() if isinstance(c, str) else c for c in df.columns}
    df = df.rename(columns=rename)
    # 日付カラムは "date" または先頭カラムで動的に特定
    date_col = "date" if "date" in df.columns else df.columns[0]

    result = pd.DataFrame(
        {
            "timestamp": pd.to_datetime(df[date_col]),
            "open": df["open"].astype(float),
            "high": df["high"].astype(float),
            "low": df["low"].astype(float),
            "close": df["close"].astype(float),
            # volume カラムが存在しない場合は 0 を使用
            "volume": df.get("volume", 0).fillna(0).astype(int),
        }
    )
    # 4h 足の場合は days × 6 本、日足の場合は days 本に絞る
    tail = min(days * 6, 360) if interval == "4h" else days
    return result.tail(tail).reset_index(drop=True)


def fetch_from_yahoo(symbol: str, days: int = 200, interval: str = "1d") -> pd.DataFrame:
    """
    Yahoo Finance から OHLCV データを取得する（フォールバック付きラッパー）。

    Chart API → yfinance の順で試行し、両方失敗した場合は例外を送出する。

    Args:
        symbol: 通貨ペアシンボル
        days: 取得する日数
        interval: データの時間足（"1d" または "4h"）

    Returns:
        OHLCV DataFrame

    Raises:
        ValueError: 全てのフェッチャーが失敗した場合（各エラーメッセージを含む）
    """
    errors = []
    # Chart API を第一候補、yfinance をフォールバックとして順に試行
    for fetcher in (fetch_from_yahoo_chart_api, fetch_from_yfinance):
        try:
            return fetcher(symbol, days, interval)
        except Exception as e:
            errors.append(str(e))
            logger.warning("%s failed for %s: %s", fetcher.__name__, symbol, e)
    # 全フェッチャーが失敗した場合は全エラーを結合して例外を送出
    raise ValueError(f"All fetchers failed for {symbol}: {'; '.join(errors)}")


def save_ohlcv_to_db(db: Session, symbol: str, df: pd.DataFrame, timeframe: str = "1d") -> int:
    """
    OHLCV データを PostgreSQL に upsert（挿入または更新）する。

    (symbol, timestamp, timeframe) の組み合わせを一意キーとして、
    既存レコードは最新データで更新し、新規レコードは挿入する。

    Args:
        db: SQLAlchemy セッション
        symbol: 通貨ペアシンボル（大文字に正規化される）
        df: 保存する OHLCV DataFrame
        timeframe: 足種（"1d" または "4h"）

    Returns:
        保存（挿入または更新）したレコード数
    """
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

    # PostgreSQL の INSERT ... ON CONFLICT DO UPDATE（upsert）を使用
    stmt = insert(OHLCVRecord).values(rows)
    stmt = stmt.on_conflict_do_update(
        # 一意制約: (symbol, timestamp, timeframe) の組み合わせ
        index_elements=["symbol", "timestamp", "timeframe"],
        # 競合時は OHLCV 値を最新データで更新（既存レコードを上書き）
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
    """
    PostgreSQL から OHLCV データを読み込んで DataFrame として返す。

    最新の days 本分のデータを降順で取得し、時系列順（昇順）に並べ直して返す。

    Args:
        db: SQLAlchemy セッション
        symbol: 通貨ペアシンボル（大文字に変換して検索）
        days: 取得する最大レコード数
        timeframe: 足種（"1d" または "4h"）

    Returns:
        OHLCV DataFrame（データが存在しない場合は None）
    """
    records = (
        db.query(OHLCVRecord)
        .filter(OHLCVRecord.symbol == symbol.upper(), OHLCVRecord.timeframe == timeframe)
        .order_by(OHLCVRecord.timestamp.desc())  # 最新のものから取得
        .limit(days)
        .all()
    )
    if not records:
        return None

    # reversed() で降順から昇順（時系列順）に並べ直してリスト化
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
    OHLCV データを取得する統合インターフェース。

    呼び出し元はデータ取得元を意識せず、常に DataFrame を受け取ることができる。
    取得優先順位: DB → Yahoo Finance → サンプルデータ

    timeframe:
        "1d" = 日足（DB キャッシュあり）
        "4h" = 4 時間足（Yahoo Finance 直接取得のみ、DB キャッシュなし）

    Args:
        symbol: 通貨ペアシンボル（例: "USDJPY"）
        days: 取得する日数
        timeframe: 足種（"1d" または "4h"）

    Returns:
        (DataFrame, source_string) のタプル
        source_string は "database" / "yahoo_finance" / "sample" のいずれか

    Raises:
        ValueError: サポートされていないシンボルの場合
    """
    symbol = symbol.upper()
    if symbol not in SYMBOL_BASE_PRICES:
        raise ValueError(f"Unknown symbol: {symbol}")

    if timeframe != "1d":
        # 4 時間足は DB キャッシュなし: Yahoo Finance から直接取得
        try:
            df = fetch_from_yahoo(symbol, days, interval=timeframe)
            return df, "yahoo_finance"
        except Exception as e:
            logger.warning("Yahoo %s fetch failed for %s: %s", timeframe, symbol, e)
            base_price = SYMBOL_BASE_PRICES[symbol]
            # Yahoo 取得失敗時はサンプルデータで代替（最大 90 日）
            return generate_sample_ohlcv(symbol, min(days, 90), base_price), "sample"

    # ── 日足（1d）の取得フロー ──────────────────────────
    # ステップ 1: DB から取得を試みる（最速・外部 API 不要）
    db = SessionLocal()
    try:
        df = load_ohlcv_from_db(db, symbol, days)
        # DB に十分なデータがある場合（最低 30 本）は DB データを使用
        if df is not None and len(df) >= min(days, 30):
            return df, "database"
    except Exception as e:
        logger.warning("DB read failed for %s: %s", symbol, e)
    finally:
        db.close()

    # ステップ 2: Yahoo Finance からデータを取得して DB に保存
    try:
        df = fetch_from_yahoo(symbol, days)
        db = SessionLocal()
        try:
            # 取得したデータを DB に保存（次回リクエスト時は DB から高速取得可能）
            save_ohlcv_to_db(db, symbol, df)
        except Exception as e:
            # DB 書き込み失敗は警告のみ（データ返却は続行）
            logger.warning("DB write failed for %s: %s", symbol, e)
        finally:
            db.close()
        return df, "yahoo_finance"
    except Exception as e:
        logger.warning("Yahoo fetch failed for %s: %s", symbol, e)

    # ステップ 3: 全ての外部取得が失敗した場合はサンプルデータを使用
    base_price = SYMBOL_BASE_PRICES[symbol]
    return generate_sample_ohlcv(symbol, days, base_price), "sample"


def sync_symbol_data(symbol: str, days: int = 200) -> dict:
    """
    Yahoo Finance から最新データを取得して PostgreSQL に同期する。

    /api/data/sync/{symbol} エンドポイントから呼び出される手動同期関数。
    定期的に実行することで DB のデータを最新に保つ。

    Args:
        symbol: 通貨ペアシンボル（大文字に正規化される）
        days: 取得・同期する日数

    Returns:
        同期結果を含む辞書:
            - symbol: 通貨ペアシンボル
            - rows_synced: 保存（upsert）したレコード数
            - latest_close: 最新足の終値
            - latest_date: 最新足のタイムスタンプ（ISO 8601 形式）
            - source: データソース名（常に "yahoo_finance"）

    Raises:
        ValueError: Yahoo Finance からのデータ取得に失敗した場合
    """
    symbol = symbol.upper()
    # Yahoo Finance からデータを取得（失敗時は例外を上位に伝播）
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
