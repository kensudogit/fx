"""
自動取引 REST API モジュール

このモジュールは、自動取引（オートトレード）機能に関する REST API エンドポイントを定義する。
以下の機能を提供する:
  - 取引設定の取得・更新（通貨ペア・リスク率・戦略プリセットなど）
  - 戦略プリセットの一覧・適用
  - 自動銘柄選択（AutoSelect）
  - 戦略シミュレーション（過去データによる模擬トレード）
  - パフォーマンス分析（累積損益・勝率・ドローダウンなど）
  - オープンポジション管理
  - 手動トレードサイクル実行（個別銘柄 / 全銘柄）
  - スケジューラー管理（自動定期実行の開始・停止）

マルチテナント対応: すべてのエンドポイントがテナント ID により
データを分離して管理する。
"""

from pydantic import BaseModel, Field

from fastapi import APIRouter, HTTPException, Query, Request

from src.autotrade.analytics import build_performance
from src.autotrade.autoselect import autoselect
from src.autotrade.engine import evaluate_symbol, run_cycle
from src.autotrade.models import DEFAULT_CONFIG, get_config, list_runs, save_config
from src.autotrade.positions import list_open_positions
from src.autotrade.presets import apply_preset, list_presets
from src.autotrade.scheduler import scheduler_status, set_tenant_scheduler_enabled, start_scheduler, stop_scheduler
from src.auth.context import get_tenant_id
from src.data.sample_data import SYMBOL_BASE_PRICES

# 自動取引機能専用の APIRouter（タグで Swagger UI にグループ表示）
router = APIRouter(tags=["Auto Trade"])


class AutoTradeConfigBody(BaseModel):
    """
    自動取引設定の更新リクエストボディスキーマ。

    全フィールドは省略可能（Optional）で、指定したフィールドのみ更新される（部分更新）。
    バリデーションにより、不正な値（範囲外・不正パターン）は API レベルで拒否される。

    Attributes:
        enabled (bool | None): 自動取引の有効/無効
        symbols (list[str] | None): 対象通貨ペアリスト
        mode (str | None): 取引モード（"paper" = ペーパー / "live" = 実取引）
        strategy_preset (str | None): 適用する戦略プリセット ID
        min_confidence (int | None): シグナルの最低信頼度（30〜95）
        risk_percent (float | None): 1トレードあたりのリスク率（0.1〜10%）
        account_balance (float | None): 運用口座残高（最小 100）
        sources (list[str] | None): シグナルソース（例: ["technical", "ml", "news"]）
        require_mtf_alignment (bool | None): マルチタイムフレーム整合性を必須とするか
        event_blackout_hours (int | None): 経済指標発表前後の取引禁止時間（0〜48時間）
        max_daily_trades (int | None): 1日の最大取引回数（1〜20）
        cooldown_minutes (int | None): 連続取引のクールダウン時間（0〜1440分）
        auto_execute_tradingview (bool | None): TradingView シグナルを自動実行するか
        auto_exit_on_reverse (bool | None): 逆シグナル時に自動決済するか
        use_stop_loss (bool | None): ストップロスを使用するか
        use_take_profit (bool | None): テイクプロフィットを使用するか
        risk_reward (float | None): リスクリワード比（0.5〜5）
        max_lots (float | None): 最大ロットサイズ（0.01〜100）
        min_lots (float | None): 最小ロットサイズ（0.01〜10）
        min_units (int | None): 最小取引単位（1000〜1,000,000）
        scheduler_interval_minutes (int | None): スケジューラー実行間隔（1〜1440分）
        scheduler_enabled (bool | None): スケジューラーの有効/無効
        allow_add_to_position (bool | None): 同方向ポジションへの追加エントリーを許可するか
    """
    enabled: bool | None = None
    symbols: list[str] | None = None
    mode: str | None = Field(default=None, pattern="^(paper|live)$")
    strategy_preset: str | None = None
    min_confidence: int | None = Field(default=None, ge=30, le=95)
    risk_percent: float | None = Field(default=None, ge=0.1, le=10)
    account_balance: float | None = Field(default=None, ge=100)
    sources: list[str] | None = None
    require_mtf_alignment: bool | None = None
    event_blackout_hours: int | None = Field(default=None, ge=0, le=48)
    max_daily_trades: int | None = Field(default=None, ge=1, le=20)
    cooldown_minutes: int | None = Field(default=None, ge=0, le=1440)
    auto_execute_tradingview: bool | None = None
    auto_exit_on_reverse: bool | None = None
    use_stop_loss: bool | None = None
    use_take_profit: bool | None = None
    risk_reward: float | None = Field(default=None, ge=0.5, le=5)
    max_lots: float | None = Field(default=None, ge=0.01, le=100)
    min_lots: float | None = Field(default=None, ge=0.01, le=10)
    min_units: int | None = Field(default=None, ge=1000, le=1_000_000)
    scheduler_interval_minutes: int | None = Field(default=None, ge=1, le=1440)
    scheduler_enabled: bool | None = None
    allow_add_to_position: bool | None = None


