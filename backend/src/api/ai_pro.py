"""
AI Pro 統合 API モジュール

このモジュールは、AI Proプランのユーザー向けに提供される高度な分析・取引支援機能の
REST API エンドポイントを定義する。以下の機能を提供する:
  - AI シグナル生成（機械学習ベースのトレードシグナル）
  - マーケットブリーフ（市場概況レポート）
  - AI コーチング（個別トレードアドバイス）
  - バックテスト（シンプル＋Backtrader）
  - ウォークフォワードテスト（過学習防止のための時系列検証）
  - 高度リスク評価
  - ポートフォリオ概要
  - ブローカーアカウント管理
  - AI チャット（会話型アシスタント）
  - プロハブ（全分析の統合エンドポイント）
"""

from pydantic import BaseModel, Field

from fastapi import APIRouter, HTTPException, Query, Request

from src.ai.chat import chat, list_sessions
from src.ai.coaching import generate_coaching
from src.ai.market_brief import build_market_brief
from src.ai.signals import generate_ai_signals
from src.analysis.risk_advanced import assess_advanced_risk
from src.auth.context import get_tenant_id
from src.backtest.backtrader_runner import run_backtrader_backtest
from src.backtest.walk_forward import run_walk_forward
from src.broker.accounts import build_portfolio_overview, create_account, list_accounts
from src.analysis.signals import backtest_signals
from src.analysis.technical import compute_all_indicators
from src.data.market_data import get_ohlcv_data
from src.data.sample_data import SYMBOL_BASE_PRICES

# AI Pro 機能専用の APIRouter（タグで Swagger UI にグループ表示）
router = APIRouter(tags=["AI Pro"])


def _validate_symbol(symbol: str) -> str:
    """
    通貨ペアシンボルを正規化・検証する内部ユーティリティ。

    大文字に変換した後、サポートされているシンボル一覧（SYMBOL_BASE_PRICES）に
    存在するかどうかを確認する。存在しない場合は 404 エラーを返す。

    Args:
        symbol (str): 検証対象のシンボル文字列（例: "usdjpy", "EURUSD"）

    Returns:
        str: 大文字に正規化されたシンボル（例: "USDJPY"）

    Raises:
        HTTPException: シンボルがサポート外の場合は 404 を返す
    """
    # 入力値を大文字に統一（大文字・小文字の混在を許容）
    symbol = symbol.upper()
    # サポート対象シンボル一覧に存在しない場合は 404 エラー
    if symbol not in SYMBOL_BASE_PRICES:
        raise HTTPException(status_code=404, detail=f"Symbol {symbol} not found")
    return symbol


class ChatBody(BaseModel):
    """
    AI チャットリクエストのボディスキーマ。

    Attributes:
        message (str): ユーザーが送信するメッセージ（1〜4000文字）
        symbol (str): 分析対象の通貨ペア（デフォルト: USDJPY）
        session_id (int | None): 既存チャットセッションの継続時に使用する ID
    """
    message: str = Field(min_length=1, max_length=4000)
    symbol: str = "USDJPY"
    session_id: int | None = None


class AccountBody(BaseModel):
    """
    ブローカーアカウント作成リクエストのボディスキーマ。

    Attributes:
        name (str): アカウント名（1〜80文字）
        broker (str): ブローカー種別（デフォルト: "paper" = ペーパートレード）
        balance (float): 初期残高（最小 0、デフォルト 10000）
        is_default (bool): このアカウントをデフォルトとして設定するか
    """
    name: str = Field(min_length=1, max_length=80)
    broker: str = "paper"
    balance: float = Field(default=10000, ge=0)
    is_default: bool = False


