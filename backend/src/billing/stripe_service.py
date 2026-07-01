"""
Stripe 課金サービスモジュール — Checkout セッション / Webhook 処理

Stripe API を使ってサブスクリプション課金を管理するモジュール。
マルチテナント構成での有料プランへのアップグレード・ダウングレードを処理する。

主な機能:
    - Checkout セッションの作成（有料プランへの申し込みフロー）
    - Stripe Webhook の検証と処理（決済完了・サブスクリプション更新・解約）
    - Billing ポータルセッションの作成（支払い方法変更・領収書確認）
    - 課金状態の取得（現在プラン・制限・サブスクリプション ID）

Webhook イベント処理対象:
    - checkout.session.completed: 初回決済完了時のプラン有効化
    - customer.subscription.updated: サブスクリプション変更・更新
    - customer.subscription.created: 新規サブスクリプション作成
    - customer.subscription.deleted: サブスクリプション解約（free へダウングレード）

セキュリティ:
    - Webhook は Stripe の署名ヘッダー（Stripe-Signature）を検証してから処理
    - API キーは環境変数から取得（コードに埋め込まない）
"""

from __future__ import annotations

import logging

import stripe
from sqlalchemy.orm import Session

from src.auth.models import Tenant
from src.config import settings

logger = logging.getLogger(__name__)

# プラン ID → 環境変数名のマッピング
# Stripe の Price ID は環境変数経由で設定する
PLAN_PRICE_ENV = {
    "pro": "stripe_price_pro",
    "enterprise": "stripe_price_enterprise",
}


def stripe_configured() -> bool:
    """Stripe API キーが設定されているか確認する。

    Returns:
        STRIPE_SECRET_KEY が設定されている場合は True
    """
    return bool(settings.stripe_secret_key)


def _price_id_for_plan(plan: str) -> str | None:
    """プラン名に対応する Stripe Price ID を環境変数から取得する。

    Args:
        plan: プラン名（"pro" または "enterprise"）

    Returns:
        Stripe Price ID の文字列。未設定の場合は None。
    """
    attr = PLAN_PRICE_ENV.get(plan)
    if not attr:
        return None
    return getattr(settings, attr, "") or None


def create_checkout_session(
    db: Session,
    tenant: Tenant,
    plan: str,
    success_url: str,
    cancel_url: str,
    customer_email: str | None = None,
) -> str:
    """Stripe Checkout セッションを作成して決済 URL を返す。

    ユーザーをこの URL にリダイレクトすることで Stripe の決済フォームに誘導する。
    既存の Stripe 顧客 ID がある場合はそれを使用し、ない場合はメールアドレスで
    新規顧客を作成する。

    サブスクリプションのメタデータには tenant_id と plan を含め、
    Webhook 処理時にテナントを特定できるようにする。

    Args:
        db: SQLAlchemy セッション
        tenant: 対象テナントの ORM オブジェクト
        plan: 申し込むプラン（"pro" または "enterprise"）
        success_url: 決済成功後のリダイレクト URL
        cancel_url: キャンセル時のリダイレクト URL
        customer_email: Stripe 顧客のメールアドレス（新規顧客の場合）

    Returns:
        Stripe Checkout セッションの URL

    Raises:
        ValueError: pro/enterprise 以外のプランが指定された場合
        ValueError: STRIPE_SECRET_KEY または Price ID が未設定の場合
        ValueError: Checkout URL の生成に失敗した場合
    """
    if plan not in ("pro", "enterprise"):
        raise ValueError("Checkout は pro / enterprise プランのみ対応")
    if not stripe_configured():
        raise ValueError("STRIPE_SECRET_KEY が未設定です")

    # 対象プランの Stripe Price ID を環境変数から取得
    price_id = _price_id_for_plan(plan)
    if not price_id:
        raise ValueError(f"Stripe Price ID が未設定です（STRIPE_PRICE_{plan.upper()}）")

    stripe.api_key = settings.stripe_secret_key
    params: dict = {
        "mode": "subscription",  # 月次/年次サブスクリプション課金モード
        "line_items": [{"price": price_id, "quantity": 1}],
        "success_url": success_url,
        "cancel_url": cancel_url,
        # Webhook 処理時にテナントを特定するためのメタデータ
        "metadata": {"tenant_id": str(tenant.id), "plan": plan},
        "subscription_data": {"metadata": {"tenant_id": str(tenant.id), "plan": plan}},
    }

    # 既存の Stripe 顧客 ID がある場合はそれを使用（二重顧客登録を防ぐ）
    if tenant.stripe_customer_id:
        params["customer"] = tenant.stripe_customer_id
    elif customer_email:
        # 顧客 ID がない場合はメールアドレスで新規顧客として作成
        params["customer_email"] = customer_email

    session = stripe.checkout.Session.create(**params)
    if not session.url:
        raise ValueError("Checkout URL の生成に失敗しました")
    return session.url


