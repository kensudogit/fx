"""
複数口座・複数通貨ペアの一元管理モジュール

ブローカー口座の CRUD 操作と、ポートフォリオ概要（口座残高・
通貨ペア価格変動・直近注文）を提供するモジュール。

主な機能:
    - 口座の一覧取得・作成（DB / インメモリフォールバック）
    - デフォルト口座の自動作成（初回アクセス時）
    - ポートフォリオ概要の生成（全口座 + 全通貨ペア + OANDA 残高）

永続化方針:
    - SQLAlchemy ORM による DB 保存（メインストレージ）
    - DB 接続失敗時はインメモリリスト（_memory_accounts）にフォールバック
    - デフォルト口座が存在しない場合は "メイン口座"（paper）を自動作成
"""

from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, Integer, Numeric, String, desc, select

# OANDA API 経由の注文一覧・口座サマリ取得
from src.broker.oanda import BrokerOrder, get_account_summary, list_orders
# 過去 OHLCV データ取得（通貨ペア価格の30日変動率計算に使用）
from src.data.market_data import get_ohlcv_data
# 全対応通貨ペアの参照価格辞書
from src.data.sample_data import SYMBOL_BASE_PRICES
from src.db.database import Base, SessionLocal, engine

# DB 接続失敗時のフォールバック用インメモリストレージ
_memory_accounts: list[dict] = []


class BrokerAccount(Base):
    """ブローカー口座の ORM モデル。

    テーブル名: broker_accounts

    属性:
        id: 主キー（自動採番）
        tenant_id: マルチテナント識別子（None はシングルテナント）
        name: 口座の表示名（例: "メイン口座", "OANDA デモ"）
        broker: ブローカー識別子（"paper", "oanda", 等）
        account_ref: ブローカー側の口座参照 ID（OANDA のアカウント ID 等）
        currency: 口座通貨（デフォルト: "USD"）
        balance: 口座残高
        is_default: デフォルト口座フラグ（1=デフォルト）
        created_at: 作成日時（UTC）
    """

    __tablename__ = "broker_accounts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    tenant_id = Column(Integer, nullable=True)
    name = Column(String(80), nullable=False)
    broker = Column(String(30), default="paper")
    account_ref = Column(String(100))
    currency = Column(String(3), default="USD")
    balance = Column(Numeric(18, 2), default=10000)
    is_default = Column(Integer, default=0)
    created_at = Column(DateTime(timezone=True), nullable=False)


def _ensure_table():
    """broker_accounts テーブルが存在しない場合に作成する。

    テーブル作成の失敗は黙って無視し、インメモリフォールバックに委ねる。
    """
    try:
        BrokerAccount.__table__.create(engine, checkfirst=True)
    except Exception:
        pass


def list_accounts(tenant_id: int | None) -> list[dict]:
    """テナントの口座一覧を取得する。

    取得順序: デフォルト口座優先、次いで ID 昇順。
    DB が利用できない場合はインメモリリストを使用する。
    口座が1件もない場合は "メイン口座"（paper）を自動作成して返す。

    Args:
        tenant_id: テナント ID（None はシングルテナント）

    Returns:
        口座情報の辞書リスト。デフォルト口座が先頭に来る。
    """
    _ensure_table()
    db = SessionLocal()
    try:
        # デフォルト口座を先頭に、次いで ID 昇順で取得
        q = select(BrokerAccount).order_by(desc(BrokerAccount.is_default), BrokerAccount.id)
        if tenant_id is not None:
            q = q.where(BrokerAccount.tenant_id == tenant_id)
        rows = db.execute(q).scalars().all()
        if rows:
            return [_row_dict(r) for r in rows]
    finally:
        db.close()

    # DB にレコードがない場合はインメモリにフォールバック
    if tenant_id is not None:
        mem = [a for a in _memory_accounts if a.get("tenant_id") == tenant_id]
        if mem:
            return mem

    # 口座が1件もない場合はデフォルトのペーパー口座を自動作成
    default = create_account(tenant_id, "メイン口座", "paper", 10000, True)
    return [default]


