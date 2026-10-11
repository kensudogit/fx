"""テナントコンテキスト — src.auth.context のテスト

ContextVar を使ったリクエストスコープ分離が正しく機能することを検証する。
"""

import asyncio
import threading

import pytest

from src.auth.context import get_tenant_context, get_tenant_id, set_tenant_context
from src.auth.service import TenantContext


def make_ctx(tenant_id: int = 1, **kwargs) -> TenantContext:
    """テスト用のテナントコンテキストを組み立てる。"""
    defaults = dict(tenant_id=tenant_id, tenant_slug=f"tenant-{tenant_id}", plan="free")
    defaults.update(kwargs)
    return TenantContext(**defaults)


@pytest.fixture(autouse=True)
def clear_context():
    """各テストの前後でコンテキストを空に戻す（テスト間の漏れを防ぐ）。"""
    set_tenant_context(None)
    yield
    set_tenant_context(None)


class TestSetAndGet:
    """set_tenant_context() / get_tenant_context() の基本動作"""

    def test_defaults_to_none(self):
        """未設定（未認証）では None を返すこと"""
        assert get_tenant_context() is None

    def test_roundtrip(self):
        """設定した値をそのまま取得できること"""
        ctx = make_ctx(42)
        set_tenant_context(ctx)
        assert get_tenant_context() is ctx

    def test_can_be_cleared(self):
        """None を渡すと明示的にクリアできること"""
        set_tenant_context(make_ctx())
        set_tenant_context(None)
        assert get_tenant_context() is None

    def test_overwrites_previous_value(self):
        """後から設定した値で上書きされること"""
        set_tenant_context(make_ctx(1))
        set_tenant_context(make_ctx(2))
        assert get_tenant_context().tenant_id == 2


class TestGetTenantId:
    """get_tenant_id() のショートカット動作"""

    def test_returns_none_when_unauthenticated(self):
        """未認証では None を返すこと（呼び出し側の None チェックを促す）"""
        assert get_tenant_id() is None

    def test_returns_tenant_id(self):
        """コンテキストの tenant_id を返すこと"""
        set_tenant_context(make_ctx(7))
        assert get_tenant_id() == 7

    def test_works_for_api_key_context(self):
        """API キー認証（user_id が None）でもテナント ID を取得できること"""
        set_tenant_context(make_ctx(9, user_id=None, email=None, role=None, auth_via="api_key"))
        assert get_tenant_id() == 9


class TestIsolation:
    """リクエストスコープ分離のテスト（マルチテナントの安全性の要）"""

    def test_threads_do_not_share_context(self):
        """スレッド間でコンテキストが混ざらないこと"""
        set_tenant_context(make_ctx(1))
        seen = {}

        def worker():
            # 別スレッドは親の値を引き継がず、独自に設定できる
            seen["before"] = get_tenant_id()
            set_tenant_context(make_ctx(2))
            seen["after"] = get_tenant_id()

        t = threading.Thread(target=worker)
        t.start()
        t.join()

        assert seen["before"] is None
        assert seen["after"] == 2
        # 呼び出し元のコンテキストは書き換えられていない
        assert get_tenant_id() == 1

    def test_concurrent_async_tasks_keep_own_context(self):
        """並行する asyncio タスク同士でテナントが混ざらないこと"""

        async def handler(tenant_id: int) -> int:
            set_tenant_context(make_ctx(tenant_id))
            # 他タスクへ処理を明け渡した後も自分のテナントを保持していること
            await asyncio.sleep(0)
            return get_tenant_id()

        async def main():
            return await asyncio.gather(*(handler(i) for i in range(1, 6)))

        assert asyncio.run(main()) == [1, 2, 3, 4, 5]

    def test_child_task_inherits_snapshot_without_leaking_back(self):
        """子タスクは親の値を引き継ぐが、子の変更は親へ漏れないこと"""

        async def child() -> int:
            inherited = get_tenant_id()
            set_tenant_context(make_ctx(99))
            return inherited

        async def main():
            set_tenant_context(make_ctx(5))
            inherited = await asyncio.create_task(child())
            return inherited, get_tenant_id()

        inherited, after = asyncio.run(main())
        assert inherited == 5
        assert after == 5
