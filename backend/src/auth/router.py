"""
認証・課金 API ルーターモジュール。

SaaS テナント管理に必要な以下のエンドポイントを提供する:
  - /api/auth/*  : ユーザー登録・ログイン・自分の情報取得・API キー管理
  - /api/billing/*: プラン一覧・請求状況・Stripe Checkout/Portal・プランアップグレード・Webhook

Stripe との連携により、クレジットカード決済を安全に処理する。
すべての課金操作はオーナーロールのユーザーのみが実行できる（_require_owner 参照）。
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy.orm import Session

from src.auth.models import Tenant
from src.auth.plans import list_plans_public
from src.auth.service import (
    create_api_key,
    get_me,
    list_api_keys,
    login_user,
    register_tenant,
    upgrade_plan,
)
from src.billing.stripe_service import (
    billing_status,
    create_checkout_session,
    create_portal_session,
    handle_stripe_webhook,
    stripe_configured,
)
from src.config import settings
from src.db.database import get_db

logger = logging.getLogger(__name__)

# "SaaS" タグを付与してSwagger UI でグループ化する
router = APIRouter(tags=["SaaS"])


class RegisterBody(BaseModel):
    """
    ユーザー登録リクエストのリクエストボディスキーマ。

    Attributes:
        email: 登録するメールアドレス（Pydantic が形式を検証）。
        password: パスワード。8〜128 文字の制約（セキュリティポリシー）。
        org_name: 組織名（テナント名）。2〜120 文字の制約。
    """

    email: EmailStr
    # min_length=8: 短すぎるパスワードによる総当たり攻撃を防ぐ
    # max_length=128: bcrypt の 72 バイト制限を考慮した上限
    password: str = Field(min_length=8, max_length=128)
    org_name: str = Field(min_length=2, max_length=120)


class LoginBody(BaseModel):
    """
    ログインリクエストのリクエストボディスキーマ。

    Attributes:
        email: 登録済みのメールアドレス。
        password: パスワード（長さ制限なし — 認証時はハッシュ比較のみ）。
    """

    email: EmailStr
    password: str


class ApiKeyBody(BaseModel):
    """
    API キー作成リクエストのリクエストボディスキーマ。

    Attributes:
        name: キーの用途を示す名前（例: "Production", "CI/CD"）。
    """

    name: str = Field(default="API Key", max_length=80)


class PlanUpgradeBody(BaseModel):
    """
    プランアップグレード（または変更）リクエストのリクエストボディスキーマ。

    Attributes:
        plan: 変更先プラン名。"free" / "pro" / "enterprise" のみ受け付ける。
    """

    # regex バリデーションで想定外のプラン名を弾く
    plan: str = Field(pattern="^(free|pro|enterprise)$")


class CheckoutBody(BaseModel):
    """
    Stripe Checkout セッション作成リクエストのリクエストボディスキーマ。

    Attributes:
        plan: 購入するプラン（"pro" または "enterprise"）。free は課金不要のため除外。
        success_url: 決済成功後にリダイレクトする URL（省略時はデフォルトの設定画面）。
        cancel_url: 決済キャンセル後にリダイレクトする URL（省略時はデフォルトの設定画面）。
    """

    # free プランは Checkout 不要のため "pro" / "enterprise" のみ受け付ける
    plan: str = Field(pattern="^(pro|enterprise)$")
    success_url: str | None = None
    cancel_url: str | None = None


class PortalBody(BaseModel):
    """
    Stripe カスタマーポータルセッション作成リクエストのリクエストボディスキーマ。

    Stripe カスタマーポータルで請求書確認・プラン変更・キャンセルができる。

    Attributes:
        return_url: ポータルからの戻り先 URL（省略時はデフォルトの設定画面）。
    """

    return_url: str | None = None


def _current_user_id(request: Request) -> int:
    """
    現在のリクエストからログインユーザーの ID を取得する。

    API キー認証では user_id が存在しないため、この関数は JWT 認証のみ許可する。
    ユーザー固有の操作（自分の情報取得等）で使用する。

    Args:
        request: FastAPI の Request オブジェクト（ミドルウェアで tenant がセット済み）。

    Returns:
        int: ログインユーザーの ID。

    Raises:
        HTTPException: 未認証または API キー認証（user_id がない）の場合に 401。
    """
    tenant = getattr(request.state, "tenant", None)
    # API キー認証時は user_id が None になるため、JWT 認証を強制する
    if not tenant or not tenant.user_id:
        raise HTTPException(status_code=401, detail="JWT ログインが必要です")
    return tenant.user_id


def _current_tenant_id(request: Request) -> int:
    """
    現在のリクエストからテナント ID を取得する。

    JWT・API キーどちらの認証でも使用できる。テナントレベルの操作で使用する。

    Args:
        request: FastAPI の Request オブジェクト（ミドルウェアで tenant がセット済み）。

    Returns:
        int: テナント ID。

    Raises:
        HTTPException: 未認証の場合に 401。
    """
    tenant = getattr(request.state, "tenant", None)
    if not tenant:
        raise HTTPException(status_code=401, detail="認証が必要です")
    return tenant.tenant_id


def _require_owner(request: Request) -> None:
    """
    現在のリクエストがオーナーロールの JWT 認証であることを確認する。

    課金操作（プラン変更・Checkout・Portal）はオーナーのみが実行できる。
    API キー認証のリクエストはロールが存在しないため、この確認をスキップする
    （API キーで課金操作することは想定していない）。

    Args:
        request: FastAPI の Request オブジェクト。

    Raises:
        HTTPException: JWT 認証でロールが "owner" でない場合に 403。
    """
    tenant = getattr(request.state, "tenant", None)
    # API キー認証（auth_via="api_key"）はロールチェック対象外
    if tenant and tenant.role != "owner" and tenant.auth_via == "jwt":
        raise HTTPException(status_code=403, detail="オーナーのみ操作できます")


@router.post("/api/auth/register")
def auth_register(body: RegisterBody, db: Session = Depends(get_db)):
    """
    新規テナント（組織）とオーナーユーザーを登録するエンドポイント。

    登録が成功すると JWT アクセストークンを発行し、すぐにログイン状態になる。
    SaaS モードが無効の場合はこのエンドポイント自体を無効化する。

    Args:
        body: メールアドレス・パスワード・組織名を含むリクエストボディ。
        db: SQLAlchemy データベースセッション（DI）。

    Returns:
        dict: access_token, token_type, user, tenant を含む辞書。

    Raises:
        HTTPException 503: SaaS モードが無効の場合。
        HTTPException 400: メールアドレスが既に登録済みの場合。
        HTTPException 500: DB エラー等、予期しない登録失敗の場合。
    """
    if not settings.saas_enabled:
        raise HTTPException(status_code=503, detail="SaaS モードが無効です")
    try:
        return register_tenant(db, body.email, body.password, body.org_name)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.exception("Registration failed: %s", e)
        db.rollback()
        # エラー内容からユーザーに分かりやすいメッセージを選択する
        detail = "登録に失敗しました。データベースの初期化を確認してください。"
        err = str(e).lower()
        if "does not exist" in err or "undefinedtable" in err or "relation" in err:
            # テーブルが存在しないエラー（初回起動・マイグレーション未実行）
            detail = "認証テーブルが未作成です。アプリを再起動してから再試行してください。"
        elif "no module named" in err:
            # Python モジュールが見つからないエラー（デプロイ失敗）
            detail = "サーバー依存関係が不足しています。再デプロイが必要です。"
        raise HTTPException(status_code=500, detail=detail)


@router.post("/api/auth/login")
def auth_login(body: LoginBody, db: Session = Depends(get_db)):
    """
    メールアドレスとパスワードで認証し、JWT アクセストークンを返すエンドポイント。

    bcrypt でパスワードを検証し、一致した場合のみトークンを発行する。
    メールアドレス不存在とパスワード不一致を区別しない（タイミング攻撃・
    ユーザー列挙攻撃を防ぐためのセキュリティ設計）。

    Args:
        body: メールアドレスとパスワードを含むリクエストボディ。
        db: SQLAlchemy データベースセッション（DI）。

    Returns:
        dict: access_token, token_type, user, tenant を含む辞書。

    Raises:
        HTTPException 503: SaaS モードが無効の場合。
        HTTPException 401: 認証失敗（メールまたはパスワードが不正）の場合。
        HTTPException 500: 予期しない DB エラー等の場合。
    """
    if not settings.saas_enabled:
        raise HTTPException(status_code=503, detail="SaaS モードが無効です")
    try:
        return login_user(db, body.email, body.password)
    except ValueError as e:
        raise HTTPException(status_code=401, detail=str(e))
    except Exception as e:
        logger.exception("Login failed: %s", e)
        db.rollback()
        raise HTTPException(status_code=500, detail="ログイン処理に失敗しました")


@router.get("/api/auth/me")
def auth_me(request: Request, db: Session = Depends(get_db)):
    """
    現在ログイン中のユーザー情報・プラン・利用状況を返すエンドポイント。

    フロントエンドのダッシュボードでユーザー情報・利用状況を表示するために使用する。
    JWT 認証が必要（API キーのみでは user_id が特定できないため）。

    Args:
        request: FastAPI の Request オブジェクト（テナントコンテキスト含む）。
        db: SQLAlchemy データベースセッション（DI）。

    Returns:
        dict: user, tenant, usage, features, billing を含む辞書。

    Raises:
        HTTPException 401: JWT 認証なしまたは無効なトークンの場合。
        HTTPException 404: ユーザーが見つからない場合。
    """
    user_id = _current_user_id(request)
    try:
        return get_me(db, user_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/api/auth/api-keys")
def auth_list_keys(request: Request, db: Session = Depends(get_db)):
    """
    現在のテナントが保有する API キーの一覧を返すエンドポイント。

    セキュリティのため、生の API キー値は返さず、プレフィックスと最終使用日時のみ返す。
    キーの作成は POST /api/auth/api-keys で行う。

    Args:
        request: FastAPI の Request オブジェクト。
        db: SQLAlchemy データベースセッション（DI）。

    Returns:
        dict: "keys" キーに API キー情報リストを含む辞書。
    """
    tenant_id = _current_tenant_id(request)
    return {"keys": list_api_keys(db, tenant_id)}


@router.post("/api/auth/api-keys")
def auth_create_key(body: ApiKeyBody, request: Request, db: Session = Depends(get_db)):
    """
    新しい API キーを作成するエンドポイント。

    生の API キー（fx_xxxxx 形式）はレスポンスに 1 度だけ含まれる。
    再表示はできないため、フロントエンドはユーザーに安全な場所への保存を促すこと。
    プランごとの最大発行数を超えた場合は 400 エラーを返す。

    Args:
        body: キー名を含むリクエストボディ。
        request: FastAPI の Request オブジェクト。
        db: SQLAlchemy データベースセッション（DI）。

    Returns:
        dict: id, name, key_prefix, api_key（生の値・1回のみ）, created_at を含む辞書。

    Raises:
        HTTPException 400: API キーの発行上限に達した場合。
    """
    tenant_id = _current_tenant_id(request)
    try:
        return create_api_key(db, tenant_id, body.name)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/api/billing/plans")
def billing_plans():
    """
    利用可能なサブスクリプションプランの一覧を返すエンドポイント。

    認証不要の公開エンドポイント（/api/billing/plans は PUBLIC_API_PATHS に含まれる）。
    フロントエンドのプラン選択ページで使用する。

    Returns:
        dict: plans（プラン一覧）・saas_enabled・stripe_enabled を含む辞書。
    """
    return {
        "plans": list_plans_public(),
        "saas_enabled": settings.saas_enabled,      # SaaS モードの有効/無効
        "stripe_enabled": stripe_configured(),        # Stripe の設定状態
    }


@router.get("/api/billing/status")
def billing_status_route(request: Request, db: Session = Depends(get_db)):
    """
    現在のテナントの請求・利用状況を返すエンドポイント。

    プラン情報・Stripe サブスクリプション状態・当日の API 利用状況（残回数・使用率）を
    一括して返す。フロントエンドのダッシュボードの請求セクションで使用する。

    Args:
        request: FastAPI の Request オブジェクト。
        db: SQLAlchemy データベースセッション（DI）。

    Returns:
        dict: Stripe ステータス情報に usage（利用状況）を追加した辞書。
              usage には daily_calls, daily_limit, remaining, usage_percent が含まれる。

    Raises:
        HTTPException 401: 未認証の場合。
        HTTPException 404: テナントが見つからない場合。
    """
    tenant_id = _current_tenant_id(request)
    tenant = db.get(Tenant, tenant_id)
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")
    from src.auth.models import count_daily_usage
    from src.auth.plans import daily_limit

    # 当日の利用回数と上限を取得
    usage = count_daily_usage(tenant_id)
    limit = daily_limit(tenant.plan)
    status = billing_status(tenant)
    # Stripe ステータス情報に API 利用状況を追加
    status["usage"] = {
        "daily_calls": usage,
        "daily_limit": limit,
        "remaining": max(0, limit - usage),          # 残回数（マイナスにはしない）
        # 利用率（%）。上限が 0 の場合は 0% とする（ZeroDivisionError 回避）
        "usage_percent": round((usage / limit) * 100, 1) if limit else 0,
    }
    return status


@router.post("/api/billing/portal")
def billing_portal(body: PortalBody, request: Request, db: Session = Depends(get_db)):
    """
    Stripe カスタマーポータルのセッション URL を発行するエンドポイント。

    顧客はポータルで請求書の確認・支払い方法の変更・サブスクリプションのキャンセルができる。
    オーナーロールの JWT 認証が必要（他のメンバーが課金情報を変更できないように）。

    Args:
        body: ポータルからの戻り先 URL を含むリクエストボディ。
        request: FastAPI の Request オブジェクト。
        db: SQLAlchemy データベースセッション（DI）。

    Returns:
        dict: "portal_url" キーに Stripe ポータル URL を含む辞書。

    Raises:
        HTTPException 401: 未認証の場合。
        HTTPException 403: オーナー以外のユーザーの場合。
        HTTPException 400: Stripe が未設定または顧客が存在しない場合。
    """
    # オーナー権限チェック（課金操作はオーナーのみ）
    _require_owner(request)
    tenant_id = _current_tenant_id(request)
    tenant = db.get(Tenant, tenant_id)
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")
    # デフォルトの戻り先は /settings ページ
    base = settings.app_public_url.rstrip("/")
    return_url = body.return_url or f"{base}/settings"
    try:
        url = create_portal_session(tenant, return_url)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"portal_url": url}


@router.post("/api/billing/checkout")
def billing_checkout(body: CheckoutBody, request: Request, db: Session = Depends(get_db)):
    """
    Stripe Checkout セッションを作成し、決済ページの URL を返すエンドポイント。

    フロントエンドはこの URL にリダイレクトして Stripe のホスト型決済ページを表示する。
    決済完了後は Stripe Webhook（/api/billing/webhook）でプランが更新される。

    Args:
        body: プラン・成功/キャンセル後のリダイレクト URL を含むリクエストボディ。
        request: FastAPI の Request オブジェクト。
        db: SQLAlchemy データベースセッション（DI）。

    Returns:
        dict: "checkout_url" キーに Stripe Checkout URL を含む辞書。

    Raises:
        HTTPException 401: 未認証の場合。
        HTTPException 403: オーナー以外のユーザーの場合。
        HTTPException 400: Stripe が未設定または無効なプランの場合。
    """
    # オーナー権限チェック（課金操作はオーナーのみ）
    _require_owner(request)
    tenant_id = _current_tenant_id(request)
    tenant = db.get(Tenant, tenant_id)
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")

    # デフォルトのリダイレクト先を設定（クエリパラメータで決済結果を通知）
    base = settings.app_public_url.rstrip("/")
    success = body.success_url or f"{base}/settings?checkout=success"
    cancel = body.cancel_url or f"{base}/settings?checkout=cancel"
    # Stripe Checkout のプリフィル用にメールアドレスを渡す（入力省略のため）
    tenant_ctx = getattr(request.state, "tenant", None)
    email = tenant_ctx.email if tenant_ctx else None

    try:
        url = create_checkout_session(db, tenant, body.plan, success, cancel, email)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"checkout_url": url}


@router.post("/api/billing/upgrade")
def billing_upgrade(body: PlanUpgradeBody, request: Request, db: Session = Depends(get_db)):
    """Stripe 未設定時のデモ用プラン変更（free へのダウングレードは常に可）

    Stripe が設定されている環境では、有料プラン（pro/enterprise）への変更は
    Stripe Checkout を通じて行う必要があり、このエンドポイントでは拒否する。
    Stripe 未設定の開発・デモ環境でのみ有料プランへの直接変更が可能。
    free へのダウングレードは常に許可する（Stripe 解約後の処理等）。

    Args:
        body: 変更先プラン名を含むリクエストボディ。
        request: FastAPI の Request オブジェクト。
        db: SQLAlchemy データベースセッション（DI）。

    Returns:
        dict: "tenant"（更新後テナント情報）と "message" を含む辞書。

    Raises:
        HTTPException 400: Stripe が設定済みで有料プランへ変更しようとした場合、
                           または無効なプラン名の場合。
    """
    # オーナー権限チェック
    _require_owner(request)
    # Stripe が設定済みの場合、有料プランは Checkout を経由しなければならない
    if stripe_configured() and body.plan in ("pro", "enterprise"):
        raise HTTPException(
            status_code=400,
            detail="有料プランは Stripe Checkout を使用してください",
        )
    tenant_id = _current_tenant_id(request)
    try:
        updated = upgrade_plan(db, tenant_id, body.plan)
        return {"tenant": updated, "message": "プランを更新しました"}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/api/billing/webhook")
async def billing_stripe_webhook(request: Request, db: Session = Depends(get_db)):
    """
    Stripe からの Webhook イベントを受信・処理するエンドポイント。

    Stripe は決済完了・サブスクリプション更新・キャンセル等のイベントを
    このエンドポイントに POST で送信する。署名検証により Stripe からの
    正規のリクエストであることを確認してから処理する。

    公開エンドポイント（PUBLIC_API_PATHS に含まれる）のため認証不要。
    ただし Stripe 署名（Stripe-Signature ヘッダー）で正当性を検証する。

    Args:
        request: FastAPI の Request オブジェクト（生のバイト列ボディを取得）。
        db: SQLAlchemy データベースセッション（DI）。

    Returns:
        dict: "received": True と処理結果を含む辞書。

    Raises:
        HTTPException 400: Stripe 署名検証失敗または Webhook 処理エラーの場合。
    """
    # Stripe は署名計算のために生のバイト列ボディを必要とする
    # （JSON パース後の再シリアライズでは署名が合わなくなる）
    payload = await request.body()
    # Stripe-Signature ヘッダー（"t=タイムスタンプ,v1=ハッシュ" 形式）
    sig = request.headers.get("Stripe-Signature")
    # Webhook シークレットが未設定の場合はノーオペで返す（開発環境向け）
    if not settings.stripe_webhook_secret:
        return {"received": True, "note": "STRIPE_WEBHOOK_SECRET 未設定 — ノーオペ"}
    try:
        # 署名検証 + イベント処理（サブスクリプション更新・キャンセル等）
        result = handle_stripe_webhook(payload, sig, db)
        return {"received": True, **result}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.exception("Stripe webhook error: %s", e)
        raise HTTPException(status_code=400, detail="Webhook processing failed")
