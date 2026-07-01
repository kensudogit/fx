"""
TradingView Webhook シグナル受信・保存モジュール

TradingView のアラート機能から送信される Webhook リクエストを受信し、
シグナル情報をデータベースに保存するモジュール。

TradingView Webhook の仕組み:
    TradingView のチャートにアラートを設定し、"Webhook URL" として
    このシステムのエンドポイントを指定することで、アラート発火時に
    JSON ペイロードが POST される。

受信するペイロードの例:
    {
        "symbol": "OANDA:USD_JPY",  // または "ticker"
        "action": "buy",             // または "side"
        "price": 149.50,
        "strategy": "RSI_Strategy",
        "message": "RSI oversold signal"
    }

シンボル正規化:
    TradingView は "OANDA:USD_JPY" や "FX:USDJPY" 形式で送ってくることがあるため、
    "OANDA:", "FX:" などのプレフィックスを除去して内部形式に統一する

永続化方針:
    - SQLAlchemy ORM で DB に保存（メインストレージ）
    - DB 接続失敗時はインメモリリスト（最大100件）にフォールバック
    - 自動売買エンジンはこのテーブルをポーリングして TradingView シグナルを活用する
"""

import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import Column, DateTime, Integer, Numeric, String, desc, select
from sqlalchemy.orm import Session

from src.db.database import Base, SessionLocal, engine

logger = logging.getLogger(__name__)

# メモリフォールバック（DB 未作成時）
# DB が使えない場合の一時保存先（最大 _MAX_MEMORY 件まで保持）
_memory_signals: list[dict] = []
_MAX_MEMORY = 100


class TradingViewSignal(Base):
    """TradingView Webhook シグナルの ORM モデル。

    テーブル名: tradingview_signals

    属性:
        id: 主キー（自動採番）
        tenant_id: マルチテナント識別子（None はシングルテナント）
        symbol: 通貨ペアコード（正規化済み内部形式、最大10文字）
        action: シグナルのアクション（"buy", "sell", "alert" 等）
        price: シグナル発生時の価格（任意）
        strategy: 戦略名または TradingView のアラート名（最大100文字）
        message: アラートメッセージ全文（最大500文字）
        source: シグナルの送信元（デフォルト: "tradingview"）
        received_at: 受信日時（UTC）
    """

    __tablename__ = "tradingview_signals"

    id = Column(Integer, primary_key=True, autoincrement=True)
    tenant_id = Column(Integer, nullable=True)
    symbol = Column(String(10), nullable=False)
    action = Column(String(10), nullable=False)
    price = Column(Numeric(18, 6))
    strategy = Column(String(100))
    message = Column(String(500))
    source = Column(String(30), default="tradingview")
    received_at = Column(DateTime(timezone=True), nullable=False)


def _ensure_table():
    """tradingview_signals テーブルが存在しない場合に作成する。

    テーブル作成の失敗は警告ログのみで握りつぶし、
    インメモリフォールバックに委ねる。
    """
    try:
        TradingViewSignal.__table__.create(engine, checkfirst=True)
    except Exception as e:
        logger.warning("tradingview_signals table: %s", e)


