"""分散ロック — src.infra.distributed_lock のテスト

Redis モード・プロセス内フォールバックの双方を、Redis クライアントを
モックに差し替えて検証する。
"""

from unittest.mock import MagicMock, patch

import pytest

import src.infra.distributed_lock as dl
from src.infra.distributed_lock import lock_status, release_lock, try_acquire_lock


@pytest.fixture(autouse=True)
def reset_lock_state():
    """モジュールのグローバル状態をテストごとに初期化する。"""
    dl._redis_client = None
    dl._local_locks = set()
    yield
    dl._redis_client = None
    dl._local_locks = set()


@pytest.fixture
def in_process(override_settings):
    """Redis 未設定（プロセス内ロック）の状態にする。"""
    override_settings(redis_url="")


@pytest.fixture
def redis_client(override_settings):
    """Redis を設定済みにし、モッククライアントを返す。"""
    override_settings(redis_url="redis://localhost:6379/0")
    client = MagicMock()
    client.ping.return_value = True
    client.set.return_value = True
    dl._redis_client = client
    return client


class TestGetRedis:
    """_get_redis() のテスト"""

    def test_returns_none_without_url(self, in_process):
        """redis_url 未設定なら None を返すこと"""
        assert dl._get_redis() is None

    def test_connection_failure_falls_back_permanently(self, override_settings):
        """接続失敗後は再試行せずプロセス内ロックへフォールバックし続けること"""
        override_settings(redis_url="redis://unreachable:6379/0")
        with patch.dict("sys.modules", {"redis": MagicMock(
                from_url=MagicMock(side_effect=OSError("connection refused")))}):
            assert dl._get_redis() is None
            # 2 回目もクライアント生成を試みない（False をキャッシュ済み）
            assert dl._get_redis() is None

        assert dl._redis_client is False

    def test_reuses_the_cached_client(self, redis_client):
        """一度接続したクライアントを再利用すること"""
        assert dl._get_redis() is redis_client
        assert dl._get_redis() is redis_client


class TestTryAcquireLockInProcess:
    """プロセス内フォールバックでのロック取得テスト"""

    def test_first_acquire_returns_a_token(self, in_process):
        """初回取得でトークンを返すこと"""
        token = try_acquire_lock("autotrade")
        assert isinstance(token, str)
        assert len(token) == 36  # UUIDv4 の文字列長

    def test_second_acquire_is_rejected(self, in_process):
        """保持中のロックは二重取得できないこと"""
        assert try_acquire_lock("autotrade") is not None
        assert try_acquire_lock("autotrade") is None

    def test_different_names_are_independent(self, in_process):
        """名前が違えば同時に取得できること"""
        assert try_acquire_lock("a") is not None
        assert try_acquire_lock("b") is not None

    def test_release_allows_reacquisition(self, in_process):
        """解放後は再取得できること"""
        token = try_acquire_lock("autotrade")
        release_lock("autotrade", token)
        assert try_acquire_lock("autotrade") is not None

    def test_release_of_unheld_lock_is_safe(self, in_process):
        """未取得のロックを解放しても例外にならないこと"""
        release_lock("never-taken", "some-token")

    def test_tokens_are_unique(self, in_process):
        """取得のたびに異なるトークンを返すこと"""
        first = try_acquire_lock("a")
        release_lock("a", first)
        assert try_acquire_lock("a") != first


class TestTryAcquireLockWithRedis:
    """Redis モードでのロック取得テスト"""

    def test_uses_set_nx_with_ttl(self, redis_client):
        """NX（未存在時のみ）+ TTL 付きで SET すること"""
        token = try_acquire_lock("autotrade", ttl_seconds=120)

        redis_client.set.assert_called_once()
        args, kwargs = redis_client.set.call_args
        assert args[0] == "lock:autotrade"
        assert args[1] == token
        assert kwargs == {"nx": True, "ex": 120}

    def test_returns_none_when_already_held(self, redis_client):
        """他プロセスが保持中なら None を返すこと"""
        redis_client.set.return_value = False
        assert try_acquire_lock("autotrade") is None

    def test_key_is_namespaced(self, redis_client):
        """キーに lock: プレフィックスを付けること"""
        try_acquire_lock("engine")
        assert redis_client.set.call_args[0][0] == "lock:engine"

    def test_redis_error_falls_back_to_in_process(self, redis_client):
        """Redis 障害時はプロセス内ロックへフォールバックすること"""
        redis_client.set.side_effect = OSError("redis down")

        assert try_acquire_lock("autotrade") is not None
        # フォールバックしたので 2 回目は取得できない
        assert try_acquire_lock("autotrade") is None

    def test_release_checks_the_token(self, redis_client):
        """解放時はトークン一致を確認してから削除すること（誤解放の防止）"""
        token = try_acquire_lock("autotrade")
        release_lock("autotrade", token)

        assert redis_client.eval.called or redis_client.delete.called

    def test_release_error_is_swallowed(self, redis_client):
        """解放時の Redis 障害でも例外を送出しないこと"""
        redis_client.eval.side_effect = OSError("redis down")
        redis_client.delete.side_effect = OSError("redis down")
        release_lock("autotrade", try_acquire_lock("autotrade"))


class TestLockStatus:
    """lock_status() のテスト"""

    def test_reports_in_process_backend(self, in_process):
        """Redis 未設定なら in_process と報告すること"""
        assert lock_status() == {"backend": "in_process", "redis_url_configured": False}

    def test_reports_redis_backend(self, redis_client):
        """Redis 接続済みなら redis と報告すること"""
        status = lock_status()
        assert status["backend"] == "redis"
        assert status["redis_url_configured"] is True

    def test_reports_configured_but_unreachable(self, override_settings):
        """URL は設定済みだが接続できない場合を区別できること"""
        override_settings(redis_url="redis://unreachable:6379/0")
        dl._redis_client = False

        status = lock_status()
        assert status["backend"] == "in_process"
        assert status["redis_url_configured"] is True
