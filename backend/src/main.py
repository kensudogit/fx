"""
FastAPI エントリポイント — main

このモジュールは FX トレード支援プラットフォームのメインアプリケーションファイルです。
FastAPI アプリケーションの初期化・ミドルウェア登録・全 API エンドポイントの定義を行います。

主な責務:
    - アプリケーションライフサイクル管理（DB 初期化・スケジューラー起動・キャッシュウォームアップ）
    - REST API エンドポイントの登録（テクニカル分析 / AI 分析 / OANDA / TradingView 等）
    - CORS・SaaS 認証ミドルウェアの設定
"""

from contextlib import asynccontextmanager
import asyncio
import logging

from fastapi import BackgroundTasks, FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, Response

from src.analysis.chart import generate_technical_chart
from src.analysis.fundamental import (
    EVENT_LABELS,
    EventType,
    get_event_alerts,
    get_fundamental_data,
    get_upcoming_events,
    refresh_economic_calendar,
    get_calendar_source,
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
from src.ml.predictor import predict_price
from src.ml.trend_predictor import predict_trend
from src.ml.volatility_predictor import predict_volatility
from src.auth.middleware import SaaSAuthMiddleware
from src.auth.router import router as auth_router
from src.auth.service import bootstrap_auth
from src.auth.context import get_tenant_id
from src.tradingview.service import list_signals, save_signal
from src.infra.warmup import warm_analysis_cache

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    FastAPI アプリケーションのライフサイクル管理コンテキストマネージャー。

    起動時（yield 前）に以下を順に実行する:
        1. PostgreSQL スキーマ初期化（テーブル作成 / シードデータ投入）
        2. 認証サービスのブートストラップ（初期ユーザー / プラン作成）
        3. 経済カレンダーのウォームアップ（失敗しても起動は続行）
        4. 自動売買スケジューラーの起動（settings.autotrade_enabled が True の場合）
        5. 分析キャッシュのバックグラウンドウォームアップ（settings.cache_warmup_enabled が True の場合）

    Args:
        app: FastAPI アプリケーションインスタンス（未使用だが FastAPI の規約により必須）
    """
    # データベーステーブルとシードデータを初期化
    init_database()
    # JWT・API キー・プランなど認証基盤を初期化
    bootstrap_auth()
    try:
        # 経済カレンダーをキャッシュに読み込む（外部 API 失敗時も起動を止めない）
        await refresh_economic_calendar()
    except Exception as e:
        logger.warning("economic calendar warmup failed: %s", e)
    if settings.autotrade_enabled:
        # 設定で有効な場合のみ自動売買スケジューラーを起動
        start_scheduler()
    if settings.cache_warmup_enabled:
        # 主要通貨ペアの分析キャッシュをバックグラウンドで事前構築（起動をブロックしない）
        asyncio.create_task(warm_analysis_cache())
    yield
    # ── シャットダウン処理（必要に応じてここに追加）──


# ── FastAPI アプリケーション初期化 ──────────────────────
app = FastAPI(
    title="FX Tool API",
    description="テクニカル分析・ファンダメンタル分析 API（SaaS対応）",
    version="2.1.0",
    lifespan=lifespan,
)

# SaaS 認証ミドルウェアを最初に追加（全リクエストのテナント特定を行う）
app.add_middleware(SaaSAuthMiddleware)
# 各機能別ルーターを登録
app.include_router(auth_router)
app.include_router(ai_pro_router)
app.include_router(autotrade_router)
app.include_router(broker_router)
app.include_router(prices_router)

# CORS ミドルウェアを追加（フロントエンドからのクロスオリジンリクエストを許可）
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.get_cors_origins(),
    allow_credentials=True,
    allow_methods=["*"],   # 全 HTTP メソッドを許可
    allow_headers=["*"],   # 全ヘッダーを許可
)


def _validate_symbol(symbol: str) -> str:
    """
    通貨ペアシンボルのバリデーションと正規化を行う。

    入力を大文字に変換し、サポート対象シンボル一覧（SYMBOL_BASE_PRICES）に
    含まれない場合は 404 エラーを送出する。

    Args:
        symbol: 通貨ペアシンボル文字列（例: "usdjpy", "EURUSD"）

    Returns:
        大文字に正規化されたシンボル文字列。

    Raises:
        HTTPException: シンボルがサポート対象外の場合（status_code=404）
    """
    symbol = symbol.upper()
    if symbol not in SYMBOL_BASE_PRICES:
        raise HTTPException(status_code=404, detail=f"Symbol {symbol} not found")
    return symbol


def _build_technical_response(symbol: str, result_df, source: str) -> dict:
    """
    テクニカル分析結果の DataFrame を API レスポンス辞書に変換する。

    フロントエンド（React チャートライブラリ）が扱いやすいように、
    インジケーターを種別ごとにネストした構造で返す。

    Args:
        symbol: 通貨ペアシンボル（例: "USDJPY"）
        result_df: compute_all_indicators() が返す全インジケーター付き DataFrame
        source: データソース文字列（例: "database", "yahoo_finance", "sample"）

    Returns:
        以下のキーを持つ辞書:
            - symbol: 通貨ペア名
            - source: データ取得元
            - timestamps: ISO 8601 形式のタイムスタンプリスト
            - ohlcv: OHLC 値の辞書（各値は float リスト）
            - indicators: MA / ボリンジャーバンド / MACD / RSI / ストキャスティクス / 一目均衡表
            - latest: 最新足の終値・RSI・MACD 値
    """
    # タイムスタンプを ISO 8601 形式文字列のリストに変換（JSON シリアライズ可能にする）
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
                "sma_20": series_to_list(result_df["sma_20"]),   # 20 日単純移動平均
                "sma_50": series_to_list(result_df["sma_50"]),   # 50 日単純移動平均
                "ema_12": series_to_list(result_df["ema_12"]),   # 12 日指数移動平均（MACD 速線に使用）
                "ema_26": series_to_list(result_df["ema_26"]),   # 26 日指数移動平均（MACD 遅線に使用）
            },
            "bollinger_bands": {
                "upper": series_to_list(result_df["bb_upper"]),   # ボリンジャーバンド上限（+2σ）
                "middle": series_to_list(result_df["bb_middle"]), # ボリンジャーバンド中心（20 日 SMA）
                "lower": series_to_list(result_df["bb_lower"]),   # ボリンジャーバンド下限（-2σ）
            },
            "macd": {
                "macd": series_to_list(result_df["macd"]),              # MACD 線（EMA12 - EMA26）
                "signal": series_to_list(result_df["macd_signal"]),     # シグナル線（MACD の 9 日 EMA）
                "histogram": series_to_list(result_df["macd_histogram"]), # ヒストグラム（MACD - Signal）
            },
            "rsi": series_to_list(result_df["rsi"]),  # RSI（相対力指数）14 日
            "stochastic": {
                "k": series_to_list(result_df["stoch_k"]),  # ストキャスティクス %K
                "d": series_to_list(result_df["stoch_d"]),  # ストキャスティクス %D（%K の移動平均）
            },
            "ichimoku": {
                "tenkan": series_to_list(result_df["ichi_tenkan"]),     # 転換線（9 日高値・安値の中値）
                "kijun": series_to_list(result_df["ichi_kijun"]),       # 基準線（26 日高値・安値の中値）
                "senkou_a": series_to_list(result_df["ichi_senkou_a"]), # 先行スパン A（転換線と基準線の中値）
                "senkou_b": series_to_list(result_df["ichi_senkou_b"]), # 先行スパン B（52 日高値・安値の中値）
                "chikou": series_to_list(result_df["ichi_chikou"]),     # 遅行スパン（終値を 26 日過去にシフト）
            },
        },
        "latest": {
            # 最新足の終値（常に存在する）
            "close": float(result_df["close"].iloc[-1]),
            # RSI は計算に最低 14 本必要なため NaN が含まれる可能性がある
            "rsi": float(result_df["rsi"].dropna().iloc[-1]) if result_df["rsi"].notna().any() else None,
            # MACD は計算に最低 26 本必要なため NaN が含まれる可能性がある
            "macd": float(result_df["macd"].dropna().iloc[-1]) if result_df["macd"].notna().any() else None,
        },
    }


@app.get("/health")
async def health():
    """
    ヘルスチェックエンドポイント。

    サービスの稼働状態と ML バックエンドの利用可能状況を返す。
    ロードバランサーや監視ツールからの死活監視に使用される。

    Returns:
        status: "ok" 固定値
        ml_frameworks: 利用可能な ML フレームワーク一覧
        ml_price_backend: 現在アクティブな価格予測バックエンド名
        ml_price_backend_config: 設定ファイルで指定されたバックエンド名
    """
    frameworks = check_ml_frameworks()
    from src.ml.deep_learning import resolve_price_backend

    return {
        "status": "ok",
        "ml_frameworks": frameworks,
        "ml_price_backend": resolve_price_backend(),
        "ml_price_backend_config": settings.ml_price_backend,
    }


@app.get("/api/ml/frameworks")
async def ml_frameworks():
    """
    利用可能な ML フレームワークと LSTM 設定を返す。

    開発・デバッグ用エンドポイント。環境に応じて sklearn / TensorFlow / PyTorch の
    どれが使えるかを確認できる。

    Returns:
        frameworks: 各フレームワークの利用可能フラグ辞書
        price_backend_active: 現在アクティブなバックエンド名
        price_backend_config: 設定値（auto の場合は実際のバックエンドと異なる場合がある）
        lstm: LSTM モデルのハイパーパラメーター設定値
    """
    from src.ml.deep_learning import resolve_price_backend

    frameworks = check_ml_frameworks()
    return {
        "frameworks": frameworks,
        "price_backend_active": resolve_price_backend(),
        "price_backend_config": settings.ml_price_backend,
        "lstm": {
            "lookback": settings.ml_lstm_lookback,
            "epochs": settings.ml_lstm_epochs,
            "units": settings.ml_lstm_units,
            "batch_size": settings.ml_lstm_batch_size,
        },
    }


@app.get("/", response_class=HTMLResponse)
async def root():
    """
    ルートパスへのアクセスを Swagger UI（/docs）にリダイレクトする。

    Returns:
        自動リダイレクトのための HTML ページ（meta refresh 使用）
    """
    return """<!DOCTYPE html>
<html lang="ja"><head><meta charset="utf-8">
<meta http-equiv="refresh" content="0;url=/docs">
<title>FX Tool API</title></head>
<body><p>FX Tool API — <a href="/docs">API Docs</a></p></body></html>"""


@app.get("/api/symbols")
async def list_symbols():
    """
    サポートされている通貨ペアシンボルの一覧を返す。

    Returns:
        symbols: サポート対象の通貨ペアシンボル文字列リスト
    """
    return {"symbols": list(SYMBOL_BASE_PRICES.keys())}


@app.post("/api/data/sync/{symbol}")
async def sync_data(symbol: str, days: int = Query(default=200, ge=30, le=500)):
    """
    指定シンボルの OHLCV データを Yahoo Finance から取得して DB に同期する。

    Args:
        symbol: 通貨ペアシンボル（例: "USDJPY"）
        days: 取得する過去の日数（最小 30 日・最大 500 日、デフォルト 200 日）

    Returns:
        同期結果（rows_synced: 保存件数、latest_close: 最新終値 等）

    Raises:
        HTTPException: データ取得または DB 保存に失敗した場合（status_code=500）
    """
    symbol = _validate_symbol(symbol)
    try:
        result = sync_symbol_data(symbol, days)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/ohlcv/{symbol}")
async def get_ohlcv(symbol: str, days: int = Query(default=200, ge=30, le=500)):
    """
    指定シンボルの OHLCV（始値・高値・安値・終値・出来高）データを返す。

    データ取得の優先順位: DB → Yahoo Finance → サンプルデータ

    Args:
        symbol: 通貨ペアシンボル
        days: 取得する過去の日数（デフォルト 200 日）

    Returns:
        symbol・source・data リスト（各要素に timestamp / open / high / low / close / volume）
    """
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
    """
    テクニカル分析結果を返す。キャッシュヒット時は再計算をスキップする。

    指定した indicator パラメーターで特定のインジケーターのみ絞り込み可能。

    Args:
        symbol: 通貨ペアシンボル
        days: 分析に使用する過去の日数
        indicator: フィルタするインジケーター名（ma / bollinger_bands / macd / rsi / stochastic / ichimoku）
                   None の場合は全インジケーターを返す

    Returns:
        テクニカル分析結果の辞書（全インジケーターまたは指定インジケーターのみ）

    Raises:
        HTTPException: 不明なインジケーター名が指定された場合（status_code=400）
    """
    symbol = _validate_symbol(symbol)

    # キャッシュキーにシンボル・日数・インジケーターを含め、条件が違えば別エントリになるようにする
    cache_key = f"technical:{symbol}:{days}:{indicator or 'all'}"
    cached = dynamodb_client.get(cache_key)
    if cached:
        # キャッシュヒット: 再計算なしでレスポンスを返す
        return cached

    # DB または Yahoo Finance から OHLCV を取得し、全インジケーターを計算
    df, source = get_ohlcv_data(symbol, days)
    result_df = compute_all_indicators(df)
    response = _build_technical_response(symbol, result_df, source)

    if indicator:
        # 特定インジケーターが指定された場合、レスポンスを絞り込む
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

    # 計算結果をキャッシュに保存（次回リクエスト時の高速化）
    dynamodb_client.put(cache_key, response)
    return response


@app.get("/api/technical/{symbol}/signals")
async def get_trading_signals(symbol: str, days: int = Query(default=200, ge=30, le=500)):
    """
    最新足のテクニカルシグナル（買い・売り・中立）を返す。

    Args:
        symbol: 通貨ペアシンボル
        days: インジケーター計算に使用する過去の日数

    Returns:
        symbol・source・signals（各インジケーターの売買シグナル辞書）・price（最新終値）
    """
    symbol = _validate_symbol(symbol)
    df, source = get_ohlcv_data(symbol, days)
    result_df = compute_all_indicators(df)
    # 最新足（最終行）のインジケーター値からシグナルを生成
    latest = result_df.iloc[-1]
    signals = signals_from_row(latest)

    return {"symbol": symbol, "source": source, "signals": signals, "price": round(float(latest["close"]), 4)}


@app.get("/api/technical/{symbol}/multi-timeframe")
async def get_multi_timeframe(symbol: str):
    """
    複数タイムフレーム（日足・4時間足）のテクニカル分析結果を返す。

    CPU バウンドな処理を asyncio.to_thread でスレッドプールにオフロードし、
    イベントループをブロックしない。

    Args:
        symbol: 通貨ペアシンボル

    Returns:
        各タイムフレームのシグナル・トレンド方向・強度を含む辞書

    Raises:
        HTTPException: 分析処理に失敗した場合（status_code=500）
    """
    symbol = _validate_symbol(symbol)
    try:
        # スレッドプールで実行してイベントループをブロックしない
        return await asyncio.to_thread(analyze_multi_timeframe, symbol)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/technical/{symbol}/backtest")
async def get_signal_backtest(symbol: str, days: int = Query(default=200, ge=90, le=500)):
    """
    シグナルベースのバックテスト統計を返す。

    Args:
        symbol: 通貨ペアシンボル
        days: バックテスト期間の日数（最小 90 日で統計的有意性を確保）

    Returns:
        勝率・平均損益・プロフィットファクターなどのバックテスト統計
    """
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
    """
    リスク管理に基づいたポジションサイズを計算して返す。

    Args:
        symbol: 通貨ペアシンボル
        days: ATR 計算に使用する過去の日数
        account_balance: 口座残高（USD 等の基準通貨）
        risk_percent: 1 トレードで許容するリスク割合（%）
        stop_pips: ストップロスのピップ数（use_atr_stop=False の場合に使用）
        use_atr_stop: True の場合は ATR ベースのストップを自動計算する

    Returns:
        推奨ポジションサイズ・ストップロス・リスク金額などを含む辞書
    """
    symbol = _validate_symbol(symbol)
    df, _ = get_ohlcv_data(symbol, days)
    price = float(df["close"].iloc[-1])
    # use_atr_stop が True の場合のみ ATR を計算（ストップ幅の客観的な設定に使用）
    atr = calc_atr(compute_all_indicators(df)) if use_atr_stop else None
    return calculate_position_size(
        symbol, price, account_balance, risk_percent,
        stop_pips=stop_pips, atr=atr,
    )


@app.get("/api/chart/{symbol}")
async def get_chart(symbol: str, days: int = Query(default=200, ge=30, le=500)):
    """
    テクニカルチャート画像（PNG）を生成して返す。

    Args:
        symbol: 通貨ペアシンボル
        days: チャートに表示する過去の日数

    Returns:
        PNG 形式のチャート画像（Content-Type: image/png）
    """
    symbol = _validate_symbol(symbol)
    df, _ = get_ohlcv_data(symbol, days)
    # 全インジケーター付きチャートを PNG バイト列として生成
    png_bytes = generate_technical_chart(df, symbol, indicator="all")
    return Response(content=png_bytes, media_type="image/png")


@app.get("/api/fundamental")
async def get_fundamental(event_type: str | None = None):
    """
    ファンダメンタルイベントデータを返す。

    Args:
        event_type: フィルタするイベントタイプ（例: "interest_rate", "gdp"）
                    None の場合は全イベントタイプを返す

    Returns:
        events: イベントデータリスト
        labels: イベントタイプの日本語ラベル辞書

    Raises:
        HTTPException: 不明なイベントタイプが指定された場合（status_code=400）
    """
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
    """
    経済カレンダーを最新データに更新して返す。

    Returns:
        events: 今後の経済イベントリスト
        source: データソース名（"investing_com" 等）
    """
    # リクエストのたびに最新カレンダーを取得・更新する
    await refresh_economic_calendar()
    return {"events": get_upcoming_events(), "source": get_calendar_source()}


@app.get("/api/fundamental/alerts")
async def get_alerts(hours: int = Query(default=48, ge=1, le=168)):
    """
    指定時間以内に発生予定の重要経済指標アラートを返す。

    Args:
        hours: アラート対象の先読み時間（1〜168 時間、デフォルト 48 時間 = 2 日）

    Returns:
        alerts: アラートリスト（イベント名・予定時刻・影響度）
        within_hours: 指定された先読み時間
    """
    return {"alerts": get_event_alerts(hours), "within_hours": hours}


def _require_openai():
    """
    OpenAI API キーが設定されていることを確認するガード関数。

    AI 分析エンドポイントの冒頭で呼び出し、キーが未設定の場合は
    ユーザーフレンドリーなエラーメッセージを返す。

    Raises:
        HTTPException: OpenAI API キーが未設定の場合（status_code=503）
    """
    if not resolve_openai_api_key():
        raise HTTPException(
            status_code=503,
            detail="OPENAI_API_KEY が未設定です。Railway の Variables に OPENAI_API_KEY を登録してください。",
        )


@app.get("/api/ai/status")
async def ai_status():
    """
    OpenAI 設定状況を返す。

    Returns:
        configured: API キーが設定されているか（bool）
        model: 使用中のモデル名
        key_preview: API キーの先頭 8 文字（セキュリティのため全体は返さない）
    """
    key = resolve_openai_api_key()
    return {
        "configured": bool(key),
        "model": settings.openai_model,
        # セキュリティ上、API キーの先頭 8 文字のみプレビューとして返す
        "key_preview": f"{key[:8]}..." if len(key) > 8 else None,
    }


@app.get("/api/ml/predict/{symbol}")
async def predict_price_endpoint(symbol: str, days: int = Query(default=200, ge=50, le=500)):
    """
    ML モデルによる価格予測を返す。

    sklearn / TensorFlow / PyTorch のいずれかのバックエンドで予測を実行する。
    CPU バウンドな処理はスレッドプールにオフロードする。

    Args:
        symbol: 通貨ペアシンボル
        days: 予測に使用する過去の日数（最小 50 日で特徴量計算を保証）

    Returns:
        予測価格・予測方向・信頼区間などを含む辞書
    """
    symbol = _validate_symbol(symbol)
    # ML 予測は CPU バウンドのためスレッドプールで実行
    return await asyncio.to_thread(predict_price, symbol, days)


@app.get("/api/ai/news/{symbol}")
async def ai_news(symbol: str, limit: int = Query(default=8, ge=3, le=15)):
    """
    OpenAI を使ったニュース感情分析結果を返す。

    Args:
        symbol: 通貨ペアシンボル
        limit: 取得するニュース記事数（最小 3・最大 15）

    Returns:
        summary / sentiment / sentiment_score / key_topics / market_impact を含む辞書

    Raises:
        HTTPException: OpenAI キー未設定（503）または分析エラー（500）
    """
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
    """
    OpenAI による経済指標・ファンダメンタル分析を返す。

    Args:
        symbol: 通貨ペアシンボル

    Returns:
        経済指標の解釈・市場への影響評価を含む辞書

    Raises:
        HTTPException: OpenAI キー未設定（503）または分析エラー（500）
    """
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
    """
    OpenAI によるテクニカル・ファンダメンタル統合売買判断を返す。

    Args:
        symbol: 通貨ペアシンボル
        days: テクニカル分析に使用する過去の日数

    Returns:
        action（buy/sell/hold）・信頼度・根拠説明を含む辞書

    Raises:
        HTTPException: OpenAI キー未設定（503）または判断エラー（500）
    """
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
    """
    OpenAI によるリスク評価レポートを返す。

    Args:
        symbol: 通貨ペアシンボル
        days: ボラティリティ計算に使用する過去の日数
        account_balance: 口座残高（リスク金額の計算に使用）

    Returns:
        リスクレベル・最大ドローダウン予測・推奨ストップロス等を含む辞書

    Raises:
        HTTPException: OpenAI キー未設定（503）またはリスク評価エラー（500）
    """
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
    """
    テクニカル・ファンダメンタル・AI 分析を統合した総合レポートを返す。

    全分析を順次実行するため、他のエンドポイントより応答時間が長くなる場合がある。

    Args:
        symbol: 通貨ペアシンボル
        days: 分析に使用する過去の日数
        account_balance: 口座残高

    Returns:
        technical / fundamental / ai_decision / risk / summary を含む総合レポート辞書

    Raises:
        HTTPException: OpenAI キー未設定（503）またはレポート生成エラー（500）
    """
    _require_openai()
    symbol = _validate_symbol(symbol)
    try:
        return await generate_full_report(symbol, days, account_balance)
    except ValueError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"レポート生成エラー: {e}")


# ── TradingView Webhook ──
async def _run_tradingview_autotrade(signal: dict, tenant_id: int | None) -> None:
    """
    TradingView シグナルに基づく自動売買をバックグラウンドで実行する。

    BackgroundTasks から呼び出されるため、レスポンス返却後に非同期で実行される。
    エラーが発生しても例外を上位に伝播させず、ログに記録するのみにとどめる。

    Args:
        signal: TradingView Webhook から受信したシグナル辞書
        tenant_id: 実行対象のテナント ID（None の場合はシングルテナントモード）
    """
    try:
        from src.autotrade.engine import process_tradingview_signal

        await process_tradingview_signal(signal, tenant_id)
    except Exception as e:
        # バックグラウンドタスクの例外は上位に伝播しないためログに記録する
        logger.exception("TradingView autotrade failed for tenant %s: %s", tenant_id, e)


@app.post("/api/tradingview/webhook", status_code=202)
async def tradingview_webhook(request: Request, background_tasks: BackgroundTasks):
    """TradingView アラート → Webhook URL（SaaS: X-API-Key でテナント特定）

    TradingView から送信される Webhook を受信し、シグナルを保存する。
    自動売買が有効かつ auto_execute_tradingview が設定されている場合は
    バックグラウンドで注文を発注する。

    Args:
        request: FastAPI リクエストオブジェクト（JSON ボディ・ヘッダー取得に使用）
        background_tasks: FastAPI バックグラウンドタスクキュー

    Returns:
        ok: True
        signal: 保存されたシグナル情報
        autotrade: "processing"（自動売買実行中）または None

    Raises:
        HTTPException: JSON パースエラー（400）/ 認証失敗（401）
    """
    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    tenant_id = get_tenant_id()
    if settings.saas_enabled:
        if not tenant_id:
            # SaaS モードでテナントが特定できていない場合、X-API-Key ヘッダーからテナントを解決する
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
            # API キーでもテナントが特定できない場合は認証エラー
            raise HTTPException(
                status_code=401,
                detail="TradingView Webhook には X-API-Key ヘッダーが必要です",
            )
    else:
        # シングルテナントモードでは Webhook シークレットによる簡易認証を行う
        secret = settings.tradingview_webhook_secret
        if secret:
            header = request.headers.get("X-Webhook-Secret", "")
            # ヘッダーまたはペイロード内の secret フィールドどちらかが一致すれば認証成功
            if header != secret and payload.get("secret") != secret:
                raise HTTPException(status_code=401, detail="Invalid webhook secret")

    # シグナルをデータベースに保存（テナント ID 紐付け）
    signal = save_signal(payload, tenant_id)

    from src.autotrade.models import get_config

    config = get_config(tenant_id)
    if config.get("enabled") and config.get("auto_execute_tradingview"):
        # 自動売買が有効かつ TradingView シグナルの自動実行が設定されている場合
        # バックグラウンドで注文を発注（レスポンスを即座に返してから実行）
        background_tasks.add_task(_run_tradingview_autotrade, signal, tenant_id)
        return {
            "ok": True,
            "signal": signal,
            "autotrade": "processing",
        }

    return {"ok": True, "signal": signal, "autotrade": None}


@app.get("/api/tradingview/signals")
async def tradingview_signals(symbol: str | None = None, limit: int = Query(default=20, le=100)):
    """
    保存済み TradingView シグナルの一覧を返す。

    Args:
        symbol: フィルタする通貨ペアシンボル（None の場合は全シンボル）
        limit: 取得件数の上限（最大 100）

    Returns:
        signals: シグナルオブジェクトのリスト
    """
    return {"signals": list_signals(symbol, limit, get_tenant_id())}


# ── ニュース分析（ML + OpenAI）──
@app.get("/api/news/analysis/{symbol}")
async def news_analysis(symbol: str, limit: int = Query(default=8, ge=3, le=15)):
    """
    ML ベースと OpenAI ベースのニュース感情分析を統合して返す。

    ML 分析は常に実行し、OpenAI 分析は API キーが設定されている場合のみ実行する。

    Args:
        symbol: 通貨ペアシンボル
        limit: 取得するニュース記事数

    Returns:
        articles: 取得したニュース記事リスト
        ml: ML 感情分析結果
        openai: OpenAI 感情分析結果（API キー未設定時は None）
        openai_error: OpenAI 分析失敗時のエラーメッセージ（省略可能）
    """
    symbol = _validate_symbol(symbol)
    articles = await fetch_rss_news(symbol, limit)
    # 記事タイトルのみを ML モデルの入力として使用（本文は不要）
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
            # OpenAI レスポンスから必要なフィールドのみを抽出して返す
            result["openai"] = {
                "summary": ai.get("summary"),
                "sentiment": ai.get("sentiment"),
                "sentiment_score": ai.get("sentiment_score"),
                "key_topics": ai.get("key_topics"),
                "market_impact": ai.get("market_impact"),
            }
        except Exception as e:
            # OpenAI 分析が失敗しても ML 分析結果は返す
            result["openai_error"] = str(e)
    return result


# ── Backtrader バックテスト ──
@app.get("/api/backtest/backtrader/{symbol}")
async def backtrader_backtest(
    symbol: str,
    days: int = Query(default=200, ge=90, le=500),
    cash: float = Query(default=10000, ge=1000),
):
    """
    Backtrader フレームワークを使用したバックテストを実行する。

    Args:
        symbol: 通貨ペアシンボル
        days: バックテスト期間の日数（最小 90 日）
        cash: 初期資金（基準通貨）

    Returns:
        最終資産・取引数・勝率・最大ドローダウンなどのバックテスト統計
    """
    symbol = _validate_symbol(symbol)
    return run_backtrader_backtest(symbol, days, cash)


# ── OANDA 注文 ──
@app.get("/api/oanda/status")
async def oanda_status():
    """
    OANDA 口座のサマリー情報（残高・証拠金・オープンポジション数等）を返す。

    Returns:
        OANDA 口座サマリー辞書
    """
    return get_account_summary(get_tenant_id())


@app.get("/api/oanda/orders")
async def oanda_orders(limit: int = Query(default=20, le=100)):
    """
    OANDA の注文履歴を返す。

    Args:
        limit: 取得する注文件数の上限

    Returns:
        orders: 注文情報のリスト
    """
    return {"orders": list_orders(limit, get_tenant_id())}


@app.post("/api/oanda/orders")
async def oanda_place_order(
    symbol: str = Query(...),
    side: str = Query(..., pattern="^(buy|sell)$"),
    units: int = Query(default=1000, ge=1, le=1_000_000),
):
    """
    OANDA に成行注文を発注する。

    Args:
        symbol: 通貨ペアシンボル
        side: 売買方向（"buy" または "sell"）
        units: 取引単位数（1〜1,000,000）

    Returns:
        OANDA が返す注文確認情報

    Raises:
        HTTPException: パラメーターエラー（400）または OANDA API エラー（502）
    """
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
    """
    React フロントエンド向けの統合ダッシュボードデータを返す。

    テクニカル・ファンダメンタル・AI 分析の結果を一括で返すため、
    フロントエンドからの複数 API 呼び出しを削減できる（BFF パターン）。

    Args:
        symbol: 通貨ペアシンボル（デフォルト: USDJPY）
        days: 分析に使用する過去の日数

    Returns:
        テクニカル分析・ファンダメンタル情報・シグナル等を統合した辞書

    Raises:
        HTTPException: ダッシュボード構築エラー（status_code=500）
    """
    symbol = _validate_symbol(symbol)
    try:
        return await build_dashboard(symbol, days)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── 5大分析（トレンド / ニュース / SNS / 経済指標 / ボラ）──
@app.get("/api/analysis/trend/{symbol}")
async def analysis_trend(symbol: str, days: int = Query(default=200, ge=60, le=500)):
    """
    ML モデルによるトレンド予測（上昇・下降・横ばい）を返す。

    Args:
        symbol: 通貨ペアシンボル
        days: 予測に使用する過去の日数（最小 60 日）

    Returns:
        trend_direction・trend_strength・confidence などを含む辞書
    """
    symbol = _validate_symbol(symbol)
    return await asyncio.to_thread(predict_trend, symbol, days)


@app.get("/api/analysis/news/{symbol}")
async def analysis_news(symbol: str, limit: int = Query(default=8, ge=3, le=15)):
    """
    ニュース感情分析結果（ML + OpenAI）を返す。

    /api/news/analysis/{symbol} と同等の機能を提供する 5 大分析ルート。

    Args:
        symbol: 通貨ペアシンボル
        limit: 取得するニュース記事数

    Returns:
        articles・ml・openai キーを含む感情分析結果辞書
    """
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
    """
    SNS（ソーシャルメディア）のセンチメント分析結果を返す。

    Args:
        symbol: 通貨ペアシンボル
        limit: 取得する投稿数の上限

    Returns:
        SNS センチメントスコア・強気・弱気の割合などを含む辞書
    """
    symbol = _validate_symbol(symbol)
    return await analyze_sns(symbol, limit)


@app.get("/api/analysis/economic/{symbol}")
async def analysis_economic(symbol: str):
    """
    通貨ペアに関連する経済指標の分析結果を返す。

    Args:
        symbol: 通貨ペアシンボル（例: USDJPY → 米国・日本の経済指標）

    Returns:
        関連経済指標・市場への影響評価などを含む辞書
    """
    symbol = _validate_symbol(symbol)
    return await analyze_economic(symbol)


@app.get("/api/analysis/volatility/{symbol}")
async def analysis_volatility(symbol: str, days: int = Query(default=200, ge=60, le=500)):
    """
    ML モデルによるボラティリティ予測を返す。

    Args:
        symbol: 通貨ペアシンボル
        days: 予測に使用する過去の日数

    Returns:
        予測ボラティリティ・ATR・リスクレベルなどを含む辞書
    """
    symbol = _validate_symbol(symbol)
    # CPU バウンドな ML 処理をスレッドプールにオフロード
    return await asyncio.to_thread(predict_volatility, symbol, days)


@app.get("/api/analysis/intelligence/{symbol}")
async def analysis_intelligence(symbol: str, days: int = Query(default=200, ge=60, le=500)):
    """
    テクニカル・ファンダメンタル・ML・センチメントを統合したインテリジェンス分析を返す。

    Args:
        symbol: 通貨ペアシンボル
        days: 分析に使用する過去の日数

    Returns:
        総合スコア・各分析軸のサブスコア・推奨アクションを含む辞書

    Raises:
        HTTPException: インテリジェンス構築エラー（status_code=500）
    """
    symbol = _validate_symbol(symbol)
    try:
        return await build_intelligence(symbol, days)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/analysis/market/{symbol}")
async def analysis_market(symbol: str, days: int = Query(default=200, ge=60, le=500)):
    """
    詳細マーケット分析レポートを返す。

    Args:
        symbol: 通貨ペアシンボル
        days: 分析に使用する過去の日数

    Returns:
        市場環境評価・トレンド強度・サポート/レジスタンスなどを含む辞書

    Raises:
        HTTPException: 分析エラー（status_code=500）
    """
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
    """
    詳細リスクレポートを生成して返す。

    VaR（バリュー・アット・リスク）・最大ドローダウン・シャープレシオ等の
    統計的リスク指標を含む詳細レポートを生成する。

    Args:
        symbol: 通貨ペアシンボル
        account_balance: 口座残高（リスク金額計算に使用）
        risk_percent: 許容リスク割合（%）
        days: 統計計算に使用する過去の日数

    Returns:
        VaR・最大ドローダウン・推奨ポジションサイズ等を含むリスクレポート辞書

    Raises:
        HTTPException: レポート生成エラー（status_code=500）
    """
    symbol = _validate_symbol(symbol)
    try:
        return build_risk_report(symbol, account_balance, risk_percent, days)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