class AutoSelectBody(BaseModel):
    """
    自動銘柄選択リクエストボディスキーマ。

    ユーザーの投資スタイル・資金規模・リスク許容度をもとに、
    最適な通貨ペアと戦略設定を自動選択するためのパラメータ。

    Attributes:
        capital (str): 資金規模（"small" / "medium" / "large"）
        horizon (str): 投資期間（"short" / "medium" / "long"）
        risk_appetite (str): リスク許容度（"low" / "medium" / "high"）
        style (str): 取引スタイル（"auto" / "range" / "trend"）
        preferred_symbols (list[str] | None): 優先的に検討する通貨ペアリスト
        apply (bool): 選択結果を即座に設定に適用するか（True の場合は save_config も実行）
    """
    capital: str = Field(default="medium", pattern="^(small|medium|large)$")
    horizon: str = Field(default="medium", pattern="^(short|medium|long)$")
    risk_appetite: str = Field(default="medium", pattern="^(low|medium|high)$")
    style: str = Field(default="auto", pattern="^(auto|range|trend)$")
    preferred_symbols: list[str] | None = None
    apply: bool = False


class ApplyPresetBody(BaseModel):
    """
    戦略プリセット適用リクエストボディスキーマ。

    Attributes:
        preset_id (str): 適用するプリセットの識別子
    """
    preset_id: str


def _validate_symbol(symbol: str) -> str:
    """
    通貨ペアシンボルを正規化・検証する内部ユーティリティ。

    Args:
        symbol (str): 検証対象のシンボル文字列（例: "usdjpy"）

    Returns:
        str: 大文字に正規化されたシンボル（例: "USDJPY"）

    Raises:
        HTTPException: シンボルがサポート外の場合は 404 を返す
    """
    # 入力を大文字に正規化
    symbol = symbol.upper()
    # サポート対象シンボルに含まれない場合は 404 エラー
    if symbol not in SYMBOL_BASE_PRICES:
        raise HTTPException(status_code=404, detail=f"Symbol {symbol} not found")
    return symbol


def _tenant(request: Request) -> int | None:
    """
    リクエストオブジェクトからテナント ID を取得する内部ユーティリティ。

    ミドルウェアによって request.state.tenant にセットされたテナント情報を優先して使用し、
    存在しない場合はコンテキスト変数（get_tenant_id）からテナント ID を取得する。

    Args:
        request (Request): FastAPI リクエストオブジェクト

    Returns:
        int | None: テナント ID（未認証環境では None）
    """
    # ミドルウェアがセットしたテナント情報を確認
    tenant = getattr(request.state, "tenant", None)
    return tenant.tenant_id if tenant else get_tenant_id()


@router.get("/api/autotrade/presets")
async def autotrade_presets():
    """
    利用可能な戦略プリセット一覧を取得する。

    プリセットは事前定義された取引設定のテンプレートで、
    初心者や特定スタイルのトレーダーがすぐに利用できる設定を提供する。
    （例: バランス型・積極型・保守型・スキャルピング型など）

    Returns:
        dict: プリセット一覧。"presets" キーにリストを格納:
            - id: プリセット識別子
            - name: プリセット名
            - description: プリセットの説明
            - config: プリセットが設定する各パラメータ値
    """
    return {"presets": list_presets()}


@router.post("/api/autotrade/presets/apply")
async def autotrade_apply_preset(body: ApplyPresetBody, request: Request):
    """
    指定したプリセットをテナントの自動取引設定に適用・保存する。

    現在の設定にプリセット値をマージして上書き保存する。
    プリセット ID が不正な場合は 400 エラーを返す。

    Args:
        body (ApplyPresetBody): 適用するプリセットの ID
        request (Request): テナント情報取得のための FastAPI リクエスト

    Returns:
        dict: 保存後の設定と適用したプリセット ID

    Raises:
        HTTPException: 不正なプリセット ID の場合は 400 を返す
    """
    # テナント ID を取得
    tid = _tenant(request)
    try:
        # 現在の設定とプリセットをマージ（プリセット優先）
        merged = apply_preset(body.preset_id, get_config(tid))
    except ValueError as e:
        # 不正なプリセット ID は 400 Bad Request で返す
        raise HTTPException(status_code=400, detail=str(e))
    # マージした設定を永続化
    saved = save_config(merged, tid)
    return {"config": saved, "preset_id": body.preset_id}


