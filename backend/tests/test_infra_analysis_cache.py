"""分析結果の TTL キャッシュ — src.infra.analysis_cache のテスト"""

from unittest.mock import patch

import pytest

from src.config import settings
from src.infra.analysis_cache import cache_get, cache_key, cache_put, get_or_compute


class TestCacheKey:
    """cache_key() のテスト"""

    def test_without_parts(self):
        """追加パラメータが無ければ prefix:SYMBOL になること"""
        assert cache_key("mtf", "EURUSD") == "mtf:EURUSD"

    def test_symbol_is_uppercased(self):
        """シンボルは大文字に正規化すること（キーの重複を防ぐ）"""
        assert cache_key("mtf", "eurusd") == cache_key("mtf", "EURUSD")

    def test_with_parts(self):
        """パラメータを key=value 形式で連結すること"""
        assert cache_key("technical", "usdjpy", days=200) == "technical:USDJPY:days=200"

    def test_parts_are_sorted_for_determinism(self):
        """パラメータの指定順が違っても同じキーになること"""
        assert cache_key("x", "USDJPY", b=2, a=1) == cache_key("x", "USDJPY", a=1, b=2)
        assert cache_key("x", "USDJPY", b=2, a=1) == "x:USDJPY:a=1:b=2"

    def test_supports_string_values(self):
        """文字列パラメータも扱えること"""
        assert cache_key("ml", "USDJPY", model="rf") == "ml:USDJPY:model=rf"

    def test_different_params_yield_different_keys(self):
        """パラメータが異なれば別キーになること"""
        assert cache_key("t", "USDJPY", days=90) != cache_key("t", "USDJPY", days=200)

    def test_prefix_separates_namespaces(self):
        """prefix が異なれば別キーになること"""
        assert cache_key("mtf", "USDJPY") != cache_key("ml", "USDJPY")


class TestCachePutGet:
    """cache_put() / cache_get() のテスト"""

    def test_roundtrip(self):
        """保存した値を取り出せること"""
        key = cache_key("test", "EURUSD", case="roundtrip")
        cache_put(key, {"value": 42}, ttl_seconds=60)
        assert cache_get(key) == {"value": 42}

    def test_missing_key_returns_none(self):
        """未保存のキーは None を返すこと"""
        assert cache_get(cache_key("test", "NOPE", case="missing")) is None

    def test_overwrites_existing_value(self):
        """同じキーへの再保存で上書きされること"""
        key = cache_key("test", "EURUSD", case="overwrite")
        cache_put(key, {"v": 1}, ttl_seconds=60)
        cache_put(key, {"v": 2}, ttl_seconds=60)
        assert cache_get(key) == {"v": 2}

    def test_uses_default_ttl_when_omitted(self):
        """TTL 省略時は設定の既定値を使うこと"""
        with patch("src.infra.analysis_cache.dynamodb_client") as client:
            cache_put("k", {"v": 1})
        assert client.put.call_args.kwargs["ttl_seconds"] == settings.analysis_cache_ttl_seconds

    def test_explicit_ttl_overrides_the_default(self):
        """TTL を指定すればそれを使うこと"""
        with patch("src.infra.analysis_cache.dynamodb_client") as client:
            cache_put("k", {"v": 1}, ttl_seconds=5)
        assert client.put.call_args.kwargs["ttl_seconds"] == 5

    def test_zero_ttl_is_respected(self):
        """TTL に 0 を指定しても既定値で上書きされないこと"""
        with patch("src.infra.analysis_cache.dynamodb_client") as client:
            cache_put("k", {"v": 1}, ttl_seconds=0)
        assert client.put.call_args.kwargs["ttl_seconds"] == 0

    def test_delegates_to_the_backend(self):
        """バックエンド（DynamoDB / インメモリ）へ委譲すること"""
        with patch("src.infra.analysis_cache.dynamodb_client") as client:
            client.get.return_value = {"cached": True}
            assert cache_get("some-key") == {"cached": True}
        client.get.assert_called_once_with("some-key")


class TestGetOrCompute:
    """get_or_compute() のテスト"""

    def test_computes_on_miss(self):
        """キャッシュミス時は計算関数を実行すること"""
        key = cache_key("test", "GBPUSD", case="miss")
        assert get_or_compute(key, lambda: {"computed": True}, ttl_seconds=60) == {"computed": True}

    def test_reuses_the_cached_value(self):
        """2 回目はキャッシュを返し、計算を再実行しないこと"""
        key = cache_key("test", "GBPUSD", case="reuse")
        calls = {"n": 0}

        def compute():
            calls["n"] += 1
            return {"computed": True}

        first = get_or_compute(key, compute, ttl_seconds=60)
        second = get_or_compute(key, compute, ttl_seconds=60)

        assert first == second
        assert calls["n"] == 1

    def test_non_dict_results_are_not_cached(self):
        """辞書以外の戻り値はキャッシュしないこと（保存形式の制約）"""
        key = cache_key("test", "GBPUSD", case="nondict")
        calls = {"n": 0}

        def compute():
            calls["n"] += 1
            return [1, 2, 3]

        assert get_or_compute(key, compute) == [1, 2, 3]
        assert get_or_compute(key, compute) == [1, 2, 3]
        assert calls["n"] == 2

    def test_passes_the_ttl_through(self):
        """指定した TTL でキャッシュへ保存すること"""
        with patch("src.infra.analysis_cache.dynamodb_client") as client:
            client.get.return_value = None
            get_or_compute("k", lambda: {"v": 1}, ttl_seconds=30)

        assert client.put.call_args.kwargs["ttl_seconds"] == 30

    def test_compute_exceptions_propagate(self):
        """計算中の例外は握りつぶさず呼び出し元へ伝えること"""
        def boom():
            raise RuntimeError("compute failed")

        with pytest.raises(RuntimeError, match="compute failed"):
            get_or_compute(cache_key("test", "X", case="boom"), boom)
