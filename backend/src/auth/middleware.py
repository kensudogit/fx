"""
SaaS 認証・認可ミドルウェアモジュール。

すべての /api/ リクエストをインターセプトし、以下の処理を順番に実行する:
  1. 公開エンドポイントの判定（認証不要なパスをスキップ）
  2. JWT または API キーによるテナント識別
  3. テナントのプラン情報をデータベースから補完
  4. 1日あたりの API 利用上限チェック（レート制限）
  5. プレミアム機能へのアクセス制御（プラン別フィーチャーゲート）
  6. リクエスト成功後の利用実績を記録

マルチテナント SaaS では「誰がリクエストを送っているか（テナント識別）」と
「そのテナントが何を利用できるか（プラン制御）」を一元管理することが重要。
"""

import logging

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from src.auth.models import record_usage
from src.auth.plans import PREMIUM_PATH_EXACT, PREMIUM_PATH_PREFIXES, daily_limit, plan_features
from src.auth.security import decode_access_token
from src.auth.service import TenantContext, resolve_api_key
from src.config import settings
from src.db.database import SessionLocal

logger = logging.getLogger(__name__)

# 認証なしでアクセスできる公開 API パス（完全一致）。
# 登録・ログイン・プラン一覧・Stripe Webhook・AI ステータスは
# 未認証ユーザーや外部サービスからのアクセスが必要なため公開とする。
PUBLIC_API_PATHS = {
    "/api/auth/register",
    "/api/auth/login",
    "/api/billing/plans",
    "/api/billing/webhook",
    "/api/ai/status",
}

# 前方一致で公開とするパスプレフィックス。
# /api/symbols/ 以下は通貨ペア一覧等の参照情報で認証不要。
PUBLIC_API_PREFIXES = (
    "/api/symbols",
)


def _is_public_api(path: str, method: str) -> bool:
    """
    指定パスが認証不要の公開 API かどうかを判定する。

    完全一致・プレフィックス一致・メソッド条件の 3 段階で判定する。
    TradingView Webhook は POST のみ公開（GET は認証必須）。

    Args:
        path: リクエストの URL パス（例: "/api/auth/login"）。
        method: HTTP メソッド（例: "GET", "POST"）。

    Returns:
        bool: 公開 API であれば True、認証が必要であれば False。
    """
    # 完全一致で公開パスを確認
    if path in PUBLIC_API_PATHS:
        return True
    # /api/symbols で始まるパスは公開（通貨ペア情報）
    if path.startswith("/api/symbols"):
        return True
    # TradingView Webhook は POST のみ公開（外部サービスからのコールバック）
    if path == "/api/tradingview/webhook" and method == "POST":
        return True
    return False


def _requires_premium(path: str, method: str) -> bool:
    """
    指定パスがプレミアム（有料）プラン限定かどうかを判定する。

    PREMIUM_PATH_EXACT（メソッド・パスの完全一致）と
    PREMIUM_PATH_PREFIXES（前方一致）の両方を確認する。

    Args:
        path: リクエストの URL パス。
        method: HTTP メソッド（POST / GET 等）。

    Returns:
        bool: プレミアム機能であれば True、無料プランでも利用可能なら False。
    """
    # AI ステータス確認エンドポイントは公開（プレミアム不要）
    if path == "/api/ai/status":
        return False
    # メソッドとパスの完全一致でプレミアム判定（例: POST /api/oanda/orders）
    if (method, path) in PREMIUM_PATH_EXACT:
        return True
    # プレフィックス一致でプレミアム判定（例: /api/ai/, /api/pro/ 等）
    return any(path.startswith(p) for p in PREMIUM_PATH_PREFIXES)


