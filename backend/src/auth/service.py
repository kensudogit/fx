"""
認証・テナント登録サービスモジュール。

このモジュールはデータベースを介した認証ビジネスロジックを実装する:
  - テナント（組織）の新規登録とオーナーユーザーの作成
  - メールアドレス・パスワードによるログイン認証
  - ログインユーザー自身の情報・利用状況取得
  - API キーの解決（X-API-Key ヘッダーからテナントを特定）
  - API キーの作成・一覧取得
  - プランのアップグレード・ダウングレード

セキュリティ設計:
  - パスワードは bcrypt で一方向ハッシュ化（平文は保持しない）
  - メール不存在とパスワード不一致を同一メッセージで返す（ユーザー列挙攻撃対策）
  - API キーは SHA-256 ハッシュのみ DB 保存（生のキーは作成時のみ返す）
"""

import re
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.ai.chat import init_chat_tables
from src.auth.models import Tenant, TenantApiKey, User, count_daily_usage, init_auth_tables
from src.auth.plans import daily_limit, plan_features
from src.auth.security import (
    api_key_prefix,
    create_access_token,
    generate_api_key,
    hash_api_key,
    hash_password,
    verify_password,
)
from src.config import settings
from src.db.database import SessionLocal


@dataclass
class TenantContext:
    """
    認証済みリクエストのテナントコンテキストデータクラス。

    ミドルウェアがリクエストごとに生成し、request.state.tenant と
    ContextVar（context.py）に格納する。JWT 認証と API キー認証の
    両方をこのデータクラスで統一的に扱う。

    Attributes:
        tenant_id: テナントの一意 ID。すべての DB クエリのフィルタに使用。
        tenant_slug: テナントの URL フレンドリー識別子（例: "my-company"）。
        plan: テナントの現在のプラン（"free" / "pro" / "enterprise"）。
        user_id: ログインユーザーの ID。API キー認証では None。
        email: ユーザーのメールアドレス。API キー認証では None。
        role: ユーザーロール（"owner" 等）。API キー認証では None。
        auth_via: 認証方式。"jwt" または "api_key" のいずれか。
                  _require_owner でのロールチェック判定に使用。
    """

    tenant_id: int
    tenant_slug: str
    plan: str
    user_id: int | None = None   # JWT 認証時のみ設定される
    email: str | None = None     # JWT 認証時のみ設定される
    role: str | None = None      # JWT 認証時のみ設定される
    auth_via: str = "jwt"        # デフォルトは JWT 認証


def _slugify(name: str) -> str:
    """
    組織名から URL フレンドリーなスラグ文字列を生成する内部ヘルパー。

    変換ルール:
      1. 小文字に変換
      2. 英数字以外の連続文字をハイフン 1 つに置換
      3. 先頭・末尾のハイフンを除去
      4. 最大 60 文字に切り詰め
      5. 空文字列になった場合は "workspace" にフォールバック

    例: "My Company!" → "my-company"
        "株式会社ABC" → "abc"（日本語は除去される）

    Args:
        name: 組織名文字列（任意の文字を含む可能性がある）。

    Returns:
        str: URL フレンドリーなスラグ文字列（英数字とハイフンのみ）。
    """
    # 英数字・ハイフン以外の文字をハイフンに置換し、連続するハイフンも 1 つにまとめる
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    # 60 文字で切り詰め、空の場合は "workspace" をデフォルトとする
    return slug[:60] or "workspace"


