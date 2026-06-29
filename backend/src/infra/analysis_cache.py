"""分析結果の TTL キャッシュ（DynamoDB またはプロセス内）"""

from __future__ import annotations

from typing import Callable, TypeVar

from src.config import settings
from src.db.database import dynamodb_client

T = TypeVar("T")


def cache_key(prefix: str, symbol: str, **parts: int | str) -> str:
    sym = symbol.upper()
    if not parts:
        return f"{prefix}:{sym}"
    suffix = ":".join(f"{k}={v}" for k, v in sorted(parts.items()))
    return f"{prefix}:{sym}:{suffix}"


def cache_get(key: str) -> dict | None:
    return dynamodb_client.get(key)


def cache_put(key: str, data: dict, ttl_seconds: int | None = None) -> None:
    ttl = ttl_seconds if ttl_seconds is not None else settings.analysis_cache_ttl_seconds
    dynamodb_client.put(key, data, ttl_seconds=ttl)


def get_or_compute(key: str, compute: Callable[[], T], ttl_seconds: int | None = None) -> T:
    """キャッシュヒット時は compute を呼ばない。"""
    cached = cache_get(key)
    if cached is not None:
        return cached  # type: ignore[return-value]
    result = compute()
    if isinstance(result, dict):
        cache_put(key, result, ttl_seconds=ttl_seconds)
    return result
