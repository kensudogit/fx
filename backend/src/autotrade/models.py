"""
自動取引設定・実行ログの永続化モジュール

SQLAlchemy ORM を使用して、以下の 2 テーブルをデータベースに管理する:
    - autotrade_configs : テナントごとの自動取引設定（JSON 形式で保存）
    - autotrade_runs    : 評価・注文の実行ログ（シグナル・判定・約定情報を記録）

データベース接続に失敗した場合はメモリキャッシュ（_memory_configs / _memory_runs）に
フォールバックするため、DB 障害時でも機能が停止しない設計になっている。
"""

import json
import logging
from datetime import datetime, timezone

from sqlalchemy import Boolean, Column, DateTime, Integer, Numeric, String, Text, desc, select

from src.db.database import Base, SessionLocal, engine

logger = logging.getLogger(__name__)

# デフォルト設定: テナントに設定が保存されていない場合に使用するフォールバック値
# すべての設定項目はここで定義され、merge_config によって実際の設定にマージされる
DEFAULT_CONFIG = {
    "enabled": False,                   # 自動取引を有効化するフラグ（デフォルトは無効）
    "symbols": ["USDJPY"],              # 取引対象の通貨ペアリスト
    "mode": "paper",                    # 取引モード: "paper"（ペーパートレード）/ "live"（本番）
    "strategy_preset": "balanced",      # ストラテジープリセット ID
    "min_confidence": 65,               # エントリーに必要な最低信頼度（%）
    "risk_percent": 1.0,               # 1 トレードあたりのリスク（口座残高に対する%）
    "account_balance": 10000,          # 運用口座残高（USD、ポジションサイジングに使用）
    "sources": ["ai", "technical", "intelligence", "mtf"],  # 使用するシグナルソース
    "require_mtf_alignment": True,     # MTF アライメント一致を必須にするか
    "event_blackout_hours": 4,         # 高影響経済指標の前後何時間を取引禁止にするか
    "max_daily_trades": 3,             # 1 日あたりの最大取引回数（日次リスク管理）
    "cooldown_minutes": 60,            # 前回取引から次のエントリーまでの最低待機時間（分）
    "auto_execute_tradingview": True,  # TradingView Webhook シグナルを自動実行するか
    "auto_exit_on_reverse": True,      # 逆シグナル発生時にポジションを自動決済するか
    "use_stop_loss": True,             # ストップロスを設定するか
    "use_take_profit": True,           # テイクプロフィットを設定するか
    "risk_reward": 2.0,               # RR 比（TP 距離 = SL 距離 × risk_reward）
    "max_lots": 1.0,                   # 1 注文あたりの最大ロット数
    "min_lots": 0.01,                  # 1 注文あたりの最小ロット数
    "min_units": 1000,                 # 1 注文あたりの最小ユニット数
    "scheduler_interval_minutes": 15, # スケジューラの実行間隔（分）
    "scheduler_enabled": True,        # スケジューラを有効にするか
    "allow_add_to_position": False,   # 同一通貨ペアへの追加エントリー（ナンピン）を許可するか
}

# DB 接続不可時のメモリフォールバック（テナント ID → 設定辞書のマッピング）
_memory_configs: dict[int, dict] = {}

# DB 接続不可時のメモリフォールバック（実行ログのリスト、新しい順）
_memory_runs: list[dict] = []


class AutoTradeConfig(Base):
    """
    テナントごとの自動取引設定を永続化する ORM モデル。

    各テナントは 1 行のみ持つ（tenant_id に UNIQUE 制約）。
    設定内容は JSON 文字列として config_json カラムに格納し、
    読み取り時に merge_config で DEFAULT_CONFIG とマージして返す。

    Attributes:
        id:          主キー（自動採番）
        tenant_id:   テナント識別子。NULL の場合は非マルチテナント環境のグローバル設定。
                     UNIQUE 制約によりテナントごとに 1 行を保証。
        config_json: 設定を JSON エンコードした文字列（ensure_ascii=False）
        updated_at:  最終更新日時（タイムゾーン付き）
    """

    __tablename__ = "autotrade_configs"

    # 主キー: 自動採番の整数 ID
    id = Column(Integer, primary_key=True, autoincrement=True)
    # テナント識別子: NULL 許容（非マルチテナント環境では NULL）、UNIQUE 制約あり
    tenant_id = Column(Integer, nullable=True, unique=True)
    # 設定 JSON: DEFAULT_CONFIG をベースに上書きした設定を JSON 文字列で保存
    config_json = Column(Text, nullable=False)
    # 最終更新日時: save_config 呼び出し時に現在の UTC 時刻を設定
    updated_at = Column(DateTime(timezone=True), nullable=False)