def _tenant_user(request: Request) -> tuple[int | None, int | None]:
    """
    リクエストオブジェクトからテナント ID とユーザー ID を取得する内部ユーティリティ。

    ミドルウェアによって request.state.tenant にセットされたテナント情報を優先して使用し、
    存在しない場合はコンテキスト変数（get_tenant_id）からテナント ID を取得する。
    マルチテナント対応のために、すべての Pro エンドポイントでこの関数を経由する。

    Args:
        request (Request): FastAPI リクエストオブジェクト

    Returns:
        tuple[int | None, int | None]: (tenant_id, user_id) のタプル
    """
    # ミドルウェアがセットしたテナント情報を確認
    tenant = getattr(request.state, "tenant", None)
    if not tenant:
        # テナント情報がない場合はコンテキスト変数から取得（開発環境やシングルテナント環境用）
        return get_tenant_id(), None
    return tenant.tenant_id, tenant.user_id


@router.get("/api/pro/signals/{symbol}")
async def pro_signals(symbol: str, days: int = Query(default=200, ge=60, le=500)):
    """
    指定通貨ペアに対して AI（機械学習）ベースのトレードシグナルを生成する。

    テクニカル分析・ML予測・センチメント分析を統合した高度なシグナルを返す。
    シグナルには強度スコア・推奨方向・根拠サマリーが含まれる。

    Args:
        symbol (str): 通貨ペア（例: "USDJPY"）
        days (int): 分析対象の過去日数（60〜500日、デフォルト: 200）

    Returns:
        dict: AI シグナル情報（方向・信頼度・根拠・推奨エントリー価格など）
    """
    # シンボルを正規化・検証してから AI シグナル生成処理を呼び出す
    symbol = _validate_symbol(symbol)
    return await generate_ai_signals(symbol, days)


@router.get("/api/pro/market-brief/{symbol}")
async def pro_market_brief(symbol: str):
    """
    指定通貨ペアのマーケットブリーフ（市場概況レポート）を生成する。

    テクニカル指標・ニュースセンチメント・経済指標を統合した
    自然言語による市場サマリーを返す。OpenAI API が設定されている場合は
    GPT による高品質なレポートが生成される。

    Args:
        symbol (str): 通貨ペア（例: "EURUSD"）

    Returns:
        dict: マーケットブリーフ（テキストサマリー・主要シグナル・センチメントスコア）
    """
    # シンボル検証後にマーケットブリーフ構築関数を呼び出す
    symbol = _validate_symbol(symbol)
    return await build_market_brief(symbol)


@router.get("/api/pro/coaching/{symbol}")
async def pro_coaching(symbol: str, request: Request):
    """
    指定通貨ペアについてテナント固有のトレードコーチングアドバイスを生成する。

    ユーザーの取引履歴・現在のマーケット状況・リスク設定を考慮した
    パーソナライズされたコーチングを返す。テナント ID をもとに個別最適化される。

    Args:
        symbol (str): 通貨ペア（例: "GBPJPY"）
        request (Request): テナント情報取得のための FastAPI リクエスト

    Returns:
        dict: コーチングアドバイス（推奨アクション・学習ポイント・改善提案）
    """
    # シンボル検証後、テナント情報を取得してパーソナライズドコーチングを生成
    symbol = _validate_symbol(symbol)
    tenant_id, _ = _tenant_user(request)
    return await generate_coaching(symbol, tenant_id)


@router.get("/api/pro/backtest/{symbol}")
async def pro_backtest(symbol: str, days: int = Query(default=200, ge=90, le=500)):
    """
    指定通貨ペアに対してシンプルバックテストと Backtrader による高度バックテストを実行し、
    さらにウォークフォワード検証の結果もまとめて返す。

    3種類のバックテスト手法を組み合わせることで、過去データへの過学習を防ぎ、
    戦略の堅牢性を多角的に評価できる。

    Args:
        symbol (str): 通貨ペア（例: "USDJPY"）
        days (int): 分析対象の過去日数（90〜500日、デフォルト: 200）

    Returns:
        dict: バックテスト結果。以下のキーを含む:
            - symbol: 通貨ペア
            - source: データソース（OANDA / サンプルデータ）
            - simple: シンプルシグナルバックテスト結果
            - backtrader: Backtrader による詳細バックテスト結果
            - walk_forward: ウォークフォワード検証結果
    """
    sym = _validate_symbol(symbol)
    # OHLCV データを取得（OANDA が設定されていればリアルデータ、なければサンプルデータ）
    df, source = get_ohlcv_data(sym, days)
    # テクニカル指標をすべて計算（RSI・MACD・ボリンジャーバンドなど）
    result_df = compute_all_indicators(df)
    # シンプルなシグナルベースのバックテストを実行
    simple = backtest_signals(result_df)
    # Backtrader フレームワークによる本格的なバックテストを実行
    bt = run_backtrader_backtest(sym, days)
    # ウォークフォワードテスト（最低 300 日のデータを使用）
    wf = run_walk_forward(sym, max(days, 300))
    return {"symbol": sym, "source": source, "simple": simple, "backtrader": bt, "walk_forward": wf}