def _resolve_tenant(request: Request) -> TenantContext | None:
    """
    リクエストヘッダーからテナント情報を解決する。

    認証方式は以下の 2 種類をサポートし、JWT を優先する:
      1. JWT Bearer トークン（Authorization: Bearer <token>）
      2. API キー（X-API-Key: fx_xxxxx）

    JWT はステートレスな認証（DB 不要）、API キーはデータベース照合が必要。

    Args:
        request: FastAPI/Starlette の Request オブジェクト。

    Returns:
        TenantContext: 認証済みテナントのコンテキスト。
                       認証失敗または認証情報なしの場合は None。
    """
    # Authorization ヘッダーから Bearer トークンを取得
    auth = request.headers.get("Authorization", "")
    if auth.lower().startswith("bearer "):
        # "Bearer " プレフィックス（7文字）を除去してトークン部分だけ取り出す
        token = auth[7:].strip()
        payload = decode_access_token(token)
        if payload:
            # JWT ペイロードからテナントコンテキストを構築。
            # plan と tenant_slug は JWT に含まれないため、後段のミドルウェアで DB から補完する。
            return TenantContext(
                tenant_id=int(payload["tenant_id"]),
                tenant_slug="",        # DB から補完（後続処理で上書き）
                plan="free",           # DB から補完（後続処理で上書き）
                user_id=int(payload["sub"]),
                email=payload.get("email"),
                role=payload.get("role"),
                auth_via="jwt",        # 認証方式を明示（ロールチェックで使用）
            )

    # JWT がない場合は X-API-Key ヘッダーを確認
    api_key = request.headers.get("X-API-Key", "").strip()
    if api_key:
        db = SessionLocal()
        try:
            # API キーを SHA-256 ハッシュで照合（生のキーはDBに保存しない）
            ctx = resolve_api_key(db, api_key)
            return ctx
        finally:
            db.close()

    # 認証情報が見つからなかった場合
    return None