def register_tenant(db: Session, email: str, password: str, org_name: str) -> dict:
    """
    新規テナント（組織）とオーナーユーザーを登録する。

    処理フロー:
      1. 認証テーブルの初期化確認（init_auth_tables）
      2. メールアドレスの重複チェック
      3. 組織名からスラグを生成（重複時は連番サフィックスを付加）
      4. Tenant レコードを DB に追加（flush で ID を取得）
      5. User レコードを DB に追加（パスワードをハッシュ化して保存）
      6. コミット後に JWT アクセストークンを生成
      7. トークン・ユーザー情報・テナント情報を返す

    Args:
        db: SQLAlchemy データベースセッション。
        email: 登録するメールアドレス（小文字に正規化）。
        password: 生のパスワード（bcrypt でハッシュ化して保存）。
        org_name: 組織名（テナント名）。

    Returns:
        dict: access_token, token_type, user, tenant を含む辞書。
              ユーザーは登録直後からログイン済み状態になる。

    Raises:
        ValueError: メールアドレスが既に登録されている場合。
    """
    # テーブルが存在しない場合は作成する（初回起動時の安全ネット）
    init_auth_tables()
    # メールアドレスを小文字に正規化（大文字小文字の違いで重複を防ぐ）
    email = email.strip().lower()
    # メールアドレスの重複チェック（一意制約が DB にもあるが、より分かりやすいエラーを返す）
    existing = db.execute(select(User).where(User.email == email)).scalar_one_or_none()
    if existing:
        raise ValueError("このメールアドレスは既に登録されています")

    # ─── スラグの一意性確保 ─────────────────────────────────
    base_slug = _slugify(org_name)
    slug = base_slug
    n = 1
    # 同名テナントが既に存在する場合は "-1", "-2", ... と連番サフィックスを付加
    while db.execute(select(Tenant).where(Tenant.slug == slug)).scalar_one_or_none():
        slug = f"{base_slug}-{n}"
        n += 1

    # ─── テナントレコードの作成 ─────────────────────────────────
    # デフォルトプランは設定ファイルで指定（通常は "free"）
    tenant = Tenant(name=org_name.strip(), slug=slug, plan=settings.saas_default_plan)
    db.add(tenant)
    # flush で SQL を実行して tenant.id を取得（commit はまだしない）
    # これにより user.tenant_id に設定できる
    db.flush()

    # ─── ユーザーレコードの作成 ─────────────────────────────────
    user = User(
        tenant_id=tenant.id,
        email=email,
        password_hash=hash_password(password),  # bcrypt でハッシュ化（生のパスワードは保存しない）
        role="owner",  # テナント作成者は自動的にオーナー権限を付与
    )
    db.add(user)
    db.commit()          # テナントとユーザーを同時にコミット（トランザクション整合性）
    db.refresh(user)     # コミット後のデータ（id, created_at 等）を再取得
    db.refresh(tenant)

    # ─── JWT トークンの発行 ─────────────────────────────────────
    # 登録直後にトークンを発行することで、別途ログイン操作を不要にする（UX 向上）
    token = create_access_token(user.id, tenant.id, user.email, user.role)
    return {
        "access_token": token,
        "token_type": "bearer",       # OAuth 2.0 標準の Bearer トークン方式
        "user": _user_payload(user),
        "tenant": _tenant_payload(tenant),
    }


def login_user(db: Session, email: str, password: str) -> dict:
    """
    メールアドレスとパスワードで認証し、JWT アクセストークンを返す。

    セキュリティのため、メールアドレスが存在しない場合とパスワードが不一致の場合を
    同一のエラーメッセージで返す（ユーザー列挙攻撃: 攻撃者がメールの存在を確認できないように）。

    Args:
        db: SQLAlchemy データベースセッション。
        email: ログインに使用するメールアドレス（小文字に正規化）。
        password: 生のパスワード（bcrypt で照合）。

    Returns:
        dict: access_token, token_type, user, tenant を含む辞書。

    Raises:
        ValueError: 認証失敗（メールアドレスまたはパスワードが不正）の場合。
                    メール不存在とパスワード不一致を区別しない（セキュリティ設計）。
    """
    # テーブルが存在しない場合は作成する（安全ネット）
    init_auth_tables()
    email = email.strip().lower()
    user = db.execute(select(User).where(User.email == email)).scalar_one_or_none()
    # ユーザーが存在しない場合と、パスワードが不一致の場合を同一メッセージで返す
    # （ユーザー列挙攻撃: 攻撃者が特定メールの登録状態を確認できないようにする）
    if not user or not verify_password(password, user.password_hash):
        raise ValueError("メールアドレスまたはパスワードが正しくありません")

    tenant = db.get(Tenant, user.tenant_id)
    # JWT にテナントとユーザーの情報を埋め込む
    token = create_access_token(user.id, tenant.id, user.email, user.role)
    return {
        "access_token": token,
        "token_type": "bearer",
        "user": _user_payload(user),
        "tenant": _tenant_payload(tenant),
    }


