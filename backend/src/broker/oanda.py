"""
OANDA v20 REST API クライアントモジュール

OANDA のトレーディング API（v20）を通じて注文・口座管理・
リアルタイム価格取得を行うモジュール。

主な機能:
    - 口座サマリの取得（残高・未実現損益・オープントレード数）
    - リアルタイム価格取得（bid/ask/mid価格、OANDA→DB→Yahoo フォールバック）
    - 成行注文の発注（SL/TP 付き）
    - ポジションのクローズ（逆方向成行注文）
    - オープンポジション一覧の取得

マルチテナント対応:
    - テナントごとに個別の OANDA API トークン・口座 ID を使用可能
    - resolve_oanda_credentials() でテナント設定 → グローバル設定 → ペーパーの順に解決

エラーハンドリング:
    - OANDA 未設定時はペーパー取引モードに自動フォールバック
    - 価格取得失敗時は market_data モジュールのデータにフォールバック
    - 注文保存失敗時はインメモリリストにフォールバック

通貨ペアのマッピング:
    OANDA API は "USD_JPY" 形式を使用するため、
    内部コード（"USDJPY"）との相互変換マップを保持する。
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

import httpx
from sqlalchemy import Column, DateTime, Integer, Numeric, String, desc, select

# テナント別 OANDA 認証情報の解決
from src.broker.tenant_oanda import OandaCredentials, resolve_oanda_credentials
from src.config import settings
from src.db.database import Base, SessionLocal, engine

logger = logging.getLogger(__name__)

# DB 接続失敗時のフォールバック用インメモリ注文ストレージ
_memory_orders: list[dict] = []

# 内部シンボルコード → OANDA API の instrument 名 マッピング
SYMBOL_TO_OANDA = {
    "USDJPY": "USD_JPY",
    "EURUSD": "EUR_USD",
    "GBPUSD": "GBP_USD",
    "AUDUSD": "AUD_USD",
}
# OANDA API の instrument 名 → 内部シンボルコード 逆引きマップ
OANDA_TO_SYMBOL = {v: k for k, v in SYMBOL_TO_OANDA.items()}


class BrokerOrder(Base):
    """ブローカー注文の ORM モデル。

    テーブル名: broker_orders

    属性:
        id: 主キー（自動採番）
        tenant_id: マルチテナント識別子
        symbol: 通貨ペアコード（内部形式、例: "USDJPY"）
        side: 注文方向（"buy" または "sell"）
        units: 注文数量（通貨単位）
        order_type: 注文タイプ（"MARKET" 固定）
        status: 注文状態（"PENDING", "FILLED", "SUBMITTED"）
        fill_price: 約定価格（OANDA 約定時または現在価格）
        broker: ブローカー識別子（"oanda" または "paper"）
        external_id: OANDA 側の注文/約定 ID
        created_at: 注文作成日時（UTC）
    """

    __tablename__ = "broker_orders"

    id = Column(Integer, primary_key=True, autoincrement=True)
    tenant_id = Column(Integer, nullable=True)
    symbol = Column(String(10), nullable=False)
    side = Column(String(10), nullable=False)
    units = Column(Integer, nullable=False)
    order_type = Column(String(20), default="MARKET")
    status = Column(String(20), default="PENDING")
    fill_price = Column(Numeric(18, 6))
    broker = Column(String(20), default="paper")
    external_id = Column(String(100))
    created_at = Column(DateTime(timezone=True), nullable=False)


def _ensure_table():
    """broker_orders テーブルが存在しない場合に作成する。"""
    try:
        BrokerOrder.__table__.create(engine, checkfirst=True)
    except Exception as e:
        logger.warning("broker_orders table: %s", e)


def is_oanda_configured(tenant_id: int | None = None, trading_mode: str = "live") -> bool:
    """OANDA が設定済み（実取引可能な状態）かを確認する。

    Args:
        tenant_id: テナント ID
        trading_mode: "live" または "practice"

    Returns:
        API トークンと口座 ID が設定されている場合は True
    """
    creds = resolve_oanda_credentials(tenant_id, trading_mode)
    return creds.configured


def _base_url(creds: OandaCredentials) -> str:
    """認証情報に応じた OANDA API のベース URL を返す。

    Args:
        creds: OANDA 認証情報オブジェクト

    Returns:
        live モードは本番 API URL、それ以外はデモ API URL
    """
    if creds.mode == "live":
        return "https://api-fxtrade.oanda.com/v3"
    return "https://api-fxpractice.oanda.com/v3"


def _headers(creds: OandaCredentials) -> dict:
    """OANDA REST API リクエスト用の認証ヘッダーを生成する。

    Args:
        creds: OANDA 認証情報オブジェクト

    Returns:
        Authorization（Bearer トークン）と Content-Type を含むヘッダー辞書
    """
    return {
        "Authorization": f"Bearer {creds.api_token}",
        "Content-Type": "application/json",
    }


def get_account_summary(tenant_id: int | None = None, trading_mode: str = "live") -> dict:
    """OANDA 口座サマリを取得する。

    OANDA が未設定の場合はペーパー取引用のデフォルト値を返す。
    設定済みの場合は OANDA API の /accounts/{id}/summary エンドポイントを呼び出す。

    Args:
        tenant_id: テナント ID
        trading_mode: "live" または "practice"

    Returns:
        口座情報の辞書:
            - configured: OANDA が設定済みか
            - mode: 取引モード（"live", "practice", "paper"）
            - balance: 口座残高
            - currency: 口座通貨
            - unrealized_pl: 未実現損益（OANDA 設定済みの場合のみ）
            - open_trade_count: オープントレード数（OANDA 設定済みの場合のみ）
    """
    creds = resolve_oanda_credentials(tenant_id, trading_mode)
    if not creds.configured:
        # OANDA 未設定時はペーパー取引のデフォルト値を返す
        return {
            "configured": False,
            "mode": "paper",
            "balance": 10000,
            "currency": "USD",
            "source": creds.source,
            "message": "OANDA 未設定 — ペーパー取引モード（/settings で口座設定）",
        }

    # OANDA API の口座サマリエンドポイントを呼び出す
    url = f"{_base_url(creds)}/accounts/{creds.account_id}/summary"
    with httpx.Client(timeout=20.0) as client:
        res = client.get(url, headers=_headers(creds))
        res.raise_for_status()
        acct = res.json().get("account", {})
    return {
        "configured": True,
        "mode": creds.mode,
        "source": creds.source,
        "balance": float(acct.get("balance", 0)),
        "currency": acct.get("currency", "USD"),
        "unrealized_pl": float(acct.get("unrealizedPL", 0)),
        "open_trade_count": int(acct.get("openTradeCount", 0)),
    }


def fetch_live_prices(symbols: list[str], tenant_id: int | None = None, trading_mode: str = "live") -> dict[str, dict]:
    """リアルタイム価格を取得する（OANDA pricing → DB/Yahoo フォールバック）。

    取得戦略（優先順）:
        1. OANDA API: /accounts/{id}/pricing エンドポイントで bid/ask を取得
        2. market_data フォールバック: OANDA 未設定または取得失敗時に
           DB や Yahoo Finance から直近の終値を使用

    mid 価格の計算:
        (bid + ask) / 2 で計算し、JPY ペアは小数第3位、それ以外は第5位に丸める

    Args:
        symbols: 取得する通貨ペアコードのリスト（例: ["USDJPY", "EURUSD"]）
        tenant_id: テナント ID
        trading_mode: "live" または "practice"

    Returns:
        シンボルをキーとする価格情報辞書。各値:
            - symbol: 通貨ペア
            - bid: 売値（OANDA）
            - ask: 買値（OANDA）
            - price: mid 価格
            - source: データ取得元（"oanda" または "yahoo" 等）
            - time: 価格時刻（ISO 形式）
    """
    creds = resolve_oanda_credentials(tenant_id, trading_mode)
    # OANDA 対応通貨ペアのみフィルタリング
    normalized = [s.upper() for s in symbols if s.upper() in SYMBOL_TO_OANDA]
    result: dict[str, dict] = {}

    if creds.configured and normalized:
        # 複数通貨ペアを一度に取得するためカンマ区切りの instruments パラメータを構築
        instruments = ",".join(SYMBOL_TO_OANDA[s] for s in normalized)
        url = f"{_base_url(creds)}/accounts/{creds.account_id}/pricing"
        try:
            with httpx.Client(timeout=10.0) as client:
                res = client.get(url, headers=_headers(creds), params={"instruments": instruments})
                res.raise_for_status()
                for item in res.json().get("prices", []):
                    # OANDA の instrument 名（例: "USD_JPY"）を内部コードに変換
                    sym = OANDA_TO_SYMBOL.get(item.get("instrument", ""))
                    if not sym:
                        continue
                    bids = item.get("bids") or []
                    asks = item.get("asks") or []
                    # bid/ask のベストプライス（先頭要素）を使用
                    bid = float(bids[0]["price"]) if bids else None
                    ask = float(asks[0]["price"]) if asks else None
                    # mid = (bid + ask) / 2、小数桁はペアに応じて調整
                    mid = round((bid + ask) / 2, 5 if not sym.endswith("JPY") else 3) if bid and ask else None
                    result[sym] = {
                        "symbol": sym,
                        "bid": bid,
                        "ask": ask,
                        "price": mid,
                        "source": "oanda",
                        "time": item.get("time"),
                    }
        except Exception as e:
            logger.warning("OANDA pricing failed: %s", e)

    # OANDA で取得できなかった通貨ペアを market_data でフォールバック取得
    missing = [s for s in normalized if s not in result]
    if missing:
        from src.data.market_data import get_ohlcv_data

        for sym in missing:
            try:
                # 直近5日の OHLCV データを取得して最新終値を使用
                df, source = get_ohlcv_data(sym, 5)
                price = float(df["close"].iloc[-1])
                result[sym] = {
                    "symbol": sym,
                    "bid": price,
                    "ask": price,
                    "price": price,
                    "source": source,
                    "time": datetime.now(timezone.utc).isoformat(),
                }
            except Exception as e:
                logger.warning("price fallback %s: %s", sym, e)

    return result


def place_market_order(
    symbol: str,
    side: str,
    units: int,
    tenant_id: int | None = None,
    stop_loss: float | None = None,
    take_profit: float | None = None,
    trading_mode: str | None = None,
) -> dict:
    """成行注文を発注する（OANDA API またはペーパー取引）。

    OANDA が設定されていない場合は自動的にペーパー取引にフォールバックする。
    OANDA が設定されている場合は FOK（Fill or Kill）の成行注文を発注する。

    注文ボディの構成:
        - type: "MARKET"（成行）
        - timeInForce: "FOK"（即時全量約定またはキャンセル）
        - positionFill: "DEFAULT"（デフォルトの建玉処理）
        - stopLossOnFill: SL が指定された場合に追加
        - takeProfitOnFill: TP が指定された場合に追加

    Args:
        symbol: 通貨ペアコード（例: "USDJPY"）
        side: "buy" または "sell"
        units: 注文数量（通貨単位。signed_units として buy=+, sell=- に変換）
        tenant_id: テナント ID
        stop_loss: ストップロス価格（任意）
        take_profit: テイクプロフィット価格（任意）
        trading_mode: "paper", "live", "practice"（None の場合は "paper"）

    Returns:
        注文情報の辞書（id, symbol, side, units, status, fill_price, broker 等）

    Raises:
        ValueError: side が "buy" または "sell" 以外の場合
        ValueError: OANDA でサポートされていない通貨ペアの場合
        httpx.HTTPStatusError: OANDA API からエラーレスポンスが返った場合
    """
    symbol = symbol.upper()
    side = side.lower()
    if side not in ("buy", "sell"):
        raise ValueError("side must be buy or sell")
    # buy は正の units、sell は負の units（OANDA API の仕様）
    signed_units = abs(units) if side == "buy" else -abs(units)

    mode = trading_mode or "paper"
    creds = resolve_oanda_credentials(tenant_id, mode)
    if not creds.configured:
        # OANDA 未設定時はペーパー取引として処理
        return _save_paper_order(symbol, side, abs(units), tenant_id, stop_loss, take_profit)

    # OANDA の instrument 名に変換（例: "USDJPY" → "USD_JPY"）
    instrument = SYMBOL_TO_OANDA.get(symbol)
    if not instrument:
        raise ValueError(f"Unsupported symbol for OANDA: {symbol}")

    # OANDA 成行注文のリクエストボディを構築
    order_body: dict[str, Any] = {
        "instrument": instrument,
        "units": str(signed_units),
        "type": "MARKET",
        "timeInForce": "FOK",    # Fill or Kill: 即時全量約定またはキャンセル
        "positionFill": "DEFAULT",
    }
    # SL が指定された場合は stopLossOnFill を追加（約定時に自動設定）
    if stop_loss is not None:
        order_body["stopLossOnFill"] = {"price": str(round(stop_loss, 5))}
    # TP が指定された場合は takeProfitOnFill を追加
    if take_profit is not None:
        order_body["takeProfitOnFill"] = {"price": str(round(take_profit, 5))}

    payload = {"order": order_body}
    # OANDA API の注文エンドポイントに POST リクエストを送信
    url = f"{_base_url(creds)}/accounts/{creds.account_id}/orders"
    with httpx.Client(timeout=20.0) as client:
        res = client.post(url, headers=_headers(creds), json=payload)
        res.raise_for_status()
        body = res.json()

    # レスポンスから約定情報を取得（約定済みは orderFillTransaction、それ以外は orderCreateTransaction）
    fill = body.get("orderFillTransaction") or body.get("orderCreateTransaction") or {}
    record = _save_order(
        symbol=symbol,
        side=side,
        units=abs(units),
        status="FILLED" if fill.get("type") == "ORDER_FILL" else "SUBMITTED",
        fill_price=float(fill.get("price", 0)) if fill.get("price") else None,
        broker="oanda",
        external_id=str(fill.get("id", "")),
        tenant_id=tenant_id,
    )
    if stop_loss is not None:
        record["stop_loss"] = stop_loss
    if take_profit is not None:
        record["take_profit"] = take_profit
    record["broker_mode"] = creds.mode
    return record


def close_position(
    symbol: str,
    side: str,
    units: int,
    tenant_id: int | None = None,
    trading_mode: str | None = None,
) -> dict:
    """保有ポジションを逆方向の成行注文でクローズする。

    OANDA では専用のクローズエンドポイントもあるが、
    このシステムでは逆方向の成行注文を使ってポジションを相殺する。

    Args:
        symbol: 通貨ペアコード
        side: 決済するポジションの方向（"buy" → sell で決済、"sell" → buy で決済）
        units: 決済数量
        tenant_id: テナント ID
        trading_mode: 取引モード

    Returns:
        決済注文の情報辞書
    """
    # buy ポジションの決済は sell 注文、sell ポジションの決済は buy 注文
    exit_side = "sell" if side == "buy" else "buy"
    return place_market_order(symbol, exit_side, units, tenant_id, trading_mode=trading_mode)


def get_open_positions(tenant_id: int | None = None, trading_mode: str | None = None) -> list[dict]:
    """オープンポジションの一覧を取得する。

    OANDA が設定されている場合は /openPositions エンドポイントを使用し、
    未設定の場合は autotrade モジュールの DB から取得する。

    OANDA レスポンスの構造:
        - long.units: ロングポジション数量（正の値）
        - short.units: ショートポジション数量（負の値）

    Args:
        tenant_id: テナント ID
        trading_mode: "live" または "practice"

    Returns:
        オープンポジションの辞書リスト。各辞書:
            - symbol: 通貨ペアコード（内部形式）
            - side: "buy" または "sell"
            - units: 数量（絶対値）
    """
    mode = trading_mode or "live"
    creds = resolve_oanda_credentials(tenant_id, mode)
    if not creds.configured:
        # OANDA 未設定時は autotrade DB のポジション管理に委譲
        from src.autotrade.positions import list_open_positions

        return list_open_positions(tenant_id)

    # OANDA API のオープンポジション一覧を取得
    url = f"{_base_url(creds)}/accounts/{creds.account_id}/openPositions"
    with httpx.Client(timeout=20.0) as client:
        res = client.get(url, headers=_headers(creds))
        res.raise_for_status()
        positions = res.json().get("positions", [])

    result = []
    for p in positions:
        # OANDA の instrument 名（例: "USD_JPY"）を内部コードに変換
        inst = p.get("instrument", "")
        sym = inst.replace("_", "")
        long_u = int(p.get("long", {}).get("units", 0))
        short_u = int(p.get("short", {}).get("units", 0))
        # ロングポジションが存在する場合（units > 0）
        if long_u > 0:
            result.append({"symbol": sym, "side": "buy", "units": long_u})
        # ショートポジションが存在する場合（units < 0）
        if short_u < 0:
            result.append({"symbol": sym, "side": "sell", "units": abs(short_u)})
    return result


def _save_paper_order(
    symbol: str,
    side: str,
    units: int,
    tenant_id: int | None = None,
    stop_loss: float | None = None,
    take_profit: float | None = None,
) -> dict:
    """ペーパー取引の注文を現在価格で約定済みとして保存する。

    リアルタイム価格の取得を試み、失敗した場合は
    market_data から最新終値を使用する。

    Args:
        symbol: 通貨ペアコード
        side: "buy" または "sell"
        units: 注文数量
        tenant_id: テナント ID
        stop_loss: SL 価格（任意）
        take_profit: TP 価格（任意）

    Returns:
        約定済みとして記録されたペーパー注文の辞書
    """
    # まずリアルタイム価格（OANDA または フォールバック）を取得
    live = fetch_live_prices([symbol], tenant_id, trading_mode="live")
    quote = live.get(symbol.upper())
    if quote and quote.get("price"):
        price = float(quote["price"])
    else:
        # 価格取得失敗時は market_data の終値を使用
        from src.data.market_data import get_ohlcv_data

        df, _ = get_ohlcv_data(symbol, 30)
        price = float(df["close"].iloc[-1])

    record = _save_order(
        symbol, side, units, "FILLED", price, "paper", f"paper-{datetime.now().timestamp():.0f}", tenant_id
    )
    if stop_loss is not None:
        record["stop_loss"] = stop_loss
    if take_profit is not None:
        record["take_profit"] = take_profit
    return record


def _save_order(
    symbol: str,
    side: str,
    units: int,
    status: str,
    fill_price: float | None,
    broker: str,
    external_id: str,
    tenant_id: int | None = None,
) -> dict:
    """注文レコードを DB に保存して返す。

    DB への書き込みに失敗した場合はインメモリリストに保存し、
    処理を継続する。

    Args:
        symbol: 通貨ペアコード
        side: 注文方向
        units: 注文数量
        status: 注文状態（"FILLED", "SUBMITTED" 等）
        fill_price: 約定価格（None の場合は未約定）
        broker: ブローカー識別子（"oanda" または "paper"）
        external_id: ブローカー側の注文/約定 ID
        tenant_id: テナント ID

    Returns:
        保存された注文情報の辞書（DB 保存成功時は id を含む）
    """
    _ensure_table()
    record = {
        "symbol": symbol,
        "side": side,
        "units": units,
        "order_type": "MARKET",
        "status": status,
        "fill_price": fill_price,
        "broker": broker,
        "external_id": external_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    db = SessionLocal()
    try:
        row = BrokerOrder(
            symbol=symbol,
            side=side,
            units=units,
            status=status,
            fill_price=fill_price,
            broker=broker,
            external_id=external_id,
            tenant_id=tenant_id,
            created_at=datetime.now(timezone.utc),
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        record["id"] = row.id
    except Exception as e:
        # DB 書き込み失敗時はロールバックしてインメモリに保存
        logger.warning("order save: %s", e)
        db.rollback()
        _memory_orders.insert(0, record)
        record["id"] = len(_memory_orders)
    finally:
        db.close()
    return record


def list_orders(limit: int = 20, tenant_id: int | None = None) -> list[dict]:
    """直近の注文一覧を取得する。

    DB から created_at 降順で取得し、失敗時はインメモリリストを返す。

    Args:
        limit: 取得件数の上限（デフォルト: 20）
        tenant_id: テナント ID でフィルタリング（None は全テナント）

    Returns:
        注文情報の辞書リスト（created_at の降順）
    """
    _ensure_table()
    db = SessionLocal()
    try:
        q = select(BrokerOrder).order_by(desc(BrokerOrder.created_at)).limit(limit)
        if tenant_id is not None:
            q = q.where(BrokerOrder.tenant_id == tenant_id)
        rows = db.execute(q).scalars().all()
        if rows:
            return [
                {
                    "id": r.id,
                    "symbol": r.symbol,
                    "side": r.side,
                    "units": r.units,
                    "status": r.status,
                    "fill_price": float(r.fill_price) if r.fill_price else None,
                    "broker": r.broker,
                    "external_id": r.external_id,
                    "created_at": r.created_at.isoformat() if r.created_at else None,
                }
                for r in rows
            ]
    except Exception as e:
        logger.warning("list_orders: %s", e)
    finally:
        db.close()
    # DB 失敗時はインメモリから返す
    return _memory_orders[:limit]
