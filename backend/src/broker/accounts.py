"""複数口座・複数通貨ペアの一元管理"""

from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, Integer, Numeric, String, desc, select

from src.broker.oanda import BrokerOrder, get_account_summary, list_orders
from src.data.market_data import get_ohlcv_data
from src.data.sample_data import SYMBOL_BASE_PRICES
from src.db.database import Base, SessionLocal, engine

_memory_accounts: list[dict] = []


class BrokerAccount(Base):
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
    try:
        BrokerAccount.__table__.create(engine, checkfirst=True)
    except Exception:
        pass


def list_accounts(tenant_id: int | None) -> list[dict]:
    _ensure_table()
    db = SessionLocal()
    try:
        q = select(BrokerAccount).order_by(desc(BrokerAccount.is_default), BrokerAccount.id)
        if tenant_id is not None:
            q = q.where(BrokerAccount.tenant_id == tenant_id)
        rows = db.execute(q).scalars().all()
        if rows:
            return [_row_dict(r) for r in rows]
    finally:
        db.close()

    if tenant_id is not None:
        mem = [a for a in _memory_accounts if a.get("tenant_id") == tenant_id]
        if mem:
            return mem

    # デフォルト口座を自動作成
    default = create_account(tenant_id, "メイン口座", "paper", 10000, True)
    return [default]


def create_account(
    tenant_id: int | None,
    name: str,
    broker: str = "paper",
    balance: float = 10000,
    is_default: bool = False,
) -> dict:
    _ensure_table()
    db = SessionLocal()
    try:
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
    accounts = list_accounts(tenant_id)
    orders = list_orders(50, tenant_id)
    oanda = get_account_summary()

    pairs = []
    for sym in SYMBOL_BASE_PRICES:
        df, source = get_ohlcv_data(sym, 30)
        price = float(df["close"].iloc[-1])
        chg = float((df["close"].iloc[-1] / df["close"].iloc[0] - 1) * 100)
        sym_orders = [o for o in orders if o["symbol"] == sym]
        pairs.append({
            "symbol": sym,
            "price": round(price, 4),
            "change_30d_pct": round(chg, 2),
            "source": source,
            "open_orders": len(sym_orders),
        })

    total_balance = sum(a["balance"] for a in accounts)
    if oanda.get("configured"):
        total_balance = oanda.get("balance", total_balance)

    return {
        "accounts": accounts,
        "account_count": len(accounts),
        "total_balance": round(total_balance, 2),
        "oanda_live": oanda if oanda.get("configured") else None,
        "pairs": pairs,
        "recent_orders": orders[:15],
        "summary": (
            f"{len(accounts)}口座 · {len(SYMBOL_BASE_PRICES)}通貨ペア · "
            f"直近注文 {len(orders)}件"
        ),
    }
