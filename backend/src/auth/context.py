"""
リクエストスコープのテナントコンテキスト管理モジュール。

Python の contextvars.ContextVar を利用して、各 HTTP リクエスト（非同期タスク）ごとに
独立したテナント情報を保持する。FastAPI / Starlette の非同期処理では asyncio タスクが
並行して走るため、グローバル変数ではテナント情報が混在してしまう。ContextVar を使うことで
タスクごとに分離されたスコープが保証される（マルチテナント SaaS の基本設計）。
"""

from contextvars import ContextVar

from src.auth.service import TenantContext

# リクエストスコープのテナントコンテキストを保持する ContextVar。
# default=None は未認証状態（ミドルウェアで認証前）を表す。
# contextvars は asyncio タスクをまたいで安全にコピーされるため、
# 各リクエストが独立した値を持つことが保証される。
_tenant_ctx: ContextVar[TenantContext | None] = ContextVar("tenant_ctx", default=None)


def set_tenant_context(ctx: TenantContext | None) -> None:
    """
    現在のリクエストスコープにテナントコンテキストをセットする。

    SaaSAuthMiddleware が認証完了後に呼び出す。
    None を渡すことで明示的にコンテキストをクリアすることも可能。

    Args:
        ctx: セットするテナントコンテキスト。認証失敗時は None。
    """
    _tenant_ctx.set(ctx)


def get_tenant_context() -> TenantContext | None:
    """
    現在のリクエストスコープのテナントコンテキストを取得する。

    認証ミドルウェアを通過していないリクエスト（公開エンドポイント等）では
    None が返る。呼び出し元は None チェックを行うこと。

    Returns:
        TenantContext: 認証済みテナントの情報。未認証の場合は None。
    """
    return _tenant_ctx.get()


def get_tenant_id() -> int | None:
    """
    現在のリクエストスコープのテナント ID を取得する。

    テナント ID だけが必要な場合のショートカット関数。
    コンテキストが存在しない（未認証）場合は None を返す。

    Returns:
        int: テナント ID。未認証またはコンテキスト未設定の場合は None。
    """
    ctx = _tenant_ctx.get()
    # コンテキストが存在する場合のみ tenant_id を返す（未認証時は None）
    return ctx.tenant_id if ctx else None