@router.get("/api/pro/walk-forward/{symbol}")
async def pro_walk_forward(symbol: str, days: int = Query(default=365, ge=180, le=500)):
    """
    指定通貨ペアに対してウォークフォワード検証を実行する。

    ウォークフォワード検証は、訓練期間と検証期間を時系列にスライドさせながら
    戦略のパフォーマンスを評価する手法で、過学習（カーブフィッティング）の
    検出に有効。通常のバックテスト単体より信頼性の高い評価が得られる。

    Args:
        symbol (str): 通貨ペア（例: "USDJPY"）
        days (int): 分析対象の過去日数（180〜500日、デフォルト: 365）

    Returns:
        dict: ウォークフォワード検証結果（期間別パフォーマンス・総合勝率など）
    """
    # シンボル検証後にウォークフォワードテストを直接実行
    return run_walk_forward(_validate_symbol(symbol), days)


@router.get("/api/pro/risk/{symbol}")
async def pro_risk(
    symbol: str,
    account_balance: float = Query(default=10000, ge=100),
    risk_percent: float = Query(default=1.0, ge=0.1, le=10),
    days: int = Query(default=200, ge=60, le=500),
):
    """
    指定通貨ペアに対して高度なリスク評価を実行する。

    ボラティリティ分析・Value at Risk（VaR）・最大ドローダウン・
    シャープレシオなどの高度なリスク指標を計算し、ポジションサイズの
    推奨値も返す。

    Args:
        symbol (str): 通貨ペア（例: "USDJPY"）
        account_balance (float): 口座残高（最小 100、デフォルト: 10000）
        risk_percent (float): 1トレードあたりのリスク率（0.1〜10%、デフォルト: 1.0）
        days (int): 分析対象の過去日数（60〜500日、デフォルト: 200）

    Returns:
        dict: リスク評価結果（VaR・ドローダウン・推奨ロットサイズ・リスク警告など）
    """
    # シンボル検証後に高度リスク評価関数を呼び出す
    return assess_advanced_risk(_validate_symbol(symbol), account_balance, risk_percent, days)


@router.get("/api/pro/portfolio")
async def pro_portfolio(request: Request):
    """
    テナントのポートフォリオ概要を取得する。

    テナントが保有する全ブローカーアカウントの残高・オープンポジション・
    損益サマリーを集計して返す。マルチアカウント・マルチブローカーに対応。

    Args:
        request (Request): テナント情報取得のための FastAPI リクエスト

    Returns:
        dict: ポートフォリオ概要（総資産・各アカウントの詳細・損益サマリー）
    """
    # テナント ID を取得してポートフォリオ概要を構築
    tenant_id, _ = _tenant_user(request)
    return build_portfolio_overview(tenant_id)


@router.get("/api/pro/accounts")
async def pro_accounts(request: Request):
    """
    テナントに紐づくブローカーアカウント一覧を取得する。

    Args:
        request (Request): テナント情報取得のための FastAPI リクエスト

    Returns:
        dict: アカウント一覧。"accounts" キーにリストを格納:
            - id: アカウント ID
            - name: アカウント名
            - broker: ブローカー種別（paper / oanda など）
            - balance: 残高
            - is_default: デフォルトアカウントフラグ
    """
    # テナント ID を取得してアカウント一覧を取得
    tenant_id, _ = _tenant_user(request)
    return {"accounts": list_accounts(tenant_id)}


