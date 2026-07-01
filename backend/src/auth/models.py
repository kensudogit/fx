"""
SaaS テナント・ユーザー・API キーの ORM モデルと利用実績管理モジュール。

マルチテナント SaaS アーキテクチャの中核となるデータモデルを定義する。
テナント（組織）> ユーザー（個人）という 2 層構造で、1 テナントが複数ユーザーを持てる。
API キーはテナント単位で発行され、プランにより発行可能数が制限される。
利用実績（UsageEvent）は API コールごとに記録され、1日の利用上限チェックに使用される。
"""

import logging
from datetime import datetime, timezone

from sqlalchemy import (
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    func,
    select,
)
from sqlalchemy.orm import relationship

from src.db.database import Base, SessionLocal, engine

logger = logging.getLogger(__name__)


class Tenant(Base):
    """
    テナント（組織・ワークスペース）モデル。

    SaaS のマルチテナント管理において最上位の単位。
    1 テナントが 1 つのサブスクリプション（プラン）を持ち、
    複数のユーザーと複数の API キーを所有する。
    Stripe との連携情報（顧客ID・サブスクリプションID）もここに保存する。

    Attributes:
        id: テナント固有 ID（主キー、自動採番）。
        name: テナント名（組織名）。最大 120 文字。
        slug: URL フレンドリーな識別子（一意）。最大 80 文字。
        plan: 現在のサブスクリプションプラン。"free" / "pro" / "enterprise" のいずれか。
        stripe_customer_id: Stripe 顧客 ID（課金管理用）。
        stripe_subscription_id: Stripe サブスクリプション ID（継続課金管理用）。
        created_at: テナント作成日時（UTC）。
        users: このテナントに属するユーザーのリスト（リレーション）。
        api_keys: このテナントが発行した API キーのリスト（リレーション）。
    """

    __tablename__ = "tenants"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(120), nullable=False)
    slug = Column(String(80), nullable=False, unique=True)
    # プラン名: "free" / "pro" / "enterprise" のいずれか（plans.py で定義）
    plan = Column(String(20), nullable=False, default="free")
    # Stripe 顧客 ID（例: "cus_XXXXXXXXXXXXXXXX"）。Stripe 未利用時は NULL。
    stripe_customer_id = Column(String(100))
    # Stripe サブスクリプション ID（例: "sub_XXXXXXXXXXXXXXXX"）。無料プランでは NULL。
    stripe_subscription_id = Column(String(100))
    # タイムゾーン情報付きの作成日時（UTC で保存）
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))

    # テナントに属するユーザーの双方向リレーション
    users = relationship("User", back_populates="tenant")
    # テナントが保有する API キーの双方向リレーション
    api_keys = relationship("TenantApiKey", back_populates="tenant")


class User(Base):
    """
    ユーザー（アカウント）モデル。

    各ユーザーは必ず 1 つのテナントに属する（外部キー制約）。
    メールアドレスはシステム全体で一意（ユニーク制約）。
    パスワードは bcrypt でハッシュ化して保存し、生のパスワードは一切保存しない。

    Attributes:
        id: ユーザー固有 ID（主キー、自動採番）。
        tenant_id: 所属テナントの ID（外部キー）。
        email: メールアドレス（一意制約付き）。ログインの識別子。
        password_hash: bcrypt ハッシュ化されたパスワード。最大 255 文字。
        role: ユーザーの権限ロール。"owner" がテナント管理者。
        created_at: ユーザー作成日時（UTC）。
        tenant: 所属テナントへの双方向リレーション。
    """

    __tablename__ = "users"
    # メールアドレスのグローバル一意制約（同一メールで複数テナント登録を防ぐ）
    __table_args__ = (UniqueConstraint("email", name="uq_users_email"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    # テナントが削除されると関連ユーザーも参照不能になる（CASCADE は DB 設定に依存）
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False)
    email = Column(String(255), nullable=False)
    # bcrypt ハッシュ（"$2b$12$..." 形式）。生のパスワードは絶対に保存しない。
    password_hash = Column(String(255), nullable=False)
    # デフォルトは "owner"（テナント作成者は自動的にオーナー権限を持つ）
    role = Column(String(20), nullable=False, default="owner")
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))

    tenant = relationship("Tenant", back_populates="users")


class TenantApiKey(Base):
    """
    テナント API キーモデル。

    API キーはプログラムからのアクセスに使用する長期有効なトークン。
    セキュリティのため、生のキー（raw_key）はレスポンス時のみ返し、
    DB には SHA-256 ハッシュのみ保存する（一方向ハッシュで逆算不能）。
    key_prefix は「どのキーか」を視覚的に識別するための先頭 12 文字（例: "fx_AbCdEfGhIj..."）。

    Attributes:
        id: API キー固有 ID（主キー、自動採番）。
        tenant_id: 発行元テナントの ID（外部キー）。
        name: キーの用途を示す名前（例: "Production", "CI/CD"）。
        key_prefix: キーの先頭 12 文字 + "..."（識別用、機密ではない）。
        key_hash: 生キーの SHA-256 ハッシュ値（64 文字の hex 文字列）。照合に使用。
        last_used_at: 最終使用日時（UTC）。利用状況の把握に使用。
        created_at: キー作成日時（UTC）。
        tenant: 発行元テナントへの双方向リレーション。
    """

    __tablename__ = "tenant_api_keys"

    id = Column(Integer, primary_key=True, autoincrement=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False)
    name = Column(String(80), nullable=False, default="Default")
    # 先頭12文字 + "..."（例: "fx_AbCdEfGhIj..."）— DB 流出時も生のキーは特定できない
    key_prefix = Column(String(20), nullable=False)
    # SHA-256 ハッシュ（64 文字の hex）— 生のキーはここに保存しない
    key_hash = Column(String(64), nullable=False)
    # 使用されるたびに更新される（長期未使用キーの検出に活用できる）
    last_used_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))

    tenant = relationship("Tenant", back_populates="api_keys")


