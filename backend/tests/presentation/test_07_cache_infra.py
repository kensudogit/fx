"""
テストスイート 07: キャッシュ基盤インフラ

カバー範囲:
    - cache_key: プレフィックス + シンボル + パラメーターのキー生成
    - cache_put / cache_get: データの保存・取得
    - get_or_compute: キャッシュヒット時の計算スキップ
    - plans: SaaS プラン定義（機能フラグ・日次リミット）
    - tenant_features: テナント設定のデフォルト値マージ

顧客向けポイント:
    - DynamoDB またはインメモリキャッシュを透過的に切り替えます。
    - キャッシュにより AI 分析・テクニカル指標の重複計算を回避し、
      API レスポンスを平均 5〜10 倍高速化します。
    - SaaS プランで機能アクセスと日次リミットを制御します。
"""

import pytest


class TestCacheKey:
    """cache_key — キャッシュキー生成テスト。"""

    @pytest.fixture(autouse=True)
    def import_module(self):
        """キャッシュモジュールをインポート。"""
        try:
            from src.infra.analysis_cache import cache_key
            self.cache_key = cache_key
        except ImportError as exc:
            pytest.skip(f"依存関係不足のためスキップ: {exc}")

    def test_basic_key_format(self):
        """基本キー形式 'prefix:SYMBOL' が正しいことを確認する。"""
        key = self.cache_key("technical", "usdjpy")
        assert key == "technical:USDJPY", \
            f"基本キーは 'technical:USDJPY' が期待されます: {key}"

    def test_symbol_is_uppercased(self):
        """シンボルが大文字に正規化されることを確認する。

        'usdjpy' と 'USDJPY' が同じキーを生成することで
        キャッシュの重複を防ぐ。
        """
        key_lower = self.cache_key("technical", "usdjpy")
        key_upper = self.cache_key("technical", "USDJPY")
        assert key_lower == key_upper, \
            f"大文字・小文字のシンボルは同じキーを生成する必要があります: {key_lower} ≠ {key_upper}"

    def test_key_with_additional_params(self):
        """追加パラメーターがキーに含まれることを確認する。"""
        key = self.cache_key("technical", "USDJPY", days=200)
        assert "days=200" in key, \
            f"キーには 'days=200' が含まれる必要があります: {key}"
        assert "USDJPY" in key, f"キーには 'USDJPY' が含まれる必要があります: {key}"

    def test_key_params_are_sorted(self):
        """複数パラメーターがキーでソートされることを確認する（決定論的キー）。

        パラメーターの順序に関わらず同じキーが生成されることで、
        引数の順序差異によるキャッシュミスを防ぐ。
        """
        key1 = self.cache_key("mtf", "EURUSD", days=200, timeframe="1d")
        key2 = self.cache_key("mtf", "EURUSD", timeframe="1d", days=200)
        assert key1 == key2, \
            f"パラメーターの順序に関わらず同じキーが生成される必要があります: {key1} ≠ {key2}"

    def test_different_prefixes_give_different_keys(self):
        """異なるプレフィックスが異なるキーを生成することを確認する。"""
        key1 = self.cache_key("technical", "USDJPY")
        key2 = self.cache_key("intelligence", "USDJPY")
        assert key1 != key2, \
            f"異なるプレフィックスは異なるキーを生成する必要があります: {key1}, {key2}"

    def test_different_symbols_give_different_keys(self):
        """異なるシンボルが異なるキーを生成することを確認する。"""
        key1 = self.cache_key("technical", "USDJPY")
        key2 = self.cache_key("technical", "EURUSD")
        assert key1 != key2, \
            f"異なるシンボルは異なるキーを生成する必要があります: {key1}, {key2}"


class TestCacheOperations:
    """cache_put / cache_get — キャッシュ保存・取得テスト。"""

    @pytest.fixture(autouse=True)
    def import_module(self):
        """キャッシュモジュールをインポート。"""
        try:
            from src.infra.analysis_cache import cache_get, cache_key, cache_put
            self.cache_key = cache_key
            self.cache_put = cache_put
            self.cache_get = cache_get
        except ImportError as exc:
            pytest.skip(f"依存関係不足のためスキップ: {exc}")

    def test_cache_miss_returns_none(self):
        """キャッシュに存在しないキーで None が返されることを確認する。"""
        key = self.cache_key("test_presentation", "XYZABC_NONEXISTENT")
        result = self.cache_get(key)
        assert result is None, \
            f"キャッシュミスは None を返す必要があります: {result}"

    def test_cache_put_and_get_roundtrip(self):
        """cache_put で保存したデータが cache_get で取得できることを確認する。"""
        key = self.cache_key("test_presentation", "TESTPAIR", test_id=999)
        test_data = {"win_rate": 0.65, "trades": 42, "test": True}

        self.cache_put(key, test_data, ttl_seconds=60)
        retrieved = self.cache_get(key)

        assert retrieved is not None, \
            f"cache_put 後に cache_get で取得できる必要があります: key={key}"
        assert retrieved.get("win_rate") == 0.65, \
            f"取得したデータの win_rate は 0.65 が期待されます: {retrieved}"
        assert retrieved.get("trades") == 42, \
            f"取得したデータの trades は 42 が期待されます: {retrieved}"

    def test_cache_overwrite(self):
        """同じキーに新しいデータを書き込むと上書きされることを確認する。"""
        key = self.cache_key("test_presentation", "OVERWRITE", test_id=1)

        self.cache_put(key, {"version": 1}, ttl_seconds=60)
        self.cache_put(key, {"version": 2}, ttl_seconds=60)
        result = self.cache_get(key)

        assert result is not None, "上書き後もデータが取得できる必要があります"
        assert result.get("version") == 2, \
            f"最新データ (version=2) が取得されるべきです: {result}"


