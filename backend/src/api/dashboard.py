"""
統合ダッシュボード API モジュール

このモジュールは、FX トレーディングダッシュボードの主要データを構築する
`build_dashboard` 関数を提供するバックエンドフォーフロントエンド（BFF）モジュール。
ルーターは定義せず、他のルーターから呼び出される共通データ構築関数として機能する。

以下のデータを統合して返す:
  - リアルタイム価格（最新終値）
  - テクニカル指標に基づくシグナル（RSI・MACD・ボリンジャーバンドなど）
  - マルチタイムフレーム分析（短・中・長期の方向性整合）
  - ML ベースのニュースセンチメント分析
  - シンプルバックテスト結果
  - Backtrader によるバックテスト結果
  - TradingView シグナル連携
  - OANDA アカウントサマリー・注文履歴
  - スタック情報（技術構成の概要）

設計方針:
  このモジュールはルーターを持たない純粋な関数モジュールとして実装することで、
  複数のルーターエンドポイントから同じダッシュボードデータを再利用可能にしている。
"""

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
    """
    指定通貨ペアの統合ダッシュボードデータを構築して返す。

    テクニカル分析・ML 分析・ニュース取得・バックテスト・ブローカー情報など
    複数の処理を実行し、フロントエンドのダッシュボード画面に必要な
    すべてのデータをまとめて返す。

    処理フロー:
        1. OHLCV データ取得（OANDA またはサンプルデータ）
        2. テクニカル指標計算（RSI・MACD・ボリンジャーバンドなど全指標）
        3. シグナル生成（最新バーのテクニカルシグナル）
        4. RSS ニュース取得と ML センチメント分析
        5. マルチタイムフレーム分析
        6. シンプルバックテスト実行
        7. Backtrader バックテスト実行（エラー時はエラー情報を返す）
        8. TradingView シグナル取得
        9. OANDA アカウントサマリー・注文履歴取得

    Args:
        symbol (str): 通貨ペア（例: "USDJPY"）。大文字で正規化して返す。
        days (int): 分析対象の過去日数（デフォルト: 200）

    Returns:
        dict: ダッシュボードデータ。以下のキーを含む:
            - symbol (str): 大文字の通貨ペア
            - price (float): 最新終値（小数点4桁）
            - source (str): データソース（"oanda" / "sample"）
            - signals (dict): テクニカルシグナル（buy/sell/neutral の各指標）
            - multi_timeframe (dict): マルチタイムフレーム分析結果
            - news_ml (dict): ML ニュースセンチメント + 記事数
            - openai_configured (bool): OpenAI API キーが設定されているか
            - backtest_simple (dict): シンプルバックテスト結果
            - backtest_backtrader (dict): Backtrader バックテスト結果（エラー時は status="error"）
            - tradingview_signals (list): TradingView からのシグナル一覧
            - oanda (dict | None): OANDA アカウントサマリー（未設定時は None）
            - recent_orders (list): 直近の注文履歴
            - stack (dict): 技術スタック情報（FastAPI / Next.js）
    """
    # OHLCV データを取得（OANDA が設定されていればリアルデータ、なければサンプルデータを使用）
    df, source = get_ohlcv_data(symbol, days)
    # RSI・MACD・ボリンジャーバンドなど全テクニカル指標を計算
    result_df = compute_all_indicators(df)
    # 最新バー（最終行）のデータを取得してシグナルを生成
    latest = result_df.iloc[-1]
    signals = signals_from_row(latest)
    # RSS フィードから最新ニュース記事を最大 8 件取得（非同期 I/O）
    articles = await fetch_rss_news(symbol, 8)
    # ニュース記事のタイトルのみ抽出して ML センチメント分析の入力とする
    headlines = [a["title"] for a in articles]
    # ML モデルによるヘッドラインセンチメント分析（bullish / bearish / neutral）
    ml_news = analyze_headlines_ml(headlines)

    # マルチタイムフレーム分析（短・中・長期の方向性を統合評価）
    mtf = analyze_multi_timeframe(symbol)
    # シンプルなシグナルバックテスト（ルールベース）
    simple_bt = backtest_signals(result_df)
    try:
        # Backtrader フレームワークによる本格的なバックテストを実行
        bt = run_backtrader_backtest(symbol, days)
    except Exception as e:
        # Backtrader のエラーはダッシュボード全体を壊さないようにキャッチして
        # エラー情報のみ返す（他のデータは正常に返す）
        bt = {"status": "error", "message": str(e)}

    return {
        "symbol": symbol.upper(),
        "price": round(float(latest["close"]), 4),
        "source": source,
        "signals": signals,
        "multi_timeframe": mtf,
        # ML センチメント結果に記事数を追加してまとめて返す
        "news_ml": {**ml_news, "article_count": len(articles)},
        # OpenAI API キーが設定されているかを確認（フロントエンドで AI チャット表示制御に使用）
        "openai_configured": bool(resolve_openai_api_key()),
        "backtest_simple": simple_bt,
        "backtest_backtrader": bt,
        # TradingView シグナル（テナント別・直近 5 件）
        "tradingview_signals": list_signals(symbol, 5, get_tenant_id()),
        # OANDA アカウントサマリー（OANDA 未設定の場合は None が返る）
        "oanda": get_account_summary(get_tenant_id()),
        # 直近 5 件の注文履歴
        "recent_orders": list_orders(5, get_tenant_id()),
        # 技術スタック情報（フロントエンドのデバッグ・確認用）
        "stack": {
            "api": "FastAPI (Python)",
            "frontend": "Next.js / React",
            "note": "Spring Boot 相当の API 層は FastAPI で実装",
        },
    }