@router.post("/api/pro/accounts")
async def pro_create_account(body: AccountBody, request: Request):
    """
    テナントに新しいブローカーアカウントを作成する。

    ペーパートレードアカウントや実口座を登録できる。
    is_default=True を設定すると、他のエンドポイントでアカウントを
    指定しない場合にこのアカウントが使用される。

    Args:
        body (AccountBody): アカウント作成パラメータ（名前・ブローカー・残高・デフォルト設定）
        request (Request): テナント情報取得のための FastAPI リクエスト

    Returns:
        dict: 作成されたアカウント情報
    """
    # テナント ID を取得してアカウントを作成
    tenant_id, _ = _tenant_user(request)
    return create_account(tenant_id, body.name, body.broker, body.balance, body.is_default)


@router.post("/api/pro/chat")
async def pro_chat(body: ChatBody, request: Request):
    """
    AI チャットアシスタントにメッセージを送信し、回答を取得する。

    OpenAI GPT を使用した会話型 FX トレードアシスタント。
    セッション ID を指定することで過去の会話を継続できる（コンテキスト保持）。
    テナント・ユーザー別に会話履歴が管理される。

    Args:
        body (ChatBody): チャットリクエスト（メッセージ・シンボル・セッション ID）
        request (Request): テナント・ユーザー情報取得のための FastAPI リクエスト

    Returns:
        dict: AI の返答、セッション ID、関連するシグナル情報など
    """
    # シンボルを検証・正規化
    symbol = _validate_symbol(body.symbol)
    # テナント ID とユーザー ID を取得（会話履歴の分離に使用）
    tenant_id, user_id = _tenant_user(request)
    return await chat(body.message, symbol, body.session_id, tenant_id, user_id)


@router.get("/api/pro/chat/sessions")
async def pro_chat_sessions(request: Request):
    """
    テナントの AI チャットセッション一覧を取得する。

    過去の会話セッションを一覧表示し、再開するためのセッション ID を提供する。
    セッションには最初のメッセージ・作成日時・最終更新日時が含まれる。

    Args:
        request (Request): テナント情報取得のための FastAPI リクエスト

    Returns:
        dict: セッション一覧。"sessions" キーにリストを格納:
            - id: セッション ID
            - symbol: 関連通貨ペア
            - created_at: 作成日時
            - last_message_at: 最終メッセージ日時
    """
    # テナント ID を取得してセッション一覧を返す
    tenant_id, _ = _tenant_user(request)
    return {"sessions": list_sessions(tenant_id)}


@router.get("/api/pro/hub/{symbol}")
async def pro_hub(symbol: str, request: Request, days: int = Query(default=200)):
    """
    AI Pro ハブ: 指定通貨ペアの全分析を一度に取得する統合エンドポイント。

    AI シグナル・マーケットブリーフ・リスク評価・ポートフォリオ概要を
    並列で取得して一括返却する。ダッシュボードの初期ロードに使用され、
    複数の個別リクエストを 1 回にまとめることでネットワーク往復を削減する。

    Args:
        symbol (str): 通貨ペア（例: "USDJPY"）
        request (Request): テナント情報取得のための FastAPI リクエスト
        days (int): 分析対象の過去日数（デフォルト: 200）

    Returns:
        dict: 統合分析結果。以下のキーを含む:
            - symbol: 通貨ペア
            - signals: AI シグナル
            - market_brief: マーケットブリーフ
            - risk: リスク評価
            - portfolio: ポートフォリオ概要
    """
    sym = _validate_symbol(symbol)
    tenant_id, _ = _tenant_user(request)
    # AI シグナルとマーケットブリーフを非同期で取得（I/O バウンド処理のため await）
    signals = await generate_ai_signals(sym, days)
    brief = await build_market_brief(sym)
    # リスク評価は同期関数（CPU バウンド処理）
    risk = assess_advanced_risk(sym)
    # テナントのポートフォリオ概要を取得
    portfolio = build_portfolio_overview(tenant_id)
    return {
        "symbol": sym,
        "signals": signals,
        "market_brief": brief,
        "risk": risk,
        "portfolio": portfolio,
    }