@router.post("/api/autotrade/autoselect")
async def autotrade_autoselect(body: AutoSelectBody, request: Request):
    """
    ユーザーの投資スタイルに基づいて最適な通貨ペアと設定を自動選択する。

    資金規模・投資期間・リスク許容度・取引スタイルをもとに、
    機械学習とルールベースのロジックで最適な通貨ペアと戦略設定を提案する。
    apply=True の場合は提案内容を即座に設定に保存する。

    Args:
        body (AutoSelectBody): 自動選択パラメータ
        request (Request): テナント情報取得のための FastAPI リクエスト

    Returns:
        dict: 自動選択結果（推奨通貨ペア・推奨設定・選択理由）
            - apply=True の場合は保存後の "config" キーも含む
    """
    tid = _tenant(request)
    # 投資スタイルパラメータをもとに最適設定を算出
    result = autoselect(
        body.capital, body.horizon, body.risk_appetite, body.style, body.preferred_symbols
    )
    if body.apply:
        # apply フラグが True の場合は選択された設定を永続化する
        result["config"] = save_config(result["config"], tid)
    return result


@router.get("/api/autotrade/simulate/{symbol}")
async def autotrade_simulate(
    symbol: str,
    days: int = Query(default=365, ge=90, le=500),
    account_balance: float = Query(default=10000, ge=100),
    preset_id: str = Query(default="balanced"),
    risk_percent: float = Query(default=1.0, ge=0.1, le=10),
):
    """
    指定通貨ペアに対して戦略シミュレーションを実行する。

    過去の OHLCV データを使用して、指定したプリセット設定で
    自動取引エンジンを模擬実行し、損益・勝率・ドローダウンなどを計算する。
    実際の注文は発生しないため、設定の評価・比較に安全に使用できる。

    Args:
        symbol (str): 通貨ペア（例: "USDJPY"）
        days (int): シミュレーション期間の日数（90〜500日、デフォルト: 365）
        account_balance (float): 仮想口座残高（最小 100、デフォルト: 10000）
        preset_id (str): 使用する戦略プリセット ID（デフォルト: "balanced"）
        risk_percent (float): 1トレードあたりのリスク率（0.1〜10%、デフォルト: 1.0）

    Returns:
        dict: シミュレーション結果（総トレード数・勝率・最終残高・最大ドローダウンなど）
    """
    sym = _validate_symbol(symbol)
    # 検証済みシンボルと設定でシミュレーション実行
    return simulate_strategy(sym, days, account_balance, preset_id, risk_percent)


@router.get("/api/autotrade/performance")
async def autotrade_performance(request: Request, limit: int = Query(default=100, le=200)):
    """
    テナントの自動取引パフォーマンス分析を取得する。

    過去の取引履歴をもとに、累積損益・勝率・ドローダウン・
    シャープレシオ・通貨ペア別パフォーマンスなどを集計する。

    Args:
        request (Request): テナント情報取得のための FastAPI リクエスト
        limit (int): 分析対象の最大取引件数（デフォルト: 100、最大: 200）

    Returns:
        dict: パフォーマンス分析結果（累積損益・勝率・最大ドローダウン・通貨ペア別集計など）
    """
    tid = _tenant(request)
    # テナント ID と件数制限を指定してパフォーマンスデータを構築
    return build_performance(tid, limit)


@router.get("/api/autotrade/positions")
async def autotrade_positions(request: Request, symbol: str | None = None):
    """
    テナントのオープンポジション一覧を取得する。

    現在保有中の全ポジション（または特定通貨ペアのポジション）を返す。
    symbol を指定した場合はその通貨ペアのみフィルタリングする。

    Args:
        request (Request): テナント情報取得のための FastAPI リクエスト
        symbol (str | None): フィルタリングする通貨ペア（省略時は全通貨ペア）

    Returns:
        dict: オープンポジション一覧。"positions" キーにリストを格納
    """
    tid = _tenant(request)
    if symbol:
        # シンボルが指定された場合は先に検証してから使用
        _validate_symbol(symbol)
    return {"positions": list_open_positions(tid, symbol)}