def get_me(db: Session, user_id: int) -> dict:
    """
    ログインユーザー自身の詳細情報・利用状況・フィーチャーフラグを返す。

    フロントエンドのダッシュボードで以下を表示するために使用:
      - ユーザー情報（メール・ロール）
      - テナント情報（プラン・Stripe 連携状態）
      - API 利用状況（今日の呼び出し回数・残回数・使用率）
      - 利用可能な機能のフィーチャーフラグ（UI の表示制御に使用）

    Args:
        db: SQLAlchemy データベースセッション。
        user_id: 取得対象のユーザー ID（JWT の sub クレームから取得）。

    Returns:
        dict: user, tenant, usage（利用状況）, features, billing を含む辞書。

    Raises:
        ValueError: ユーザーが見つからない場合（論理的にはほぼ発生しない）。
    """
    user = db.get(User, user_id)
    if not user:
        raise ValueError("User not found")
    tenant = db.get(Tenant, user.tenant_id)

    # ─── 利用状況の計算 ─────────────────────────────────────────
    usage = count_daily_usage(tenant.id)
    limit = daily_limit(tenant.plan)
    remaining = max(0, limit - usage)       # 残回数（マイナスにならないよう max で保護）
    # 使用率（%）: 上限 0 の場合はゼロ除算を避けて 0% とする
    pct = round((usage / limit) * 100, 1) if limit else 0

    # ─── 利用レベルの判定 ───────────────────────────────────────
    # フロントエンドの UI（プログレスバーの色等）に使用する利用状況レベル
    if remaining <= 0:
        usage_level = "exhausted"  # 上限到達（赤・警告表示）
    elif pct >= 90:
        usage_level = "critical"   # 90%以上使用（オレンジ・注意表示）
    elif pct >= 75:
        usage_level = "warning"    # 75%以上使用（黄色・注意表示）
    else:
        usage_level = "ok"         # 通常状態（緑・問題なし）

    return {
        "user": _user_payload(user),
        "tenant": _tenant_payload(tenant),
        "usage": {
            "daily_calls": usage,
            "daily_limit": limit,
            "remaining": remaining,
            "usage_percent": pct,
            "usage_level": usage_level,
        },
        "features": plan_features(tenant.plan),  # プランに応じたフィーチャーフラグ
        "billing": {
            # Stripe 顧客 ID・サブスクリプション ID の有無（True/False で返す）
            # 実際の ID 値は返さない（フロントエンドに不要かつセキュリティ上も不要）
            "stripe_customer": bool(tenant.stripe_customer_id),
            "stripe_subscription": bool(tenant.stripe_subscription_id),
        },
    }


def resolve_api_key(db: Session, raw_key: str) -> TenantContext | None:
    """
    生の API キー文字列からテナントコンテキストを解決する。

    処理フロー:
      1. "fx_" プレフィックスチェック（即時フィルタリング）
      2. SHA-256 ハッシュ化して DB の key_hash と照合
      3. 一致した TenantApiKey と Tenant を結合取得
      4. 最終使用日時を更新
      5. TenantContext を返す

    Args:
        db: SQLAlchemy データベースセッション。
        raw_key: リクエストヘッダーから取得した生の API キー文字列。

    Returns:
        TenantContext: API キーに対応するテナントのコンテキスト。
                       キーが無効または存在しない場合は None。
    """
    # "fx_" プレフィックスがない場合は即座に None を返す（DB クエリを節約）
    if not raw_key.startswith("fx_"):
        return None
    # 生のキーを SHA-256 ハッシュ化して DB の key_hash カラムと照合する
    # （DB には生のキーを保存しないため、ハッシュで比較する）
    key_hash = hash_api_key(raw_key)
    # TenantApiKey と Tenant を JOIN して一度のクエリで両方取得する（N+1 回避）
    row = db.execute(
        select(TenantApiKey, Tenant)
        .join(Tenant, Tenant.id == TenantApiKey.tenant_id)
        .where(TenantApiKey.key_hash == key_hash)
    ).first()
    if not row:
        return None
    api_key_row, tenant = row
    # 最終使用日時を現在時刻で更新（長期未使用キーの検出・監査に使用）
    api_key_row.last_used_at = datetime.now(timezone.utc)
    db.commit()
    # API キー認証では user_id・email・role は特定できないため None のまま
    return TenantContext(
        tenant_id=tenant.id,
        tenant_slug=tenant.slug,
        plan=tenant.plan,
        auth_via="api_key",    # 認証方式を "api_key" に設定（ロールチェックで参照）
    )


