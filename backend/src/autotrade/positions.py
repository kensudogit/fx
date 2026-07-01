"""
ポジション管理モジュール — SL/TP 監視・逆シグナル決済

FX 自動売買システムにおいてオープンポジションを管理し、
以下のトリガーで自動決済を行うモジュール。

決済トリガー:
    1. ストップロス（SL）価格への到達
    2. テイクプロフィット（TP）価格への到達
    3. 逆方向シグナルの発生（auto_exit_on_reverse=True の場合）

永続化方針:
    - SQLAlchemy ORM を使ってデータベースに保存（メインストレージ）
    - DB 接続失敗時はインメモリリスト（_memory_positions）にフォールバック
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import Column, DateTime, Integer, Numeric, String, desc, select

# 実現損益計算ユーティリティ（pips→USD換算）
from src.autotrade.pnl import calc_realized_pnl_usd
# OANDA REST API 経由の決済・注文・オープンポジション取得関数
from src.broker.oanda import close_position as oanda_close, get_open_positions, place_market_order
from src.db.database import Base, SessionLocal, engine

logger = logging.getLogger(__name__)

# DB 接続失敗時のフォールバック用インメモリストレージ
_memory_positions: list[dict] = []


class AutoTradePosition(Base):
    """自動売買ポジションの ORM モデル。

    テーブル名: autotrade_positions

    属性:
        id: 主キー（自動採番）
        tenant_id: マルチテナント識別子（None はシングルテナント運用）
        symbol: 通貨ペアコード（例: "USDJPY"）
        side: ポジション方向（"buy" または "sell"）
        units: 通貨単位数（例: 10000）
        entry_price: エントリー価格
        stop_loss: ストップロス価格（任意）
        take_profit: テイクプロフィット価格（任意）
        status: ポジション状態（"OPEN" または "CLOSED"）
        order_id: ブローカー側の注文 ID
        opened_at: ポジションオープン日時（UTC）
        closed_at: ポジション決済日時（UTC、決済後のみ）
        close_price: 決済価格（決済後のみ）
        close_reason: 決済理由（"stop_loss", "take_profit", "reverse_signal" 等）
    """

    __tablename__ = "autotrade_positions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    tenant_id = Column(Integer, nullable=True)
    symbol = Column(String(10), nullable=False)
    side = Column(String(10), nullable=False)
    units = Column(Integer, nullable=False)
    entry_price = Column(Numeric(18, 6), nullable=False)
    stop_loss = Column(Numeric(18, 6))
    take_profit = Column(Numeric(18, 6))
    status = Column(String(20), default="OPEN")
    order_id = Column(Integer)
    opened_at = Column(DateTime(timezone=True), nullable=False)
    closed_at = Column(DateTime(timezone=True))
    close_price = Column(Numeric(18, 6))
    close_reason = Column(String(50))


def _ensure_table():
    """autotrade_positions テーブルが存在しない場合に作成する。

    テーブル作成の失敗は警告ログのみで握りつぶし、
    処理を継続できるようにする（インメモリフォールバックに委ねる）。
    """
    try:
        AutoTradePosition.__table__.create(engine, checkfirst=True)
    except Exception as e:
        logger.warning("autotrade_positions table: %s", e)


def open_position(
    tenant_id: int | None,
    symbol: str,
    side: str,
    units: int,
    entry_price: float,
    stop_loss: float | None,
    take_profit: float | None,
    order_id: int | None = None,
) -> dict:
    """新規ポジションを DB に記録して返す。

    DB への書き込みに失敗した場合はインメモリリストに保存し、
    処理を継続する（ペーパー取引やテスト環境での DB 未設定に対応）。

    Args:
        tenant_id: テナント ID（None はシングルテナント）
        symbol: 通貨ペアコード（大文字に正規化される）
        side: "buy" または "sell"
        units: 通貨単位数
        entry_price: エントリー価格
        stop_loss: SL 価格（None の場合は SL なし）
        take_profit: TP 価格（None の場合は TP なし）
        order_id: ブローカー側の注文 ID（任意）

    Returns:
        保存されたポジション情報の辞書。
        DB 保存成功時は id フィールドを含む。
    """
    _ensure_table()
    now = datetime.now(timezone.utc)
    # 返却用の基本レコードを先に構築
    record = {
        "symbol": symbol.upper(),
        "side": side,
        "units": units,
        "entry_price": entry_price,
        "stop_loss": stop_loss,
        "take_profit": take_profit,
        "status": "OPEN",
        "order_id": order_id,
        "opened_at": now.isoformat(),
    }
    db = SessionLocal()
    try:
        row = AutoTradePosition(
            tenant_id=tenant_id,
            symbol=symbol.upper(),
            side=side,
            units=units,
            entry_price=entry_price,
            stop_loss=stop_loss,
            take_profit=take_profit,
            status="OPEN",
            order_id=order_id,
            opened_at=now,
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        record["id"] = row.id
    except Exception as e:
        # DB 書き込み失敗時はロールバックしてインメモリに退避
        logger.warning("open_position: %s", e)
        db.rollback()
        record["id"] = len(_memory_positions) + 1
        _memory_positions.append(record)
    finally:
        db.close()
    return record


def list_open_positions(tenant_id: int | None = None, symbol: str | None = None) -> list[dict]:
    """オープン中のポジション一覧を取得する。

    DB から取得を試み、失敗またはレコードなしの場合は
    インメモリリストからフィルタリングして返す。

    Args:
        tenant_id: テナント ID でフィルタリング（None は全テナント）
        symbol: 通貨ペアでフィルタリング（None は全通貨ペア）

    Returns:
        オープンポジションの辞書リスト（opened_at の降順）
    """
    _ensure_table()
    db = SessionLocal()
    try:
        # status="OPEN" のポジションを opened_at 降順で取得
        q = select(AutoTradePosition).where(AutoTradePosition.status == "OPEN").order_by(desc(AutoTradePosition.opened_at))
        if tenant_id is not None:
            q = q.where(AutoTradePosition.tenant_id == tenant_id)
        if symbol:
            q = q.where(AutoTradePosition.symbol == symbol.upper())
        rows = db.execute(q).scalars().all()
        if rows:
            return [_pos_dict(r) for r in rows]
    except Exception as e:
        logger.warning("list_open_positions: %s", e)
    finally:
        db.close()

    # DB が利用できない場合はインメモリリストからフィルタリング
    items = [p for p in _memory_positions if p.get("status") == "OPEN"]
    if tenant_id is not None:
        items = [p for p in items if p.get("tenant_id") == tenant_id]
    if symbol:
        items = [p for p in items if p.get("symbol") == symbol.upper()]
    return items


def _pos_dict(r: AutoTradePosition, include_close: bool = False) -> dict:
    """ORM オブジェクトを API レスポンス用辞書に変換する。

    CLOSED ポジションまたは include_close=True の場合は、
    決済情報（close_price, close_reason）と実現損益（realized_pnl_usd）も含める。

    Args:
        r: AutoTradePosition ORM オブジェクト
        include_close: True の場合は決済情報を強制的に含める

    Returns:
        ポジション情報の辞書。CLOSED の場合は損益計算結果も含む。
    """
    d = {
        "id": r.id,
        "symbol": r.symbol,
        "side": r.side,
        "units": r.units,
        "entry_price": float(r.entry_price),
        "stop_loss": float(r.stop_loss) if r.stop_loss else None,
        "take_profit": float(r.take_profit) if r.take_profit else None,
        "status": r.status,
        "order_id": r.order_id,
        "opened_at": r.opened_at.isoformat() if r.opened_at else None,
    }
    # CLOSED ポジションまたは明示的に決済情報を要求した場合のみ損益を計算
    if include_close or r.status == "CLOSED":
        d["closed_at"] = r.closed_at.isoformat() if r.closed_at else None
        d["close_price"] = float(r.close_price) if r.close_price else None
        d["close_reason"] = r.close_reason
        # 決済価格がある場合のみ実現損益を計算（pips→USD 換算）
        if d.get("close_price"):
            d["realized_pnl_usd"] = calc_realized_pnl_usd(
                r.symbol, r.side, r.units, float(r.entry_price), float(r.close_price)
            )
    return d


def list_closed_positions(
    tenant_id: int | None = None,
    days: int = 90,
    limit: int = 200,
) -> list[dict]:
    """指定期間内の決済済みポジション一覧を取得する。

    Args:
        tenant_id: テナント ID でフィルタリング（None は全テナント）
        days: 過去何日分を取得するか（デフォルト: 90日）
        limit: 取得上限件数（デフォルト: 200件）

    Returns:
        決済済みポジションの辞書リスト（closed_at の降順）。
        各辞書に realized_pnl_usd を含む。
        取得失敗時は空リストを返す。
    """
    _ensure_table()
    # 取得開始日時を計算（現在時刻から days 日前）
    since = datetime.now(timezone.utc) - timedelta(days=days)
    db = SessionLocal()
    try:
        q = (
            select(AutoTradePosition)
            .where(AutoTradePosition.status == "CLOSED")
            .where(AutoTradePosition.closed_at >= since)
            .order_by(desc(AutoTradePosition.closed_at))
            .limit(limit)
        )
        if tenant_id is not None:
            q = q.where(AutoTradePosition.tenant_id == tenant_id)
        rows = db.execute(q).scalars().all()
        # include_close=True で実現損益を含む辞書に変換
        return [_pos_dict(r, include_close=True) for r in rows]
    except Exception as e:
        logger.warning("list_closed_positions: %s", e)
        return []
    finally:
        db.close()


def close_position_record(
    position_id: int,
    close_price: float,
    reason: str,
    tenant_id: int | None = None,
) -> dict | None:
    """DB のポジションレコードを CLOSED に更新する。

    テナント ID が指定された場合はテナント所有権を検証し、
    他テナントのポジションへの不正アクセスを防ぐ。

    Args:
        position_id: 決済するポジションの ID
        close_price: 決済価格
        reason: 決済理由（"stop_loss", "take_profit", "reverse_signal" 等）
        tenant_id: テナント ID（所有権確認に使用。None はチェックなし）

    Returns:
        更新後のポジション辞書（realized_pnl_usd を含む）。
        ポジションが存在しない、OPEN でない、または
        テナント不一致の場合は None を返す。
    """
    _ensure_table()
    db = SessionLocal()
    try:
        row = db.get(AutoTradePosition, position_id)
        # ポジションが存在しない、または既に CLOSED の場合はスキップ
        if not row or row.status != "OPEN":
            return None
        # テナント所有権の確認（他テナントのポジションへのアクセスを拒否）
        if tenant_id is not None and row.tenant_id != tenant_id:
            return None

        # ポジションを CLOSED に更新
        row.status = "CLOSED"
        row.closed_at = datetime.now(timezone.utc)
        row.close_price = close_price
        row.close_reason = reason
        db.commit()
        return _pos_dict(row, include_close=True)
    except Exception as e:
        logger.warning("close_position_record: %s", e)
        db.rollback()
        return None
    finally:
        db.close()


def check_exits(
    symbol: str,
    current_price: float,
    tenant_id: int | None,
    reverse_action: str | None = None,
    auto_exit_on_reverse: bool = True,
    trading_mode: str = "paper",
) -> list[dict]:
    """SL/TP 到達または逆シグナルで保有ポジションを自動決済する。

    決済判定ロジック（優先順）:
        1. ストップロス到達: buy ポジションで current_price <= SL、
                            sell ポジションで current_price >= SL
        2. テイクプロフィット到達: buy ポジションで current_price >= TP、
                                  sell ポジションで current_price <= TP
        3. 逆シグナル: auto_exit_on_reverse=True の場合、
                       buy ポジションで sell シグナル、またはその逆

    決済実行:
        - まず OANDA API の close_position を試みる
        - 失敗した場合は逆方向の成行注文（place_market_order）でフォールバック
        - DB のポジションレコードを CLOSED に更新

    Args:
        symbol: 監視対象の通貨ペアコード
        current_price: 現在の市場価格
        tenant_id: テナント ID
        reverse_action: 新しいシグナルの方向（"buy", "sell", None）
        auto_exit_on_reverse: True の場合、逆シグナルで決済
        trading_mode: "paper"（ペーパー取引）または "live"（実取引）

    Returns:
        決済されたポジションの辞書リスト。
        各辞書に close_reason（決済理由）を含む。
    """
    positions = list_open_positions(tenant_id, symbol)
    if not positions:
        return []

    closed = []
    for pos in positions:
        reason = None
        side = pos["side"]

        # === SL（ストップロス）判定 ===
        if pos.get("stop_loss"):
            if side == "buy" and current_price <= pos["stop_loss"]:
                # buy ポジション: 価格がSL以下に下落 → 損切り
                reason = "stop_loss"
            elif side == "sell" and current_price >= pos["stop_loss"]:
                # sell ポジション: 価格がSL以上に上昇 → 損切り
                reason = "stop_loss"

        # === TP（テイクプロフィット）判定（SL未到達の場合のみ）===
        if not reason and pos.get("take_profit"):
            if side == "buy" and current_price >= pos["take_profit"]:
                # buy ポジション: 価格がTP以上に上昇 → 利確
                reason = "take_profit"
            elif side == "sell" and current_price <= pos["take_profit"]:
                # sell ポジション: 価格がTP以下に下落 → 利確
                reason = "take_profit"

        # === 逆シグナル判定（SL/TP 未到達かつ自動決済が有効な場合）===
        if not reason and auto_exit_on_reverse and reverse_action in ("buy", "sell"):
            if (side == "buy" and reverse_action == "sell") or (side == "sell" and reverse_action == "buy"):
                # 保有方向と逆のシグナルが発生 → ポジションをクローズ
                reason = "reverse_signal"

        # 決済理由がない場合はスキップ（継続保有）
        if not reason:
            continue

        # 決済方向はポジション方向の逆（buy → sell で決済、sell → buy で決済）
        exit_side = "sell" if side == "buy" else "buy"
        try:
            # 優先: OANDA API のポジション決済エンドポイントを使用
            oanda_close(symbol, side, pos["units"], tenant_id, trading_mode=trading_mode)
        except Exception:
            # フォールバック: 逆方向の成行注文でポジションを相殺
            place_market_order(symbol, exit_side, pos["units"], tenant_id, trading_mode=trading_mode)

        # DB のレコードを CLOSED に更新して決済済みリストに追加
        rec = close_position_record(pos["id"], current_price, reason, tenant_id)
        if rec:
            rec["close_reason"] = reason
            closed.append(rec)
    return closed


def has_open_position(tenant_id: int | None, symbol: str) -> bool:
    """指定通貨ペアにオープンポジションが存在するか確認する。

    Args:
        tenant_id: テナント ID
        symbol: 通貨ペアコード

    Returns:
        オープンポジションが1件以上ある場合は True
    """
    return len(list_open_positions(tenant_id, symbol)) > 0