@router.get("/api/autotrade/config")
async def autotrade_get_config(request: Request):
    """
    テナントの現在の自動取引設定とデフォルト設定を取得する。

    現在保存されている設定値と、システムのデフォルト設定値を
    並べて返すことで、フロントエンドで設定変更 UI を構築しやすくする。

    Args:
        request (Request): テナント情報取得のための FastAPI リクエスト

    Returns:
        dict:
            - config: テナントの現在の設定値
            - defaults: システムデフォルト設定値（DEFAULT_CONFIG）
    """
    tid = _tenant(request)
    cfg = get_config(tid)
    return {"config": cfg, "defaults": DEFAULT_CONFIG}


@router.put("/api/autotrade/config")
async def autotrade_update_config(body: AutoTradeConfigBody, request: Request):
    """
    テナントの自動取引設定を部分更新する。

    リクエストボディで指定されたフィールドのみを現在の設定にマージして保存する。
    None 値のフィールドは無視されるため、変更したいフィールドのみ送信すれば良い。
    シンボルリストが含まれる場合は、各シンボルの有効性を事前に検証する。

    Args:
        body (AutoTradeConfigBody): 更新する設定フィールド（未指定フィールドは変更されない）
        request (Request): テナント情報取得のための FastAPI リクエスト

    Returns:
        dict: 保存後の設定値全体（"config" キー）
    """
    tid = _tenant(request)
    # 現在の設定を取得
    current = get_config(tid)
    # None 値を除外してリクエストフィールドのみ抽出（部分更新）
    updates = body.model_dump(exclude_none=True)
    if updates.get("symbols"):
        # シンボルリストが含まれる場合、各シンボルが有効かどうかを検証
        for s in updates["symbols"]:
            _validate_symbol(s)
    # 現在の設定に変更内容をマージして保存
    merged = save_config({**current, **updates}, tid)
    return {"config": merged}


@router.get("/api/autotrade/status")
async def autotrade_status(request: Request):
    """
    自動取引の現在の総合ステータスを取得する。

    設定・スケジューラー状態・直近の実行履歴・パフォーマンス概要・
    オープンポジションをまとめて返す、ダッシュボード向けの統合エンドポイント。
    フロントエンドはこのエンドポイント 1 つで画面の主要情報を取得できる。

    Args:
        request (Request): テナント情報取得のための FastAPI リクエスト

    Returns:
        dict: 総合ステータス。以下のキーを含む:
            - config: 現在の自動取引設定
            - scheduler: スケジューラーの稼働状態
            - recent_runs: 直近 5 件の実行履歴
            - performance: パフォーマンス概要（直近 50 件）
            - open_positions: オープンポジション一覧
    """
    tid = _tenant(request)
    # 現在の設定を取得
    cfg = get_config(tid)
    # スケジューラーの稼働状態を確認
    status = scheduler_status(tid)
    # 直近 5 件の実行履歴を取得
    recent = list_runs(5, tid)
    # パフォーマンス概要（直近 50 件）を計算
    performance = build_performance(tid, 50)
    return {
        "config": cfg,
        "scheduler": status,
        "recent_runs": recent,
        "performance": performance,
        "open_positions": list_open_positions(tid),
    }


@router.get("/api/autotrade/runs")
async def autotrade_runs(
    request: Request,
    symbol: str | None = None,
    limit: int = Query(default=30, le=100),
):
    """
    自動取引の実行履歴を取得する。

    スケジューラーや手動実行によるトレードサイクルの履歴を返す。
    symbol でフィルタリングすることで特定通貨ペアの履歴のみ取得できる。

    Args:
        request (Request): テナント情報取得のための FastAPI リクエスト
        symbol (str | None): フィルタリングする通貨ペア（省略時は全通貨ペア）
        limit (int): 取得件数の上限（デフォルト: 30、最大: 100）

    Returns:
        dict: 実行履歴一覧。"runs" キーにリストを格納:
            - id: 実行 ID
            - symbol: 通貨ペア
            - executed_at: 実行日時
            - trigger: 実行トリガー（scheduler / manual）
            - result: 実行結果（取引実行 / スキップ / エラー）
    """
    tid = _tenant(request)
    if symbol:
        # シンボルが指定された場合は検証してからフィルタリングに使用
        _validate_symbol(symbol)
    return {"runs": list_runs(limit, tid, symbol)}


@router.post("/api/autotrade/evaluate/{symbol}")
async def autotrade_evaluate(symbol: str, request: Request):
    """
    指定通貨ペアに対してトレード評価をドライラン（模擬実行）する。

    実際に注文は発生させずに、シグナル評価・リスクチェック・
    注文計算のロジックを実行し、どのような判断が下されるかを確認できる。
    設定変更後の動作確認や、特定シンボルの現在のシグナル状態確認に有用。

    Args:
        symbol (str): 評価対象の通貨ペア（例: "USDJPY"）
        request (Request): テナント情報取得のための FastAPI リクエスト

    Returns:
        dict: 評価結果（シグナル・信頼度・リスク計算・注文内容など、実際の注文は発生しない）
    """
    sym = _validate_symbol(symbol)
    tid = _tenant(request)
    # dry_run=True で実際の注文を発生させずに評価のみ実行
    result = await evaluate_symbol(sym, tid, dry_run=True)
    return result


