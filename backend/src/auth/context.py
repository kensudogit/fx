"""リクエストスコープのテナントコンテキスト"""

from contextvars import ContextVar

from src.auth.service import TenantContext

_tenant_ctx: ContextVar[TenantContext | None] = ContextVar("tenant_ctx", default=None)


def set_tenant_context(ctx: TenantContext | None) -> None:
    _tenant_ctx.set(ctx)


def get_tenant_context() -> TenantContext | None:
    return _tenant_ctx.get()


def get_tenant_id() -> int | None:
    ctx = _tenant_ctx.get()
    return ctx.tenant_id if ctx else None