def save_signal(payload: dict[str, Any], tenant_id: int | None = None) -> dict:
    """TradingView Webhook ペイロードを解析して DB に保存する。

    ペイロードのフィールドは TradingView の設定によって異なるため、
    複数のフィールド名を試みてフォールバックする（例: "symbol" または "ticker"）。

    シンボル正規化の処理:
        1. "OANDA:USD_JPY" → "OANDA:" を除去
        2. "FX:USDJPY" → "FX:" を除去
        3. ":" で分割して最後の部分を取得
        4. 先頭10文字に切り詰め

    DB 保存失敗時のフォールバック:
        インメモリリストの先頭に追加し、_MAX_MEMORY 件を超えた古いシグナルは削除

    Args:
        payload: TradingView Webhook の JSON ペイロード（辞書形式）
        tenant_id: テナント ID（マルチテナント環境でのシグナル分離に使用）

    Returns:
        保存されたシグナルの辞書:
            - id: DB の主キー（または インメモリの順序番号）
            - symbol: 正規化済み通貨ペアコード
            - action: シグナルアクション
            - price: シグナル価格（None の場合あり）
            - strategy: 戦略名
            - message: アラートメッセージ
            - source: "tradingview"
            - tenant_id: テナント ID
            - received_at: 受信日時（ISO 形式）
    """
    _ensure_table()

    # シンボルの取得（"symbol" または "ticker" フィールドから）
    symbol = str(payload.get("symbol", payload.get("ticker", "UNKNOWN"))).upper()
    # TradingView のプレフィックス除去（"OANDA:", "FX:" 等）
    symbol = symbol.replace("OANDA:", "").replace("FX:", "").split(":")[-1][:10]

    # アクションの取得（"action" または "side" フィールドから）
    action = str(payload.get("action", payload.get("side", "alert"))).lower()

    # 価格の取得（"price" または "close" フィールドから）
    price = payload.get("price") or payload.get("close")

    # 戦略名の取得（100文字に切り詰め）
    strategy = str(payload.get("strategy", payload.get("strategy_name", "TradingView")))[:100]

    # メッセージの取得（500文字に切り詰め）
    message = str(payload.get("message", payload.get("comment", "")))[:500]

    record = {
        "symbol": symbol,
        "action": action,
        "price": float(price) if price is not None else None,
        "strategy": strategy,
        "message": message,
        "source": "tradingview",
        "tenant_id": tenant_id,
        "received_at": datetime.now(timezone.utc).isoformat(),
    }

    db: Session = SessionLocal()
    try:
        row = TradingViewSignal(
            tenant_id=tenant_id,
            symbol=record["symbol"],
            action=record["action"],
            price=record["price"],
            strategy=record["strategy"],
            message=record["message"],
            # source フィールドは DB の default で設定されるが明示的にも設定可能
            received_at=datetime.now(timezone.utc),
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        # DB から払い出された主キーをレコードに追加
        record["id"] = row.id
    except Exception as e:
        # DB 書き込み失敗時はインメモリリストに保存してフォールバック
        logger.warning("DB save failed, using memory: %s", e)
        db.rollback()
        # インメモリリストの先頭に追加（最新が先頭）
        _memory_signals.insert(0, record)
        # 古いシグナルを削除して上限（_MAX_MEMORY 件）を維持
        del _memory_signals[_MAX_MEMORY:]
        record["id"] = len(_memory_signals)
    finally:
        db.close()

    return record


def list_signals(symbol: str | None = None, limit: int = 20, tenant_id: int | None = None) -> list[dict]:
    """保存済みの TradingView シグナル一覧を取得する。

    DB から received_at 降順で取得し、失敗時はインメモリリストを返す。
    symbol と tenant_id でフィルタリングできる。

    Args:
        symbol: 通貨ペアコードでフィルタリング（None は全通貨ペア）
        limit: 取得件数の上限（デフォルト: 20）
        tenant_id: テナント ID でフィルタリング（None は全テナント）

    Returns:
        シグナル情報の辞書リスト（received_at の降順）。各辞書:
            - id: シグナル ID
            - symbol: 通貨ペアコード
            - action: アクション（"buy", "sell", "alert" 等）
            - price: シグナル価格（None の場合あり）
            - strategy: 戦略名
            - message: アラートメッセージ
            - source: "tradingview"
            - received_at: 受信日時（ISO 形式）
    """
    _ensure_table()
    db: Session = SessionLocal()
    try:
        # received_at 降順で最新シグナルを取得
        q = select(TradingViewSignal).order_by(desc(TradingViewSignal.received_at)).limit(limit)
        # シンボルフィルタ（指定された場合のみ）
        if symbol:
            q = q.where(TradingViewSignal.symbol == symbol.upper())
        # テナントフィルタ（指定された場合のみ）
        if tenant_id is not None:
            q = q.where(TradingViewSignal.tenant_id == tenant_id)
        rows = db.execute(q).scalars().all()
        if rows:
            return [
                {
                    "id": r.id,
                    "symbol": r.symbol,
                    "action": r.action,
                    "price": float(r.price) if r.price is not None else None,
                    "strategy": r.strategy,
                    "message": r.message,
                    "source": r.source,
                    "received_at": r.received_at.isoformat() if r.received_at else None,
                }
                for r in rows
            ]
    except Exception as e:
        logger.warning("list_signals DB: %s", e)
    finally:
        db.close()

    # DB 失敗時はインメモリリストからフィルタリング
    items = _memory_signals
    if symbol:
        items = [s for s in items if s["symbol"] == symbol.upper()]
    return items[:limit]