class UsageEvent(Base):
    """
    API 利用イベント記録モデル。

    各 API コールの成功時に 1 レコードを追加する、追記専用のログテーブル。
    1日の利用上限チェック（count_daily_usage）はこのテーブルを集計して行う。
    将来的には課金計算・分析ダッシュボード・不正利用検知にも活用できる。

    Attributes:
        id: イベント固有 ID（主キー、自動採番）。
        tenant_id: 呼び出し元テナントの ID（外部キー）。
        event_type: イベント種別。現在は "api_call" のみ。
        path: 呼び出された API パス（最大 200 文字）。
        created_at: イベント発生日時（UTC）。利用上限の集計基準。
    """

    __tablename__ = "usage_events"

    id = Column(Integer, primary_key=True, autoincrement=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False)
    # 将来の拡張に備えてイベント種別を持つ（現在は "api_call" のみ使用）
    event_type = Column(String(40), nullable=False, default="api_call")
    # 呼び出された API パス（分析用）。200 文字で切り詰める（record_usage 参照）。
    path = Column(String(200))
    # タイムゾーン付き日時（UTC 保存）。1日の集計は UTC 0:00 基準で行う。
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))


def init_auth_tables():
    """
    認証関連テーブルを初期化する。

    アプリ起動時や初回リクエスト時に呼び出し、テーブルが存在しない場合のみ作成する
    （checkfirst=True で既存テーブルを壊さない）。
    また、ALTER TABLE で後から追加されたカラム（stripe_subscription_id 等）の
    マイグレーションも行う（IF NOT EXISTS で冪等）。

    Raises:
        なし（例外はキャッチして warning ログに記録し、処理を継続する）。
    """
    try:
        # checkfirst=True: テーブルが既に存在する場合はスキップ（冪等）
        Tenant.__table__.create(engine, checkfirst=True)
        User.__table__.create(engine, checkfirst=True)
        TenantApiKey.__table__.create(engine, checkfirst=True)
        UsageEvent.__table__.create(engine, checkfirst=True)
        from sqlalchemy import text

        # stripe_subscription_id カラムの追加マイグレーション
        # IF NOT EXISTS で既に存在する場合はスキップ（PostgreSQL 9.6+）
        with engine.begin() as conn:
            conn.execute(
                text("ALTER TABLE tenants ADD COLUMN IF NOT EXISTS stripe_subscription_id VARCHAR(100)")
            )
    except Exception as e:
        # テーブル作成失敗は致命的ではない（既存環境では正常）
        logger.warning("auth tables init: %s", e)


def count_daily_usage(tenant_id: int) -> int:
    """
    指定テナントの本日（UTC 基準）の API 利用回数を返す。

    UsageEvent テーブルから当日 UTC 0:00 以降のレコード数を集計する。
    ミドルウェアがリクエストごとに呼び出すため、軽量な COUNT クエリを使用。

    Args:
        tenant_id: 集計対象のテナント ID。

    Returns:
        int: 当日の API 呼び出し回数。レコードなしの場合は 0。
    """
    db = SessionLocal()
    try:
        # 当日 UTC 0:00:00 を基準とした集計開始点を計算
        start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        # COUNT(*) 集計クエリ（フルスキャンを避けるため tenant_id + created_at に複合インデックス推奨）
        q = select(func.count()).select_from(UsageEvent).where(
            UsageEvent.tenant_id == tenant_id,
            UsageEvent.created_at >= start,
        )
        return int(db.execute(q).scalar() or 0)
    finally:
        db.close()


def record_usage(tenant_id: int, path: str, event_type: str = "api_call") -> None:
    """
    API 呼び出しの利用実績を UsageEvent テーブルに記録する。

    ミドルウェアがレスポンス成功後（status_code < 400）に呼び出す。
    書き込みエラーは無視してロールバックし、アプリの正常動作を優先する。

    Args:
        tenant_id: 記録対象のテナント ID。
        path: 呼び出された API パス（200 文字を超える場合は切り詰める）。
        event_type: イベント種別（デフォルト: "api_call"）。

    Returns:
        None。エラー時もサイレントに失敗する（ログ出力なし）。
    """
    db = SessionLocal()
    try:
        # path は最大 200 文字に切り詰め（DB カラムの長さ制限に合わせる）
        db.add(UsageEvent(tenant_id=tenant_id, event_type=event_type, path=path[:200]))
        db.commit()
    except Exception:
        # 利用記録の失敗はアプリの主要機能に影響させないためロールバックのみ
        db.rollback()
    finally:
        db.close()
