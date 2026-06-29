"""analysis_cache のテスト"""

from src.infra.analysis_cache import cache_get, cache_key, cache_put, get_or_compute


class TestAnalysisCache:
    """TTL キャッシュユーティリティのテスト"""

    def test_cache_key_format(self):
        assert cache_key("ml:trend", "usdjpy", days=200) == "ml:trend:USDJPY:days=200"

    def test_put_and_get(self):
        key = cache_key("test", "EURUSD", n=1)
        cache_put(key, {"value": 42}, ttl_seconds=60)
        assert cache_get(key) == {"value": 42}

    def test_get_or_compute(self):
        key = cache_key("test", "GBPUSD", n=2)
        calls = {"n": 0}

        def compute():
            calls["n"] += 1
            return {"computed": True}

        first = get_or_compute(key, compute, ttl_seconds=60)
        second = get_or_compute(key, compute, ttl_seconds=60)
        assert first == second == {"computed": True}
        assert calls["n"] == 1