def handle_stripe_webhook(payload: bytes, sig_header: str | None, db: Session) -> dict:
    """Stripe Webhook のリクエストを検証して処理する。

    Stripe はイベント発生時にこのエンドポイントに POST リクエストを送る。
    署名ヘッダー（Stripe-Signature）を検証して改ざんされていないことを確認してから
    イベントタイプに応じた処理を行う。

    処理するイベントタイプ:
        - checkout.session.completed: 初回決済完了
        - customer.subscription.updated: サブスクリプション更新
        - customer.subscription.created: 新規サブスクリプション
        - customer.subscription.deleted: サブスクリプション解約

    Args:
        payload: リクエストボディのバイト列（署名検証に使用）
        sig_header: Stripe-Signature ヘッダーの値
        db: SQLAlchemy セッション

    Returns:
        処理結果の辞書（handled: bool, type: str, 等）

    Raises:
        ValueError: Webhook シークレットまたは API キーが未設定の場合
        stripe.error.SignatureVerificationError: 署名検証に失敗した場合
    """
    if not settings.stripe_webhook_secret:
        raise ValueError("STRIPE_WEBHOOK_SECRET が未設定です")
    if not settings.stripe_secret_key:
        raise ValueError("STRIPE_SECRET_KEY が未設定です")

    stripe.api_key = settings.stripe_secret_key
    # Stripe の署名を検証してイベントオブジェクトを構築
    # 署名が無効な場合は stripe.error.SignatureVerificationError が発生
    event = stripe.Webhook.construct_event(payload, sig_header or "", settings.stripe_webhook_secret)

    event_type = event["type"]
    data = event["data"]["object"]

    # イベントタイプに応じたハンドラーに処理を委譲
    if event_type == "checkout.session.completed":
        return _on_checkout_completed(db, data)
    if event_type in ("customer.subscription.updated", "customer.subscription.created"):
        return _on_subscription_updated(db, data)
    if event_type == "customer.subscription.deleted":
        return _on_subscription_deleted(db, data)

    # 対象外のイベントは handled=False で返す（Stripe は 200 レスポンスを期待）
    return {"handled": False, "type": event_type}


def _on_checkout_completed(db: Session, session: dict) -> dict:
    """Checkout セッション完了イベントを処理する（初回決済完了）。

    メタデータから tenant_id と plan を取得し、テナントのプランを更新する。
    また Stripe の顧客 ID とサブスクリプション ID を DB に保存する。

    Args:
        db: SQLAlchemy セッション
        session: Stripe の checkout.session オブジェクト

    Returns:
        処理結果辞書（handled, tenant_id, plan）
    """
    tenant_id = int(session.get("metadata", {}).get("tenant_id", 0))
    plan = session.get("metadata", {}).get("plan", "pro")
    tenant = db.get(Tenant, tenant_id)
    if not tenant:
        logger.warning("checkout completed for unknown tenant %s", tenant_id)
        return {"handled": False, "reason": "tenant_not_found"}

    # テナントのプランを有料プランに更新
    tenant.plan = plan
    # Stripe 顧客 ID を保存（以降の課金操作で使用）
    if session.get("customer"):
        tenant.stripe_customer_id = session["customer"]
    # サブスクリプション ID を保存（解約・更新の追跡に使用）
    sub_id = session.get("subscription")
    if sub_id:
        tenant.stripe_subscription_id = sub_id
    db.commit()
    logger.info("Stripe checkout completed tenant=%s plan=%s", tenant_id, plan)
    return {"handled": True, "tenant_id": tenant_id, "plan": plan}