class SaaSAuthMiddleware(BaseHTTPMiddleware):
    """
    SaaS マルチテナント認証・認可ミドルウェア。

    Starlette の BaseHTTPMiddleware を継承し、FastAPI アプリの全リクエストに
    認証・認可・レート制限・利用記録の処理を適用する。

    処理フロー:
        1. SaaS モード無効時はスルー
        2. /api/ 以外（フロントエンド等）はスルー
        3. WebSocket・ライブ価格等の特例パスをスルー
        4. 公開 API パスをスルー
        5. JWT / API キーでテナントを識別
        6. テナントの実際のプランを DB から取得
        7. 1日の API 利用回数が上限に達していれば 429 を返す
        8. プレミアム機能のアクセス制御
        9. テナントコンテキストをリクエストステートにセット
        10. レスポンス成功時に利用実績を記録
    """

    async def dispatch(self, request: Request, call_next):
        """
        ミドルウェアのメイン処理。全リクエストに対して認証・認可を実行する。

        Args:
            request: 受信した HTTP リクエスト。
            call_next: 次のミドルウェアまたはルートハンドラを呼び出す関数。

        Returns:
            Response: 認証・認可を通過したリクエストのレスポンス、
                      または 401/403/429 エラーレスポンス。
        """
        # SaaS モードが無効（シングルテナント・ローカル開発等）の場合は全スルー
        if not settings.saas_enabled:
            return await call_next(request)

        path = request.url.path
        method = request.method

        # /api/ プレフィックスがないパス（静的ファイル・フロントエンド）はスルー
        if not path.startswith("/api/"):
            return await call_next(request)

        # WebSocket 接続は認証不要（別途 WS ハンドシェイクで認証）
        if path.startswith("/api/ws/"):
            return await call_next(request)
        # ライブ価格ストリーミングは公開（認証コストを避けるため）
        if path == "/api/prices/live" and method == "GET":
            return await call_next(request)

        # 登録・ログイン等の公開 API パスはスルー
        if _is_public_api(path, method):
            return await call_next(request)

        # ─── 認証フェーズ ─────────────────────────────────────────
        # JWT または API キーからテナントコンテキストを解決
        ctx = _resolve_tenant(request)
        if not ctx:
            # 認証情報が存在しない、または無効な場合は 401 を返す
            return JSONResponse(status_code=401, content={"detail": "認証が必要です。ログインまたは API キーを設定してください。"})

        # ─── テナント情報補完フェーズ ────────────────────────────────
        # JWT にはプラン情報が含まれないため、DB からテナントの最新情報を取得する。
        # API キー認証時もここで plan が上書きされ、常に最新のプランが使われる。
        db = SessionLocal()
        try:
            from src.auth.models import Tenant

            tenant = db.get(Tenant, ctx.tenant_id)
            if not tenant:
                return JSONResponse(status_code=401, content={"detail": "テナントが見つかりません"})
            # JWT 認証時に仮設定した "free" を DB の実際のプランで上書き
            ctx.plan = tenant.plan
            ctx.tenant_slug = tenant.slug
        finally:
            db.close()

        # ─── レート制限フェーズ ──────────────────────────────────────
        # 本日（UTC 0:00 以降）の API 呼び出し回数を集計し、上限と比較する
        from src.auth.models import count_daily_usage

        used = count_daily_usage(ctx.tenant_id)
        limit = daily_limit(ctx.plan)          # プランごとの 1日上限（free=100, pro=2000, enterprise=50000）
        if used >= limit:
            # 上限到達時は HTTP 429 Too Many Requests を返す
            return JSONResponse(
                status_code=429,
                content={
                    "detail": (
                        f"1日のAPI利用上限 ({limit}) に達しました。"
                        f"{' Pro プラン（2,000 回/日）へのアップグレードをご検討ください。' if ctx.plan == 'free' else ' 明日以降に再試行するか、プランをアップグレードしてください。'}"
                    ),
                    "usage": used,
                    "limit": limit,
                    "plan": ctx.plan,
                },
            )

        # ─── プレミアム機能アクセス制御フェーズ ────────────────────────
        # 有料プラン限定のエンドポイントにアクセスしようとした場合、
        # テナントのプランが必要な機能を持っているか確認する（フィーチャーゲート）
        if _requires_premium(path, method):
            feats = plan_features(ctx.plan)
            # /api/pro/ は AI Pro 機能（高度なプロンプト・分析）
            if path.startswith("/api/pro/") and not feats.get("ai_pro"):
                return JSONResponse(status_code=403, content={"detail": "AI Pro 機能は Pro プラン以上で利用できます"})
            # /api/ai/ は AI 分析機能全般
            if path.startswith("/api/ai/") and not feats.get("ai"):
                return JSONResponse(status_code=403, content={"detail": "AI分析は Pro プラン以上で利用できます"})
            # /api/analysis/intelligence/ は統合インテリジェンス分析
            if path.startswith("/api/analysis/intelligence/") and not feats.get("analysis_intelligence"):
                return JSONResponse(status_code=403, content={"detail": "統合インテリジェンス分析は Pro プラン以上で利用できます"})
            # OANDA 注文作成（POST のみ制限、照会は無料）
            if path == "/api/oanda/orders" and method == "POST" and not feats.get("oanda_orders"):
                return JSONResponse(status_code=403, content={"detail": "OANDA 注文は Pro プラン以上で利用できます"})
            # /api/autotrade/ は自動取引機能
            if path.startswith("/api/autotrade/") and not feats.get("autotrade"):
                return JSONResponse(status_code=403, content={"detail": "自動取引は Pro プラン以上で利用できます"})
            # /api/broker/ はブローカー（OANDA）設定管理
            if path.startswith("/api/broker/") and not feats.get("oanda_orders"):
                return JSONResponse(status_code=403, content={"detail": "OANDA 設定は Pro プラン以上で利用できます"})

        # ─── コンテキスト伝播フェーズ ────────────────────────────────
        # テナントコンテキストをリクエストステートにセット（ルートハンドラから参照可能）
        request.state.tenant = ctx
        from src.auth.context import set_tenant_context

        # ContextVar にもセット（ルートハンドラ以外のモジュールからも参照可能）
        set_tenant_context(ctx)

        # 後続のハンドラ（ルート関数）を実行してレスポンスを取得
        response = await call_next(request)

        # ─── 利用実績記録フェーズ ─────────────────────────────────
        # 4xx/5xx エラーは記録しない（正常に処理されたリクエストのみカウント）
        if response.status_code < 400:
            record_usage(ctx.tenant_id, path)

        return response
