"""
Redis 分散ロック（未設定時はプロセス内フォールバック）— infra/distributed_lock

複数のワーカーまたはサーバーインスタンスが同一リソース（ML モデル学習・
重複注文防止・キャッシュ更新等）に同時アクセスすることを防ぐための
分散ロック機構を提供するモジュール。

動作モード:
    Redis モード（redis_url 設定済み）:
        Redis の SET NX EX コマンドを使用した分散ロック。
        複数プロセス・複数サーバー間でロックを共有できる。
        Lua スクリプトによる原子的なロック解放でトークンの誤解放を防止。

    インプロセスモード（redis_url 未設定 / Redis 接続失敗）:
        Python の set オブジェクトを使用したプロセス内ロック。
        シングルプロセス環境（開発・テスト）でのフォールバック実装。
        複数プロセス間では共有されないため、本番のマルチワーカー環境では Redis が必要。
"""

from __future__ import annotations

import logging
from uuid import uuid4

logger = logging.getLogger(__name__)

# Redis クライアントのシングルトン（None: 未初期化、False: 接続失敗、redis.Redis: 接続済み）
_redis_client = None
# インプロセスフォールバック用のロックキーセット（Redis 未使用時のみ参照される）
_local_locks: set[str] = set()

# ── Redis Lua スクリプト: 原子的なロック解放 ──────────
# SET NX で取得したロックを、正しいトークンを持つ場合のみ削除する。
# Python 側で GET + DEL を分けて実行すると競合状態（TOCTOU）が発生するため、
# Lua スクリプトで原子的に実行することで安全性を確保する。
_RELEASE_SCRIPT = """
if redis.call('get', KEYS[1]) == ARGV[1] then
    return redis.call('del', KEYS[1])
else
    return 0
end
"""


def _get_redis():
    """
    Redis クライアントを取得する（遅延初期化・シングルトン）。

    初回呼び出し時に Redis への接続を試みる。
    接続成功時は redis.Redis インスタンスをキャッシュし、
    接続失敗時は False をキャッシュして以降の接続試行をスキップする。

    settings.redis_url が空の場合は None を返す（インプロセスフォールバックを使用）。

    Returns:
        redis.Redis インスタンス（接続成功時）または None（未設定・接続失敗時）
    """
    global _redis_client
    from src.config import settings

    if not settings.redis_url:
        # redis_url が未設定の場合はインプロセスロックを使用
        return None
    if _redis_client is None:
        try:
            import redis

            # redis_url から Redis クライアントを生成（decode_responses=True で文字列として扱う）
            _redis_client = redis.from_url(settings.redis_url, decode_responses=True)
            # ping で接続確認（ここで失敗した場合は except に落ちる）
            _redis_client.ping()
            logger.info("Redis distributed lock enabled")
        except Exception as e:
            logger.warning("Redis unavailable, using in-process locks: %s", e)
            # False をセットすることで以降の接続試行をスキップ（パフォーマンス改善）
            _redis_client = False
    # False（接続失敗）の場合は None を返してインプロセスフォールバックを使用
    return _redis_client if _redis_client is not False else None


def try_acquire_lock(name: str, ttl_seconds: int = 180) -> str | None:
    """
    分散ロックの取得を試みる。

    ロックを取得できた場合は解放用のトークン（UUID4）を返す。
    ロックが既に他のプロセスに取得されている場合は None を返す（非ブロッキング）。

    Redis モードでは SET NX EX コマンドを使用した原子的な操作でロックを取得する。
    インプロセスモードでは set オブジェクトへの追加で擬似ロックを実現する。

    Args:
        name: ロック名（リソースを一意に識別する文字列、例: "autotrade:USDJPY"）
        ttl_seconds: ロックの最大保持時間（秒）。この時間を超えると自動解放される
                     （デフォルト: 180 秒 = 3 分）。デッドロック防止のための安全装置。

    Returns:
        ロック取得成功時: release_lock() に渡すための UUIDv4 トークン文字列
        ロック取得失敗時: None（別のプロセスがロックを保持中）
    """
    # UUIDv4 でロック所有者を一意に識別するトークンを生成
    # 同じ名前のロックでもトークンが異なることで、別のプロセスによる誤解放を防止
    token = str(uuid4())
    key = f"lock:{name}"  # Redis キーに "lock:" プレフィックスを付与
    client = _get_redis()
    if client:
        try:
            # SET NX EX: キーが存在しない場合のみ設定（NX）し、TTL を設定（EX）
            # 原子的な操作のため競合状態が発生しない
            if client.set(key, token, nx=True, ex=ttl_seconds):
                return token  # ロック取得成功
            return None  # ロックは既に他のプロセスが保持中
        except Exception as e:
            logger.warning("Redis lock acquire failed: %s", e)
            # Redis エラー時はインプロセスフォールバックに降格

    # インプロセスフォールバック: セットにキーが存在しない場合のみロック取得
    if key in _local_locks:
        return None  # 既に同プロセス内でロック取得済み
    _local_locks.add(key)
    return token


def release_lock(name: str, token: str) -> None:
    """
    取得したロックを解放する。

    Redis モードでは Lua スクリプトを使用して原子的にロックを解放する。
    トークンが一致する場合のみ削除することで、TTL 期限切れ後に別のプロセスが
    取得したロックを誤って解放することを防止する。

    インプロセスモードではセットからキーを削除する（discard は存在しない場合も安全）。

    Args:
        name: try_acquire_lock() に渡したロック名（同一の値を使用する）
        token: try_acquire_lock() が返したトークン文字列
    """
    key = f"lock:{name}"
    client = _get_redis()
    if client:
        try:
            # Lua スクリプトで原子的に「トークン確認 → 削除」を実行
            # KEYS[1] = ロックキー, ARGV[1] = 所有者トークン
            client.eval(_RELEASE_SCRIPT, 1, key, token)
        except Exception as e:
            logger.warning("Redis lock release failed: %s", e)
        return
    # インプロセスモード: discard は要素が存在しない場合もエラーなし（冪等）
    _local_locks.discard(key)


def lock_status() -> dict:
    """
    現在のロックバックエンドの状態を返す。

    デバッグ・監視用のエンドポイントや管理ツールから呼び出すことで、
    Redis が正しく設定されているかを確認できる。

    Returns:
        以下のキーを持つ辞書:
            - backend: 使用中のバックエンド名（"redis" または "in_process"）
            - redis_url_configured: settings.redis_url が設定されているか（bool）
    """
    from src.config import settings

    client = _get_redis()
    return {
        "backend": "redis" if client else "in_process",
        "redis_url_configured": bool(settings.redis_url),
    }