class AutoTradeRun(Base):
    """
    自動取引の評価・実行ログを永続化する ORM モデル。

    evaluate_symbol / execute_order / run_cycle が実行されるたびに 1 行追加される。
    decision フィールドで結果を分類し、シグナルスナップショットを JSON で記録する。

    Attributes:
        id:              主キー（自動採番）
        tenant_id:       テナント識別子（NULL は非マルチテナント環境）
        symbol:          通貨ペアシンボル（例: "USDJPY"）、最大 10 文字
        action:          シグナルアクション（"buy" / "sell" / "hold" / "close"）
        decision:        最終判定結果:
                             "executed" = 注文約定済み
                             "blocked"  = リスクガード等でブロック
                             "skipped"  = hold シグナルのためスキップ
                             "ready"    = dry_run で実行可能判定
                             "failed"   = 注文エラー
                             "disabled" = 自動取引が無効
        confidence:      シグナル統合後の信頼度（0.00〜100.00）
        units:           注文ユニット数（未実行の場合は NULL）
        fill_price:      約定価格（精度: 整数部 12 桁 + 小数部 6 桁、未約定は NULL）
        order_id:        ブローカーの注文 ID（未実行は NULL）
        trigger:         実行トリガー（"scheduler" / "manual" / "tradingview"）
        reason:          判定理由の日本語テキスト（ブロック理由・約定価格等）
        signal_snapshot: シグナルスナップショットの JSON 文字列
                         （fused / breakdown / guard_reason / order_plan / price を含む）
        created_at:      レコード作成日時（タイムゾーン付き UTC）
    """

    __tablename__ = "autotrade_runs"

    # 主キー: 自動採番の整数 ID
    id = Column(Integer, primary_key=True, autoincrement=True)
    # テナント識別子: NULL 許容（複数テナントのログを同一テーブルで管理）
    tenant_id = Column(Integer, nullable=True)
    # 通貨ペアシンボル: 大文字で格納（例: "USDJPY"）、最大 10 文字
    symbol = Column(String(10), nullable=False)
    # シグナルアクション: "buy" / "sell" / "hold" / "close" のいずれか
    action = Column(String(10), nullable=False)
    # 最終判定結果: executed / blocked / skipped / ready / failed / disabled
    decision = Column(String(20), nullable=False)
    # シグナル信頼度: 小数点 2 桁（例: 75.50）
    confidence = Column(Numeric(5, 2))
    # 注文ユニット数: 約定した場合のみ設定（NULL = 未約定）
    units = Column(Integer)
    # 約定価格: 整数部 12 桁 + 小数部 6 桁の高精度数値（NULL = 未約定）
    fill_price = Column(Numeric(18, 6))
    # ブローカー注文 ID: place_market_order が返す ID（NULL = 未約定）
    order_id = Column(Integer)
    # 実行トリガー: "scheduler"（定期実行）/ "manual"（手動）/ "tradingview"（Webhook）
    trigger = Column(String(30), default="scheduler")
    # 判定理由: ブロック理由や約定の詳細情報を日本語テキストで記録
    reason = Column(Text)
    # シグナルスナップショット: 評価時の全シグナル情報を JSON 文字列で保存
    signal_snapshot = Column(Text)
    # レコード作成日時: save_run 呼び出し時の UTC 現在時刻
    created_at = Column(DateTime(timezone=True), nullable=False)


def _ensure_tables():
    """
    autotrade_configs / autotrade_runs テーブルが存在しない場合に作成する。

    checkfirst=True により既存テーブルへの影響はなく、冪等に実行できる。
    DB 接続エラーは WARNING レベルでログに記録して処理を継続する。
    """
    try:
        AutoTradeConfig.__table__.create(engine, checkfirst=True)
        AutoTradeRun.__table__.create(engine, checkfirst=True)
    except Exception as e:
        logger.warning("autotrade tables: %s", e)