def _on_subscription_updated(db: Session, sub: dict) -> dict:
    """サブスクリプション更新・作成イベントを処理する。

    サブスクリプションのステータスに応じてテナントのプランを更新する。
    - active/trialing: プラン有効（有料プランに設定）
    - canceled/unpaid/past_due: プラン無効（free にダウングレード）

    Args:
        db: SQLAlchemy セッション
        sub: Stripe の subscription オブジェクト

    Returns:
        処理結果辞書
    """
    tenant_id = int(sub.get("metadata", {}).get("tenant_id", 0))
    plan = sub.get("metadata", {}).get("plan")
    tenant = db.get(Tenant, tenant_id)
    if not tenant:
        return {"handled": False, "reason": "tenant_not_found"}

    status = sub.get("status", "")
    if status in ("active", "trialing") and plan:
        # サブスクリプションが有効な場合、プランを更新
        tenant.plan = plan
        tenant.stripe_subscription_id = sub.get("id")
        if sub.get("customer"):
            tenant.stripe_customer_id = sub["customer"]
        db.commit()
        return {"handled": True, "tenant_id": tenant_id, "plan": plan}

    if status in ("canceled", "unpaid", "past_due"):
        # 支払い失敗・解約の場合は free プランにダウングレード
        tenant.plan = "free"
        db.commit()
        return {"handled": True, "tenant_id": tenant_id, "plan": "free"}

    return {"handled": False, "status": status}


def _on_subscription_deleted(db: Session, sub: dict) -> dict:
    """サブスクリプション削除（解約）イベントを処理する。

    サブスクリプションが完全に削除された場合、
    テナントを free プランにダウングレードする。

    Args:
        db: SQLAlchemy セッション
        sub: Stripe の subscription オブジェクト

    Returns:
        処理結果辞書
    """
    tenant_id = int(sub.get("metadata", {}).get("tenant_id", 0))
    tenant = db.get(Tenant, tenant_id)
    if not tenant:
        return {"handled": False, "reason": "tenant_not_found"}

    # サブスクリプションが削除されたため free プランに戻す
    tenant.plan = "free"
    tenant.stripe_subscription_id = None
    db.commit()
    logger.info("Stripe subscription deleted tenant=%s -> free", tenant_id)
    return {"handled": True, "tenant_id": tenant_id, "plan": "free"}


def create_portal_session(tenant: Tenant, return_url: str) -> str:
    """Stripe Billing Portal セッションを作成する。

    Billing Portal では以下の操作が可能:
        - 支払い方法の変更
        - サブスクリプションのキャンセル
        - 請求書・領収書の確認
        - プラン変更

    Args:
        tenant: 対象テナントの ORM オブジェクト
        return_url: Portal から戻ったときのリダイレクト URL

    Returns:
        Stripe Billing Portal の URL

    Raises:
        ValueError: STRIPE_SECRET_KEY が未設定の場合
        ValueError: テナントに Stripe 顧客 ID がない場合
        ValueError: Portal URL の生成に失敗した場合
    """
    if not stripe_configured():
        raise ValueError("STRIPE_SECRET_KEY が未設定です")
    if not tenant.stripe_customer_id:
        raise ValueError("Stripe 顧客 ID がありません。先に有料プランを申し込んでください")

    stripe.api_key = settings.stripe_secret_key
    session = stripe.billing_portal.Session.create(
        customer=tenant.stripe_customer_id,
        return_url=return_url,
    )
    if not session.url:
        raise ValueError("ポータル URL の生成に失敗しました")
    return session.url


def billing_status(tenant: Tenant) -> dict:
    """テナントの現在の課金状態を返す。

    プラン情報・API 制限・Stripe 連携状態をまとめて返す。
    ダッシュボードの課金ステータス表示に使用する。

    Args:
        tenant: 対象テナントの ORM オブジェクト

    Returns:
        課金状態の辞書:
            - plan: 現在のプラン ID
            - plan_name: プランの表示名
            - price_monthly_usd: 月額料金（USD）
            - daily_api_limit: 1日あたりの API 呼び出し制限数
            - stripe_customer_id: Stripe 顧客 ID（マスクなし）
            - stripe_subscription_id: Stripe サブスクリプション ID
            - has_active_subscription: 有効なサブスクリプションがあるか
            - stripe_enabled: Stripe が設定済みか
    """
    from src.auth.plans import PLANS, daily_limit

    # 不明なプランの場合は free にフォールバック
    plan = tenant.plan if tenant.plan in PLANS else "free"
    info = PLANS[plan]
    return {
        "plan": plan,
        "plan_name": info["name"],
        "price_monthly_usd": info["price_monthly_usd"],
        "daily_api_limit": daily_limit(plan),
        "stripe_customer_id": tenant.stripe_customer_id,
        "stripe_subscription_id": tenant.stripe_subscription_id,
        "has_active_subscription": bool(tenant.stripe_subscription_id),
        "stripe_enabled": stripe_configured(),
    }
