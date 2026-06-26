"""Redis 分散ロック（未設定時はプロセス内フォールバック）"""

from __future__ import annotations

import logging
from uuid import uuid4

logger = logging.getLogger(__name__)

_redis_client = None
_local_locks: set[str] = set()

_RELEASE_SCRIPT = """
if redis.call('get', KEYS[1]) == ARGV[1] then
    return redis.call('del', KEYS[1])
else
    return 0
end
"""


def _get_redis():
    global _redis_client
    from src.config import settings

    if not settings.redis_url:
        return None
    if _redis_client is None:
        try:
            import redis

            _redis_client = redis.from_url(settings.redis_url, decode_responses=True)
            _redis_client.ping()
            logger.info("Redis distributed lock enabled")
        except Exception as e:
            logger.warning("Redis unavailable, using in-process locks: %s", e)
            _redis_client = False
    return _redis_client if _redis_client is not False else None


def try_acquire_lock(name: str, ttl_seconds: int = 180) -> str | None:
    """ロック取得。成功時は release 用トークンを返す。"""
    token = str(uuid4())
    key = f"lock:{name}"
    client = _get_redis()
    if client:
        try:
            if client.set(key, token, nx=True, ex=ttl_seconds):
                return token
            return None
        except Exception as e:
            logger.warning("Redis lock acquire failed: %s", e)

    if key in _local_locks:
        return None
    _local_locks.add(key)
    return token


def release_lock(name: str, token: str) -> None:
    key = f"lock:{name}"
    client = _get_redis()
    if client:
        try:
            client.eval(_RELEASE_SCRIPT, 1, key, token)
        except Exception as e:
            logger.warning("Redis lock release failed: %s", e)
        return
    _local_locks.discard(key)


def lock_status() -> dict:
    from src.config import settings

    client = _get_redis()
    return {
        "backend": "redis" if client else "in_process",
        "redis_url_configured": bool(settings.redis_url),
    }