def create_api_key(db: Session, tenant_id: int, name: str) -> dict:
    """
    テナントの新しい API キーを生成して返す。

    セキュリティのため、生の API キー（raw）はこの関数の返り値に 1 度だけ含まれる。
    DB には SHA-256 ハッシュのみ保存し、生のキーは保存しない。
    再表示はできないため、フロントエンドはユーザーに保存を促す UI を表示すること。

    プランごとに発行可能な API キーの最大数が制限されている（plans.py 参照）:
      - free: 1 本、pro: 5 本、enterprise: 50 本

    Args:
        db: SQLAlchemy データベースセッション。
        tenant_id: API キーを発行するテナントの ID。
        name: キーの用途を示す名前（例: "Production"、"CI/CD"）。

    Returns:
        dict: id, name, key_prefix, api_key（生の値・1回のみ）, created_at を含む辞書。

    Raises:
        ValueError: テナントが存在しない場合、または API キーの発行上限に達した場合。
    """
    tenant = db.get(Tenant, tenant_id)
    if not tenant:
        raise ValueError("Tenant not found")
    # プランの API キー上限数を取得（features["api_keys"]、デフォルト 1）
    max_keys = plan_features(tenant.plan).get("api_keys", 1)
    # 現在のキー数をカウント
    count = len(db.execute(select(TenantApiKey).where(TenantApiKey.tenant_id == tenant_id)).scalars().all())
    if count >= max_keys:
        raise ValueError(f"APIキー上限 ({max_keys}) に達しています。プランをアップグレードしてください。")

    # ─── API キーの生成・保存 ──────────────────────────────────
    # 1. 暗号学的に安全なランダムキーを生成
    raw = generate_api_key()
    row = TenantApiKey(
        tenant_id=tenant_id,
        name=name.strip() or "API Key",          # 空の場合はデフォルト名を使用
        key_prefix=api_key_prefix(raw),            # 先頭12文字+...（識別用）
        key_hash=hash_api_key(raw),               # SHA-256 ハッシュ（照合用）
        # raw（生のキー）は DB に保存しない
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return {
        "id": row.id,
        "name": row.name,
        "key_prefix": row.key_prefix,
        "api_key": raw,   # 生のキー: この返り値のみで確認可能（再表示不可）
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


def list_api_keys(db: Session, tenant_id: int) -> list[dict]:
    """
    テナントが保有する API キーの一覧を返す。

    セキュリティのため、生の API キー値は含めない。
    プレフィックス（先頭12文字）と最終使用日時のみを返す。

    Args:
        db: SQLAlchemy データベースセッション。
        tenant_id: 一覧取得対象のテナント ID。

    Returns:
        list[dict]: 各キーの id, name, key_prefix, last_used_at, created_at を含む辞書のリスト。
    """
    rows = db.execute(select(TenantApiKey).where(TenantApiKey.tenant_id == tenant_id)).scalars().all()
    return [
        {
            "id": r.id,
            "name": r.name,
            "key_prefix": r.key_prefix,
            # ISO 8601 形式の日時文字列（使用なし=None は null として返す）
            "last_used_at": r.last_used_at.isoformat() if r.last_used_at else None,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in rows
    ]


def upgrade_plan(db: Session, tenant_id: int, plan: str) -> dict:
    """
    テナントのプランを変更する。

    Stripe 未設定の開発・デモ環境での直接プラン変更と、
    Stripe Webhook 経由でのプラン自動更新の両方で使用される。
    Stripe Checkout 経由の場合は handle_stripe_webhook 内から呼び出される。

    Args:
        db: SQLAlchemy データベースセッション。
        tenant_id: プラン変更対象のテナント ID。
        plan: 変更先プラン名（"free" / "pro" / "enterprise"）。

    Returns:
        dict: 更新後のテナント情報（_tenant_payload の形式）。

    Raises:
        ValueError: 無効なプラン名またはテナントが見つからない場合。
    """
    # 有効なプラン名のホワイトリスト検証（不正なプラン設定を防ぐ）
    if plan not in ("free", "pro", "enterprise"):
        raise ValueError("Invalid plan")
    tenant = db.get(Tenant, tenant_id)
    if not tenant:
        raise ValueError("Tenant not found")
    # プランを更新してコミット
    tenant.plan = plan
    db.commit()
    db.refresh(tenant)
    return _tenant_payload(tenant)


def _user_payload(user: User) -> dict:
    """
    User モデルから API レスポンス用の辞書を生成する内部ヘルパー。

    password_hash 等の機密フィールドは含めない。

    Args:
        user: User ORM オブジェクト。

    Returns:
        dict: id, email, role, tenant_id を含む辞書。
    """
    return {"id": user.id, "email": user.email, "role": user.role, "tenant_id": user.tenant_id}


def _tenant_payload(tenant: Tenant) -> dict:
    """
    Tenant モデルから API レスポンス用の辞書を生成する内部ヘルパー。

    Stripe の ID 値は機密ではないが、stripe_subscription_id は bool で返す
    （サブスクリプションの有無をフロントエンドが判断できれば十分）。

    Args:
        tenant: Tenant ORM オブジェクト。

    Returns:
        dict: id, name, slug, plan, stripe_customer_id, has_stripe_subscription を含む辞書。
    """
    return {
        "id": tenant.id,
        "name": tenant.name,
        "slug": tenant.slug,
        "plan": tenant.plan,
        "stripe_customer_id": tenant.stripe_customer_id,
        # サブスクリプション ID の有無を bool で返す（実際の ID は不要）
        "has_stripe_subscription": bool(tenant.stripe_subscription_id),
    }


def bootstrap_auth():
    """
    アプリケーション起動時の認証・チャットテーブル初期化処理。

    アプリ起動時（main.py 等の lifespan イベント）から呼び出し、
    必要なテーブルをすべて初期化する。冪等な処理のため複数回呼び出しても安全。

    処理内容:
      - 認証関連テーブル（tenants, users, tenant_api_keys, usage_events）の初期化
      - AI チャット関連テーブルの初期化
    """
    init_auth_tables()  # 認証テーブルの初期化（checkfirst=True で冪等）
    init_chat_tables()  # AI チャットテーブルの初期化