def merge_config(raw: dict | None) -> dict:
    """
    生の設定辞書と DEFAULT_CONFIG をマージして完全な設定辞書を返す。

    raw の値が DEFAULT_CONFIG の値を上書きする（raw が優先）。
    symbols が空またはなしの場合は ["USDJPY"] をデフォルトとして設定する。

    Args:
        raw: テナント固有の設定辞書。None の場合は DEFAULT_CONFIG のみを使用。

    Returns:
        DEFAULT_CONFIG と raw をマージした完全な設定辞書
    """
    merged = {**DEFAULT_CONFIG, **(raw or {})}
    # symbols が空リストや None の場合は USDJPY をデフォルトとして設定
    if not merged.get("symbols"):
        merged["symbols"] = ["USDJPY"]
    return merged


def get_config(tenant_id: int | None = None) -> dict:
    """
    テナントの自動取引設定を取得する。

    取得優先順:
        1. データベースの autotrade_configs テーブル（tenant_id で検索）
        2. メモリキャッシュ _memory_configs（DB 接続失敗時のフォールバック）
        3. DEFAULT_CONFIG のデフォルト値のみ（設定が存在しない場合）

    Args:
        tenant_id: テナント識別子。None の場合は設定を検索せず DEFAULT_CONFIG を返す。

    Returns:
        merge_config で DEFAULT_CONFIG とマージした完全な設定辞書
    """
    _ensure_tables()
    db = SessionLocal()
    try:
        if tenant_id is not None:
            row = db.execute(
                select(AutoTradeConfig).where(AutoTradeConfig.tenant_id == tenant_id)
            ).scalar_one_or_none()
            if row:
                return merge_config(json.loads(row.config_json))
    except Exception as e:
        logger.warning("get_config: %s", e)
    finally:
        db.close()
    # DB から取得できなかった場合はメモリキャッシュを確認
    if tenant_id is not None and tenant_id in _memory_configs:
        return merge_config(_memory_configs[tenant_id])
    # どちらにもない場合はデフォルト設定を返す
    return merge_config(None)


def save_config(config: dict, tenant_id: int | None = None) -> dict:
    """
    テナントの自動取引設定を保存する（UPSERT）。

    DB に同一 tenant_id の行が存在する場合は更新、存在しない場合は新規追加する。
    DB 保存に失敗した場合はメモリキャッシュ _memory_configs に保存してフォールバック。

    Args:
        config:    保存する設定辞書（merge_config でデフォルト値とマージされる）
        tenant_id: テナント識別子

    Returns:
        merge_config でマージされた完全な設定辞書
    """
    _ensure_tables()
    merged = merge_config(config)
    payload = json.dumps(merged, ensure_ascii=False)
    now = datetime.now(timezone.utc)

    db = SessionLocal()
    try:
        row = None
        if tenant_id is not None:
            row = db.execute(
                select(AutoTradeConfig).where(AutoTradeConfig.tenant_id == tenant_id)
            ).scalar_one_or_none()
        if row:
            # 既存行の更新（config_json と updated_at を更新）
            row.config_json = payload
            row.updated_at = now
        else:
            # 新規行の追加
            db.add(AutoTradeConfig(tenant_id=tenant_id, config_json=payload, updated_at=now))
        db.commit()
    except Exception as e:
        logger.warning("save_config: %s", e)
        db.rollback()
        # DB 保存失敗時はメモリキャッシュに保存（次回 get_config でも参照可能）
        if tenant_id is not None:
            _memory_configs[tenant_id] = merged
    finally:
        db.close()
    return merged


