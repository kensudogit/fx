"""
分析結果の TTL キャッシュ（DynamoDB またはプロセス内）— infra/analysis_cache

テクニカル分析・ML 予測・インテリジェンス分析などの計算コストの高い処理結果を
キャッシュするためのユーティリティモジュール。

バックエンドは DynamoDB またはインメモリキャッシュ（db/database.py の dynamodb_client）
を透過的に使用し、呼び出し元がストレージの種類を意識せずにキャッシュ操作を行える。

TTL 設定は settings の各 *_cache_ttl_seconds フィールドで管理され、
呼び出し側で明示的に指定しない場合はデフォルト（analysis_cache_ttl_seconds）が適用される。
"""

from __future__ import annotations

from typing import Callable, TypeVar

from src.config import settings
from src.db.database import dynamodb_client

# 型変数: get_or_compute の戻り値型を呼び出し元の compute 関数の戻り値型に合わせるための型パラメーター
T = TypeVar("T")


def cache_key(prefix: str, symbol: str, **parts: int | str) -> str:
    """
    一意なキャッシュキー文字列を生成する。

    キーの形式: "{prefix}:{SYMBOL}" または "{prefix}:{SYMBOL}:{k1=v1}:{k2=v2}:..."
    parts が指定された場合はキーでソートして決定論的なキー順序を保証する。

    Args:
        prefix: キャッシュキーのプレフィックス（例: "technical", "intelligence", "mtf"）
        symbol: 通貨ペアシンボル（大文字に正規化される）
        **parts: キャッシュキーに含める追加パラメーター（例: days=200, timeframe="1d"）

    Returns:
        一意なキャッシュキー文字列

    Example:
        >>> cache_key("technical", "usdjpy", days=200)
        'technical:USDJPY:days=200'
        >>> cache_key("mtf", "EURUSD")
        'mtf:EURUSD'
    """
    # シンボルを大文字に正規化（"usdjpy" → "USDJPY"）してキーの一意性を確保
    sym = symbol.upper()
    if not parts:
        # 追加パラメーターなし: シンプルな "prefix:SYMBOL" 形式
        return f"{prefix}:{sym}"
    # 追加パラメーターあり: ソートして決定論的な順序を保証
    # 例: {"days": 200, "timeframe": "1d"} → "days=200:timeframe=1d"
    suffix = ":".join(f"{k}={v}" for k, v in sorted(parts.items()))
    return f"{prefix}:{sym}:{suffix}"


def cache_get(key: str) -> dict | None:
    """
    キャッシュからデータを取得する。

    バックエンド（DynamoDB またはインメモリ）の違いを隠蔽し、
    統一されたインターフェースでキャッシュアクセスを提供する。

    Args:
        key: cache_key() で生成したキャッシュキー文字列

    Returns:
        キャッシュデータ辞書（TTL 内のキャッシュヒット時）、または None（キャッシュミス時）
    """
    return dynamodb_client.get(key)


def cache_put(key: str, data: dict, ttl_seconds: int | None = None) -> None:
    """
    キャッシュにデータを保存する。

    ttl_seconds が指定されない場合は settings.analysis_cache_ttl_seconds（デフォルト 15 分）
    を使用する。呼び出し元が分析種別に応じて TTL を調整できる。

    Args:
        key: キャッシュキー文字列
        data: 保存するデータ辞書（JSON シリアライズ可能な形式）
        ttl_seconds: キャッシュ有効期間（秒）。None の場合はデフォルト TTL を使用
    """
    # None の場合は設定ファイルのデフォルト TTL を使用
    ttl = ttl_seconds if ttl_seconds is not None else settings.analysis_cache_ttl_seconds
    dynamodb_client.put(key, data, ttl_seconds=ttl)


def get_or_compute(key: str, compute: Callable[[], T], ttl_seconds: int | None = None) -> T:
    """
    キャッシュヒット時は compute を呼ばず、キャッシュミス時のみ compute を実行してキャッシュに保存する。

    計算コストの高い分析処理（ML 予測・マルチタイムフレーム分析等）に使用し、
    同一リクエストの重複計算を回避することでレスポンスタイムを削減する。

    注意: compute の戻り値が dict 型の場合のみキャッシュに保存される。
    他の型（str, list, None 等）の場合はキャッシュ保存をスキップする。

    Args:
        key: キャッシュキー文字列（cache_key() で生成することを推奨）
        compute: キャッシュミス時に実行する計算関数（引数なし callable）
        ttl_seconds: キャッシュ有効期間（秒）。None の場合はデフォルト TTL を使用

    Returns:
        キャッシュデータまたは compute() の戻り値（型は compute の戻り値型 T と同じ）

    Example:
        result = get_or_compute(
            cache_key("technical", "USDJPY", days=200),
            lambda: compute_all_indicators(df),
            ttl_seconds=settings.analysis_cache_ttl_seconds,
        )
    """
    # キャッシュを確認し、ヒットした場合は計算をスキップして返す
    cached = cache_get(key)
    if cached is not None:
        return cached  # type: ignore[return-value]
    # キャッシュミス: compute を実行して結果を取得
    result = compute()
    # dict 型の場合のみキャッシュに保存（リスト・文字列・None はキャッシュ不可）
    if isinstance(result, dict):
        cache_put(key, result, ttl_seconds=ttl_seconds)
    return result
