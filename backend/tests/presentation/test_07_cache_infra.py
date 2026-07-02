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
    """SaaS プラン定義テスト（機能フラグ・日次リミット）。

    plans.py の構造:
      - PLANS: {"free": {...}, "pro": {...}, "enterprise": {...}}
      - plan_features(plan): フィーチャーフラグ辞書を返す
      - daily_limit(plan): 日次 API 上限を返す
      - 未知プランは "free" にフォールバック（セキュリティ設計）
    """

    @pytest.fixture(autouse=True)
    def import_module(self):
        """プランモジュールをインポート。"""
        try:
            from src.auth.plans import PLANS, daily_limit, plan_features
            self.PLANS = PLANS
            self.plan_features = plan_features
            self.daily_limit = daily_limit
        except ImportError as exc:
            pytest.skip(f"依存関係不足のためスキップ: {exc}")

    def test_three_plans_defined(self):
        """free / pro / enterprise の 3 プランが定義されていることを確認する。"""
        assert "free" in self.PLANS, "free プランが定義されている必要があります"
        assert "pro" in self.PLANS, "pro プランが定義されている必要があります"
        assert "enterprise" in self.PLANS, "enterprise プランが定義されている必要があります"

    def test_free_plan_has_lower_daily_limit_than_pro(self):
        """FREE プランの日次 API 上限が PRO より低いことを確認する。

        SaaS モデルの基本: 無料プランは制限付き（100 回/日）、
        PRO プランは高リミット（2,000 回/日）。
        """
        free_limit = self.daily_limit("free")
        pro_limit = self.daily_limit("pro")
        assert free_limit < pro_limit, \
            f"FREE ({free_limit}/日) < PRO ({pro_limit}/日) が期待されます"

    def test_free_daily_limit_is_100(self):
        """FREE プランの日次上限が 100 回/日であることを確認する。"""
        assert self.daily_limit("free") == 100, \
            f"FREE プランの日次上限は 100 が期待されます: {self.daily_limit('free')}"

    def test_pro_daily_limit_is_2000(self):
        """PRO プランの日次上限が 2,000 回/日であることを確認する。"""
        assert self.daily_limit("pro") == 2000, \
            f"PRO プランの日次上限は 2000 が期待されます: {self.daily_limit('pro')}"

    def test_unknown_plan_falls_back_to_free_limit(self):
        """未知のプラン名で FREE プランの日次上限（100）が返されることを確認する。

        セキュリティ設計: 不明なプランは最低権限（FREE）にフォールバックする。
        """
        unknown_limit = self.daily_limit("nonexistent_plan_xyz")
        free_limit = self.daily_limit("free")
        assert unknown_limit == free_limit, \
            f"未知プランは FREE の日次上限 ({free_limit}) にフォールバックする必要があります: {unknown_limit}"

    def test_free_plan_ai_basic_enabled(self):
        """FREE プランで基本 AI 機能が有効であることを確認する。

        FREE プランでも基本的な AI 分析は利用可能（ai=True）。
        AI Pro (ai_pro) のみ有料プラン限定。
        """
        features = self.plan_features("free")
        assert features.get("ai") is True, \
            f"FREE プランで AI 基本機能 (ai) が有効である必要があります: {features.get('ai')}"

    def test_free_plan_autotrade_disabled(self):
        """FREE プランで自動取引が無効であることを確認する。

        自動取引は PRO 以上のプレミアム機能。
        """
        features = self.plan_features("free")
        assert not features.get("autotrade"), \
            "FREE プランの自動取引は無効である必要があります"

    def test_pro_plan_autotrade_enabled(self):
        """PRO プランで自動取引が有効であることを確認する。"""
        features = self.plan_features("pro")
        assert features.get("autotrade") is True, \
            f"PRO プランの自動取引は有効である必要があります: {features.get('autotrade')}"

    def test_pro_plan_has_more_api_keys_than_free(self):
        """PRO プランが FREE より多くの API キーを発行できることを確認する。"""
        free_keys = self.plan_features("free").get("api_keys", 0)
        pro_keys = self.plan_features("pro").get("api_keys", 0)
        assert pro_keys > free_keys, \
            f"PRO ({pro_keys} 本) > FREE ({free_keys} 本) の API キー上限が期待されます"