def save_run(record: dict, tenant_id: int | None = None) -> dict:
    """
    評価・実行ログを autotrade_runs テーブルに保存する。

    保存後は record に "id" と "created_at" を追記して返す。
    DB 保存に失敗した場合はメモリキャッシュ _memory_runs に追加する（フォールバック）。

    Args:
        record:    _result() が返す実行結果辞書
                   （symbol / action / decision / confidence / units 等を含む）
        tenant_id: テナント識別子

    Returns:
        "id" と "created_at" を追記した record 辞書
    """
    _ensure_tables()
    now = datetime.now(timezone.utc)
    db = SessionLocal()
    try:
        row = AutoTradeRun(
            tenant_id=tenant_id,
            symbol=record["symbol"],
            action=record.get("action", "hold"),
            decision=record.get("decision", "skipped"),
            confidence=record.get("confidence"),
            units=record.get("units"),
            fill_price=record.get("fill_price"),
            order_id=record.get("order_id"),
            trigger=record.get("trigger", "manual"),
            reason=record.get("reason", ""),
            # signal_snapshot は JSON 文字列として保存
            signal_snapshot=json.dumps(record.get("signal_snapshot", {}), ensure_ascii=False),
            created_at=now,
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        # DB が払い出した自動採番 ID と作成日時を record に追記
        record["id"] = row.id
        record["created_at"] = now.isoformat()
    except Exception as e:
        logger.warning("save_run: %s", e)
        db.rollback()
        # DB 保存失敗時はメモリキャッシュに先頭挿入（新しい順を維持）
        record["id"] = len(_memory_runs) + 1
        record["created_at"] = now.isoformat()
        _memory_runs.insert(0, record)
    finally:
        db.close()
    return record


def list_runs(limit: int = 30, tenant_id: int | None = None, symbol: str | None = None) -> list[dict]:
    """
    実行ログの一覧を作成日時の降順で取得する。

    DB から取得できない場合はメモリキャッシュ _memory_runs にフォールバック。

    Args:
        limit:     取得件数の上限（デフォルト 30 件）
        tenant_id: テナント識別子でフィルタ。None の場合はフィルタなし。
        symbol:    通貨ペアシンボルでフィルタ（大文字で比較）。None の場合はフィルタなし。

    Returns:
        実行ログ辞書のリスト（新しい順）。各辞書には以下のキーを含む:
            id / symbol / action / decision / confidence / units /
            fill_price / order_id / trigger / reason / signal_snapshot / created_at
    """
    _ensure_tables()
    db = SessionLocal()
    try:
        # created_at 降順で取得し、テナント・シンボルでフィルタ
        q = select(AutoTradeRun).order_by(desc(AutoTradeRun.created_at)).limit(limit)
        if tenant_id is not None:
            q = q.where(AutoTradeRun.tenant_id == tenant_id)
        if symbol:
            q = q.where(AutoTradeRun.symbol == symbol.upper())
        rows = db.execute(q).scalars().all()
        if rows:
            return [
                {
                    "id": r.id,
                    "symbol": r.symbol,
                    "action": r.action,
                    "decision": r.decision,
                    # Numeric 型は float に変換して返す（JSON シリアライズ可能にする）
                    "confidence": float(r.confidence) if r.confidence is not None else None,
                    "units": r.units,
                    "fill_price": float(r.fill_price) if r.fill_price else None,
                    "order_id": r.order_id,
                    "trigger": r.trigger,
                    "reason": r.reason,
                    # signal_snapshot は JSON デシリアライズして辞書で返す
                    "signal_snapshot": json.loads(r.signal_snapshot) if r.signal_snapshot else {},
                    "created_at": r.created_at.isoformat() if r.created_at else None,
                }
                for r in rows
            ]
    except Exception as e:
        logger.warning("list_runs: %s", e)
    finally:
        db.close()
    # DB 取得失敗時はメモリキャッシュからフィルタして返す
    items = _memory_runs
    if tenant_id is not None:
        items = [r for r in items if r.get("tenant_id") == tenant_id]
    if symbol:
        items = [r for r in items if r.get("symbol") == symbol.upper()]
    return items[:limit]


def count_today_trades(tenant_id: int | None, symbol: str | None = None) -> int:
    """
    当日の約定件数をカウントする（日次取引上限チェックに使用）。

    decision="executed" のレコードのうち、UTC 当日の created_at を持つものを数える。

    Args:
        tenant_id: テナント識別子。None の場合はフィルタなし。
        symbol:    通貨ペアシンボルでフィルタ（大文字で比較）。None の場合はフィルタなし。

    Returns:
        当日の約定件数（int）。DB エラー時は 0 を返す。
    """
    _ensure_tables()
    today = datetime.now(timezone.utc).date()
    db = SessionLocal()
    try:
        # decision="executed" のレコードを取得し、Python 側で当日分をカウント
        # （タイムゾーン対応の DATE 比較をアプリ層で処理）
        q = select(AutoTradeRun).where(AutoTradeRun.decision == "executed")
        if tenant_id is not None:
            q = q.where(AutoTradeRun.tenant_id == tenant_id)
        if symbol:
            q = q.where(AutoTradeRun.symbol == symbol.upper())
        rows = db.execute(q).scalars().all()
        return sum(1 for r in rows if r.created_at and r.created_at.date() == today)
    except Exception as e:
        logger.warning("count_today_trades: %s", e)
        return 0
    finally:
        db.close()


def last_executed_at(tenant_id: int | None, symbol: str) -> datetime | None:
    """
    指定シンボルの最後の約定日時を返す（クールダウンチェックに使用）。

    decision="executed" のレコードの中から最新の created_at を取得する。

    Args:
        tenant_id: テナント識別子
        symbol:    通貨ペアシンボル（大文字で比較）

    Returns:
        最後の約定日時（timezone-aware の datetime）、または None（約定履歴なし / DB エラー）
    """
    _ensure_tables()
    db = SessionLocal()
    try:
        q = (
            select(AutoTradeRun)
            .where(AutoTradeRun.decision == "executed", AutoTradeRun.symbol == symbol.upper())
            .order_by(desc(AutoTradeRun.created_at))
            .limit(1)
        )
        if tenant_id is not None:
            q = q.where(AutoTradeRun.tenant_id == tenant_id)
        row = db.execute(q).scalar_one_or_none()
        return row.created_at if row else None
    except Exception as e:
        logger.warning("last_executed_at: %s", e)
        return None
    finally:
        db.close()


def list_enabled_tenant_ids() -> list[int | None]:
    """
    自動取引が有効（enabled=True）なテナント ID の一覧を返す。

    スケジューラが処理対象テナントを列挙する際に使用する。
    tenant_id=None は非マルチテナント環境（グローバル設定）を表す。

    Returns:
        enabled=True のテナント ID リスト（None を含む場合あり）
    """
    return _list_tenant_ids_by_flag("enabled")


def list_scheduler_eligible_tenant_ids() -> list[int | None]:
    """
    enabled かつ scheduler_enabled なテナント ID の一覧を返す。

    定期スケジューラ（APScheduler 等）が run_cycle を実行するテナントを
    特定するために使用する。

    Returns:
        enabled=True かつ scheduler_enabled=True のテナント ID リスト
    """
    return _list_tenant_ids_by_flag("enabled", also_require="scheduler_enabled")


def _list_tenant_ids_by_flag(flag: str, also_require: str | None = None) -> list[int | None]:
    """
    指定フラグが True のテナント ID を DB とメモリキャッシュから収集する内部ヘルパー。

    DB と _memory_configs の両方を確認し、重複を除いてリストを返す。
    DB エラー時はメモリキャッシュのみから返す。

    Args:
        flag:         True であることを確認するフラグ名（例: "enabled"）
        also_require: 追加で True を確認するフラグ名（例: "scheduler_enabled"）。
                      None の場合は追加チェックなし。

    Returns:
        条件を満たすテナント ID のリスト（NULL=None を含む場合あり）
    """
    _ensure_tables()
    ids: list[int | None] = []
    db = SessionLocal()
    try:
        rows = db.execute(select(AutoTradeConfig)).scalars().all()
        for row in rows:
            cfg = merge_config(json.loads(row.config_json))
            # 主フラグが False のテナントはスキップ
            if not cfg.get(flag):
                continue
            # 追加フラグが指定されている場合は、そちらも True であることを確認
            # also_require のデフォルト値は True（設定がない場合は有効とみなす）
            if also_require and not cfg.get(also_require, True):
                continue
            ids.append(row.tenant_id)
    except Exception as e:
        logger.warning("_list_tenant_ids_by_flag: %s", e)
    finally:
        db.close()
    # メモリキャッシュにある分も確認して追加（DB との重複はチェック）
    for tid, cfg in _memory_configs.items():
        if not cfg.get(flag):
            continue
        if also_require and not cfg.get(also_require, True):
            continue
        if tid not in ids:
            ids.append(tid)
    return ids