def create_account(
    tenant_id: int | None,
    name: str,
    broker: str = "paper",
    balance: float = 10000,
    is_default: bool = False,
) -> dict:
    """新しいブローカー口座を作成して返す。

    is_default=True の場合、同一テナントの既存デフォルト口座のフラグを
    リセットしてから新しい口座をデフォルトに設定する（1テナント1デフォルト）。

    DB への書き込みに失敗した場合はインメモリリストに保存する。

    Args:
        tenant_id: テナント ID
        name: 口座の表示名
        broker: ブローカー識別子（"paper", "oanda" 等）
        balance: 初期残高（USD）
        is_default: この口座をデフォルトにするか

    Returns:
        作成された口座情報の辞書
    """
    _ensure_table()
    db = SessionLocal()
    try:
        # デフォルト口座設定時は既存デフォルトを解除（1テナント1デフォルト制約）
        if is_default and tenant_id is not None:
            for row in db.execute(
                select(BrokerAccount).where(BrokerAccount.tenant_id == tenant_id)
            ).scalars().all():
                row.is_default = 0

        row = BrokerAccount(
            tenant_id=tenant_id,
            name=name,
            broker=broker,
            balance=balance,
            is_default=1 if is_default else 0,
            created_at=datetime.now(timezone.utc),
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        return _row_dict(row)
    except Exception:
        # DB 書き込み失敗時はロールバックしてインメモリに保存
        db.rollback()
        record = {
            "id": len(_memory_accounts) + 1,
            "tenant_id": tenant_id,
            "name": name,
            "broker": broker,
            "balance": balance,
            "currency": "USD",
            "is_default": is_default,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        _memory_accounts.append(record)
        return record
    finally:
        db.close()


def _row_dict(r: BrokerAccount) -> dict:
    """ORM オブジェクトを API レスポンス用辞書に変換する。

    Args:
        r: BrokerAccount ORM オブジェクト

    Returns:
        口座情報の辞書
    """
    return {
        "id": r.id,
        "tenant_id": r.tenant_id,
        "name": r.name,
        "broker": r.broker,
        "account_ref": r.account_ref,
        "currency": r.currency,
        "balance": float(r.balance) if r.balance else 0,
        "is_default": bool(r.is_default),
        "created_at": r.created_at.isoformat() if r.created_at else None,
    }


def build_portfolio_overview(tenant_id: int | None) -> dict:
    """テナントのポートフォリオ全体の概要を構築して返す。

    以下の情報を統合して返す:
        1. 登録済みブローカー口座の一覧と合計残高
        2. 対応全通貨ペアの現在価格と30日変動率
        3. OANDA 口座が設定されている場合はリアルタイム残高
        4. 直近の注文履歴（最大15件）

    OANDA が設定済みの場合は OANDA のリアルタイム残高を合計残高として優先使用する。

    Args:
        tenant_id: テナント ID

    Returns:
        ポートフォリオ概要の辞書:
            - accounts: 口座リスト
            - account_count: 口座数
            - total_balance: 合計残高（USD）
            - oanda_live: OANDA 口座サマリ（未設定時は None）
            - pairs: 通貨ペアごとの価格・変動率・オープン注文数
            - recent_orders: 直近注文リスト（最大15件）
            - summary: 概要テキスト（口座数・通貨ペア数・注文数）
    """
    accounts = list_accounts(tenant_id)
    # 直近50件の注文を取得（通貨ペアごとのオープン注文数算出に使用）
    orders = list_orders(50, tenant_id)
    # OANDA 口座サマリを取得（未設定の場合は configured=False が返る）
    oanda = get_account_summary()

    # 全対応通貨ペアの価格情報を構築
    pairs = []
    for sym in SYMBOL_BASE_PRICES:
        # 過去30日の OHLCV データを取得して現在価格と変動率を計算
        df, source = get_ohlcv_data(sym, 30)
        price = float(df["close"].iloc[-1])
        # 30日変動率: (現在終値 / 30日前終値 - 1) × 100
        chg = float((df["close"].iloc[-1] / df["close"].iloc[0] - 1) * 100)
        # この通貨ペアのオープン注文数を集計
        sym_orders = [o for o in orders if o["symbol"] == sym]
        pairs.append({
            "symbol": sym,
            "price": round(price, 4),
            "change_30d_pct": round(chg, 2),
            "source": source,
            "open_orders": len(sym_orders),
        })

    # 合計残高: 全口座の残高を合算
    total_balance = sum(a["balance"] for a in accounts)
    # OANDA が設定済みの場合はリアルタイム残高を優先使用
    if oanda.get("configured"):
        total_balance = oanda.get("balance", total_balance)

    return {
        "accounts": accounts,
        "account_count": len(accounts),
        "total_balance": round(total_balance, 2),
        # OANDA が未設定の場合は None を返してフロントで非表示にする
        "oanda_live": oanda if oanda.get("configured") else None,
        "pairs": pairs,
        "recent_orders": orders[:15],
        "summary": (
            f"{len(accounts)}口座 · {len(SYMBOL_BASE_PRICES)}通貨ペア · "
            f"直近注文 {len(orders)}件"
        ),
    }
