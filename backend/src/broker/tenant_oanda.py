"""
テナント別 OANDA 口座設定モジュール

マルチテナント環境において各テナントの OANDA API 認証情報を
安全に管理するモジュール。

認証情報の解決優先順位:
    1. テナント固有の設定（DB の tenant_oanda_settings テーブル）
    2. グローバル環境変数（settings.oanda_api_token 等）
    3. ペーパー取引モード（認証情報なし）

セキュリティ:
    - API トークンは暗号化して DB に保存（encrypt_secret / decrypt_secret）
    - 外部への表示時はマスク処理（"abcd...wxyz" 形式）
    - trading_mode="paper" の場合は常にペーパーモード（認証情報を使わない）

マルチテナント対応:
    - 各テナントは独自の OANDA アカウント（practice または live）を持てる
    - テナント設定がない場合はグローバル設定にフォールバック
    - practice 環境のテナントが live モードをリクエストしても practice を返す（安全策）
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, select

# API トークンの暗号化・復号化ユーティリティ
from src.auth.secrets import decrypt_secret, encrypt_secret
# グローバル OANDA 設定（環境変数から読み込み）
from src.config import settings
from src.db.database import Base, SessionLocal, engine

logger = logging.getLogger(__name__)


class TenantOandaSettings(Base):
    """テナント別 OANDA 設定の ORM モデル。

    テーブル名: tenant_oanda_settings

    属性:
        tenant_id: テナント ID（主キー兼 tenants テーブルの外部キー）
        api_token: 暗号化された OANDA API トークン（encrypt_secret で暗号化済み）
        account_id: OANDA の口座 ID（例: "001-009-12345678-001"）
        environment: 取引環境（"practice" または "live"）
        updated_at: 最終更新日時（UTC）

    制約:
        - tenant_id は tenants テーブルを参照し、CASCADE 削除対応
        - api_token は暗号化して保存するため平文で読み出し不可
    """

    __tablename__ = "tenant_oanda_settings"

    tenant_id = Column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"), primary_key=True)
    api_token = Column(String(500))
    account_id = Column(String(50))
    environment = Column(String(20), default="practice")
    updated_at = Column(DateTime(timezone=True), nullable=False)


@dataclass
class OandaCredentials:
    """OANDA 認証情報を保持するデータクラス。

    resolve_oanda_credentials() の戻り値として使用される。

    属性:
        configured: 有効な認証情報が揃っているか（False の場合はペーパー取引）
        mode: 取引環境（"live", "practice", "paper"）
        api_token: OANDA API トークン（configured=False の場合は None）
        account_id: OANDA 口座 ID（configured=False の場合は None）
        source: 認証情報の取得元（"tenant", "global", "paper"）
    """

    configured: bool
    mode: str
    api_token: str | None
    account_id: str | None
    source: str


def _ensure_table():
    """tenant_oanda_settings テーブルが存在しない場合に作成する。"""
    try:
        TenantOandaSettings.__table__.create(engine, checkfirst=True)
    except Exception as e:
        logger.warning("tenant_oanda_settings table: %s", e)


def _mask_token(token: str | None) -> str | None:
    """API トークンをマスクして安全に表示できる形式に変換する。

    トークンの先頭4文字と末尾4文字のみを表示し、
    中間部分を "..." で隠す（ログやレスポンスで平文を露出しないため）。

    Args:
        token: マスクする API トークン

    Returns:
        マスクされたトークン（例: "abcd...wxyz"）。
        None または8文字以下の場合は "****" を返す。
    """
    if not token:
        return None
    if len(token) <= 8:
        return "****"
    return f"{token[:4]}...{token[-4:]}"


def get_tenant_oanda_settings(tenant_id: int) -> dict | None:
    """テナントの OANDA 設定を取得する（API トークンはマスク済み）。

    外部 API レスポンスとして返すため、API トークンはマスクして返す。
    設定が存在しない場合は None を返す。

    Args:
        tenant_id: テナント ID

    Returns:
        OANDA 設定の辞書（api_token は "api_token_masked" としてマスク表示）、
        または設定が存在しない場合は None
    """
    _ensure_table()
    db = SessionLocal()
    try:
        row = db.get(TenantOandaSettings, tenant_id)
        if not row:
            return None
        return {
            "tenant_id": tenant_id,
            "account_id": row.account_id,
            "environment": row.environment or "practice",
            # API トークンが設定されているかの boolean フラグ（平文は返さない）
            "api_token_set": bool(row.api_token),
            # マスク済みトークン（UI 表示用）
            "api_token_masked": _mask_token(row.api_token),
            "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        }
    finally:
        db.close()


def save_tenant_oanda_settings(
    tenant_id: int,
    *,
    api_token: str | None = None,
    account_id: str | None = None,
    environment: str | None = None,
    clear_token: bool = False,
) -> dict:
    """テナントの OANDA 設定を保存・更新する。

    既存のレコードがある場合は更新、ない場合は新規作成する。
    API トークンは暗号化して DB に保存する（平文では保存しない）。

    Args:
        tenant_id: テナント ID
        api_token: OANDA API トークン（平文。None の場合は変更なし）
        account_id: OANDA 口座 ID（None の場合は変更なし）
        environment: 取引環境（"practice" または "live"）
        clear_token: True の場合、API トークンを削除してペーパーモードに戻す

    Returns:
        更新後の設定辞書（get_tenant_oanda_settings の戻り値と同形式）

    Raises:
        ValueError: environment が "practice" または "live" 以外の場合
        Exception: DB エラー発生時（ロールバックして再送出）
    """
    _ensure_table()
    now = datetime.now(timezone.utc)
    env = (environment or "practice").lower()
    if env not in ("practice", "live"):
        raise ValueError("environment must be practice or live")

    db = SessionLocal()
    try:
        row = db.get(TenantOandaSettings, tenant_id)
        if not row:
            # レコードが存在しない場合は新規作成
            row = TenantOandaSettings(tenant_id=tenant_id, updated_at=now)
            db.add(row)

        # 各フィールドを選択的に更新（None の場合は変更なし）
        if account_id is not None:
            row.account_id = account_id.strip() or None
        if environment is not None:
            row.environment = env
        if clear_token:
            # トークンクリア（ペーパーモードに戻す）
            row.api_token = None
        elif api_token is not None and api_token.strip():
            # API トークンを暗号化して保存（平文での保存を防ぐ）
            row.api_token = encrypt_secret(api_token.strip())

        row.updated_at = now
        db.commit()
        return get_tenant_oanda_settings(tenant_id) or {}
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def resolve_oanda_credentials(tenant_id: int | None, trading_mode: str = "paper") -> OandaCredentials:
    """取引モードとテナント ID に基づいて OANDA 認証情報を解決する。

    認証情報の解決優先順位:
        1. trading_mode="paper" → 常にペーパーモード（認証情報を無視）
        2. テナント固有設定（DB の tenant_oanda_settings）
        3. グローバル環境変数（settings.oanda_api_token）
        4. 設定なし → ペーパーモード

    環境（practice/live）の安全策:
        - テナントが practice 環境に設定しているのに live モードが要求された場合、
          practice に固定して live 注文を誤って出さないようにする

    Args:
        tenant_id: テナント ID（None はシングルテナント運用）
        trading_mode: "paper"（ペーパー）, "live"（本番）, "practice"（デモ）

    Returns:
        解決された OandaCredentials オブジェクト。
        configured=False の場合はペーパーモードとして扱う。
    """
    mode = (trading_mode or "paper").lower()

    # ペーパーモードの場合は認証情報を持たない OandaCredentials を即返す
    if mode == "paper":
        return OandaCredentials(
            configured=False,
            mode="paper",
            api_token=None,
            account_id=None,
            source="paper",
        )

    _ensure_table()

    # === テナント固有設定の確認 ===
    if tenant_id is not None:
        db = SessionLocal()
        try:
            row = db.get(TenantOandaSettings, tenant_id)
            if row and row.api_token and row.account_id:
                # 暗号化されたトークンを復号化
                token = decrypt_secret(row.api_token)
                if not token:
                    # 復号化失敗（キー変更等）→ ペーパーモードにフォールバック
                    return OandaCredentials(
                        configured=False,
                        mode="paper",
                        api_token=None,
                        account_id=None,
                        source="paper",
                    )
                env = row.environment or "practice"
                # 安全策: テナントが practice 環境なのに live モードを要求した場合は practice に固定
                if mode == "live" and env != "live":
                    env = "practice"
                return OandaCredentials(
                    configured=True,
                    mode=env,
                    api_token=token,
                    account_id=row.account_id,
                    source="tenant",  # テナント固有設定から取得
                )
        finally:
            db.close()

    # === グローバル環境変数の確認 ===
    if settings.oanda_api_token and settings.oanda_account_id:
        env = settings.oanda_environment
        # 安全策: グローバル設定が practice の場合は live を要求しても practice を返す
        if mode == "live" and env != "live":
            env = "practice"
        return OandaCredentials(
            configured=True,
            mode=env,
            api_token=settings.oanda_api_token,
            account_id=settings.oanda_account_id,
            source="global",  # グローバル環境変数から取得
        )

    # === 認証情報が見つからない場合 → ペーパーモードにフォールバック ===
    return OandaCredentials(
        configured=False,
        mode="paper",
        api_token=None,
        account_id=None,
        source="paper",
    )