@router.post("/api/autotrade/run/{symbol}")
async def autotrade_run_symbol(symbol: str, request: Request):
    """
    指定通貨ペアに対して自動取引を手動でトリガーする（実取引あり）。

    シグナル評価後に条件を満たした場合は実際に注文が発生する。
    自動取引が設定で無効化されている場合は 400 エラーを返す。
    実本番取引に直結するため、enabled フラグを必ず確認する。

    Args:
        symbol (str): 取引対象の通貨ペア（例: "USDJPY"）
        request (Request): テナント情報取得のための FastAPI リクエスト

    Returns:
        dict: 実行結果（取引実行内容・注文 ID・シグナル詳細など）

    Raises:
        HTTPException: 自動取引が無効の場合は 400 を返す
    """
    sym = _validate_symbol(symbol)
    tid = _tenant(request)
    cfg = get_config(tid)
    # 自動取引が有効化されていない場合は取引を拒否（誤操作防止）
    if not cfg.get("enabled"):
        raise HTTPException(status_code=400, detail="自動取引が無効です。設定で有効化してください。")
    # dry_run=False で実際の注文を発生させる
    result = await evaluate_symbol(sym, tid, dry_run=False)
    return result


@router.post("/api/autotrade/run")
async def autotrade_run_all(request: Request):
    """
    設定されている全通貨ペアに対して自動取引サイクルを手動で実行する。

    テナントの設定で有効化されている全シンボルを対象に、シグナル評価・
    リスクチェック・注文実行を順次処理する。スケジューラーとは独立して
    手動でサイクルを強制実行したい場合に使用する。

    Args:
        request (Request): テナント情報取得のための FastAPI リクエスト

    Returns:
        dict:
            - results: 各通貨ペアの実行結果リスト
            - count: 処理した通貨ペア数

    Raises:
        HTTPException: 自動取引が無効の場合は 400 を返す
    """
    tid = _tenant(request)
    cfg = get_config(tid)
    # 自動取引が有効化されていない場合はサイクル実行を拒否
    if not cfg.get("enabled"):
        raise HTTPException(status_code=400, detail="自動取引が無効です。設定で有効化してください。")
    # "manual" トリガーで全シンボルのトレードサイクルを実行
    results = await run_cycle(tid, trigger="manual")
    return {"results": results, "count": len(results)}


@router.post("/api/autotrade/scheduler/start")
async def autotrade_scheduler_start(request: Request):
    """
    テナントのスケジューラーを有効化し、グローバルスケジューラーを起動する。

    スケジューラーは設定された間隔（scheduler_interval_minutes）で
    自動的にトレードサイクルを実行する。テナントレベルの有効フラグを
    True にセットした後、グローバルスケジューラーを起動する。

    Args:
        request (Request): テナント情報取得のための FastAPI リクエスト

    Returns:
        dict:
            - ok: 処理成功フラグ（True）
            - scheduler: スケジューラーの現在の状態
    """
    tid = _tenant(request)
    # テナントのスケジューラー有効フラグを True に設定
    set_tenant_scheduler_enabled(tid, True)
    # グローバルスケジューラープロセスを起動（既に起動中の場合は無視）
    start_scheduler()
    return {"ok": True, "scheduler": scheduler_status(tid)}


@router.post("/api/autotrade/scheduler/stop")
async def autotrade_scheduler_stop(request: Request):
    """
    テナントのスケジューラーを無効化する。

    このテナントのスケジューラー有効フラグを False にセットすることで、
    次の実行サイクルからこのテナントの処理をスキップするようになる。
    グローバルスケジューラープロセス自体は停止しない（他のテナントに影響しないため）。

    Args:
        request (Request): テナント情報取得のための FastAPI リクエスト

    Returns:
        dict:
            - ok: 処理成功フラグ（True）
            - scheduler: スケジューラーの現在の状態（enabled=False になっているはず）
    """
    tid = _tenant(request)
    # テナントのスケジューラー有効フラグを False に設定
    # グローバルスケジューラーは停止しない（他テナントへの影響を防ぐため）
    set_tenant_scheduler_enabled(tid, False)
    return {"ok": True, "scheduler": scheduler_status(tid)}