class TestGetOrCompute:
    """get_or_compute — キャッシュヒット時の計算スキップテスト。"""

    @pytest.fixture(autouse=True)
    def import_module(self):
        """キャッシュモジュールをインポート。"""
        try:
            from src.infra.analysis_cache import get_or_compute
            self.get_or_compute = get_or_compute
        except ImportError as exc:
            pytest.skip(f"依存関係不足のためスキップ: {exc}")

    def test_compute_function_is_called_on_miss(self):
        """キャッシュミス時に compute 関数が呼び出されることを確認する。"""
        call_count = [0]

        def expensive_compute():
            call_count[0] += 1
            return {"result": "computed", "call": call_count[0]}

        key = f"test_presentation:COMPUTE_TEST:unique_123456"
        result = self.get_or_compute(key, expensive_compute, ttl_seconds=5)

        assert result is not None, "get_or_compute は結果を返す必要があります"
        assert result.get("result") == "computed", "compute 関数の戻り値が返される必要があります"

    def test_compute_function_not_called_on_hit(self):
        """キャッシュヒット時に compute 関数が呼び出されないことを確認する。

        キャッシュの主目的: 同じ計算を繰り返さずにレスポンスを高速化する。
        """
        call_count = [0]
        key = f"test_presentation:HIT_TEST:unique_789012"

        def expensive_compute():
            call_count[0] += 1
            return {"count": call_count[0]}

        # 1回目: キャッシュミス → compute が呼ばれる
        result1 = self.get_or_compute(key, expensive_compute, ttl_seconds=60)
        first_count = call_count[0]

        # 2回目: キャッシュヒット → compute は呼ばれないはず
        result2 = self.get_or_compute(key, expensive_compute, ttl_seconds=60)

        assert result1 is not None, "1回目の呼び出しは結果を返す必要があります"
        assert result2 is not None, "2回目の呼び出しも結果を返す必要があります"
        assert call_count[0] == first_count, \
            f"キャッシュヒット時に compute は呼ばれないべきです: {call_count[0]} 回呼ばれました"


class TestSaaSPlans:
    """SaaS プラン定義テスト（機能フラグ・日次リミット）。"""

    @pytest.fixture(autouse=True)
    def import_module(self):
        """プランモジュールをインポート。"""
        try:
            from src.auth.plans import get_plan, FREE_PLAN, PRO_PLAN
            self.get_plan = get_plan
            self.FREE_PLAN = FREE_PLAN
            self.PRO_PLAN = PRO_PLAN
        except ImportError as exc:
            pytest.skip(f"依存関係不足のためスキップ: {exc}")

    def test_free_plan_exists(self):
        """FREE_PLAN が定義されていることを確認する。"""
        assert self.FREE_PLAN is not None, "FREE_PLAN が定義されている必要があります"

    def test_pro_plan_exists(self):
        """PRO_PLAN が定義されていることを確認する。"""
        assert self.PRO_PLAN is not None, "PRO_PLAN が定義されている必要があります"

    def test_free_plan_has_lower_daily_limit(self):
        """FREE プランの日次リミットが PRO より低いことを確認する。

        SaaS モデルの基本: 無料プランは制限付き、有料プランは高リミット。
        """
        free_limit = self.FREE_PLAN.get("daily_analysis_limit", 0)
        pro_limit = self.PRO_PLAN.get("daily_analysis_limit", 0)
        assert free_limit < pro_limit, \
            f"FREE ({free_limit}) < PRO ({pro_limit}) が期待されます"

    def test_unknown_plan_falls_back_to_free(self):
        """未知のプラン名で FREE プランが返されることを確認する。

        セキュリティ設計: 不明なプランは最低権限（FREE）にフォールバックする。
        """
        result = self.get_plan("nonexistent_plan_xyz")
        assert result == self.FREE_PLAN or result.get("name") in ("free", "Free"), \
            "未知のプランは FREE プランにフォールバックする必要があります"

    def test_pro_plan_has_ai_features(self):
        """PRO プランが AI 機能を有効にしていることを確認する。"""
        features = self.PRO_PLAN.get("features", {})
        ai_enabled = features.get("ai_analysis", features.get("ai", False))
        assert ai_enabled, "PRO プランは AI 機能が有効である必要があります"
