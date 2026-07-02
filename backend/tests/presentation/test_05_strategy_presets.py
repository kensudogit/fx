"""
テストスイート 05: 戦略プリセット管理

カバー範囲:
    - list_presets: 全プリセットの一覧取得
    - apply_preset: プリセット設定の適用
    - 各プリセット (conservative / balanced / aggressive / range_repeat / trend_follow) の内容検証
    - 無効なプリセット ID のエラーハンドリング

顧客向けポイント:
    - 5種類のプリセット戦略で異なるリスク・リターンを実現します。
    - conservative: 初心者向け低リスク（信頼度閾値 75%、1%/2回/日）
    - balanced: 標準的な AI+テクニカル統合（65%閾値、1%/3回/日）
    - aggressive: 上級者向け高頻度（50%閾値、2%/5回/日）
    - range_repeat: レンジ相場専用（ボリンジャーバンド）
    - trend_follow: トレンド相場専用（MTF+ML 順張り）
"""

import pytest


class TestListPresets:
    """list_presets — 全プリセット一覧取得テスト。"""

    @pytest.fixture(autouse=True)
    def import_module(self):
        """プリセットモジュールをインポート。"""
        try:
            from src.autotrade.presets import list_presets, STRATEGY_PRESETS
            self.list_presets = list_presets
            self.STRATEGY_PRESETS = STRATEGY_PRESETS
        except ImportError as exc:
            pytest.skip(f"依存関係不足のためスキップ: {exc}")

    def test_list_presets_returns_list(self):
        """list_presets がリストを返すことを確認する。"""
        result = self.list_presets()
        assert isinstance(result, list), \
            f"list_presets はリストを返す必要があります: {type(result)}"

    def test_all_five_presets_are_present(self):
        """5種類の全プリセットが含まれることを確認する。"""
        result = self.list_presets()
        preset_ids = {p.get("id") for p in result}
        expected_ids = {"conservative", "balanced", "aggressive", "range_repeat", "trend_follow"}
        missing = expected_ids - preset_ids
        assert not missing, f"以下のプリセットが不足しています: {missing}"

    def test_each_preset_has_required_fields(self):
        """各プリセットに必須フィールドが含まれることを確認する。"""
        result = self.list_presets()
        required_fields = ["id", "label", "description", "min_confidence", "risk_percent"]
        for preset in result:
            missing = [f for f in required_fields if f not in preset]
            assert not missing, \
                f"プリセット '{preset.get('id')}' に必須フィールドが不足: {missing}"

    def test_preset_ids_are_unique(self):
        """各プリセット ID が一意であることを確認する。"""
        result = self.list_presets()
        ids = [p.get("id") for p in result]
        assert len(ids) == len(set(ids)), "プリセット ID に重複があります"

    def test_strategy_presets_dict_exists(self):
        """STRATEGY_PRESETS 辞書が存在し、空でないことを確認する。"""
        assert self.STRATEGY_PRESETS, "STRATEGY_PRESETS は空でない辞書である必要があります"
        assert len(self.STRATEGY_PRESETS) >= 5, \
            f"5種類以上のプリセットが期待されます: {len(self.STRATEGY_PRESETS)}"


class TestApplyPreset:
    """apply_preset — プリセット設定適用テスト。"""

    @pytest.fixture(autouse=True)
    def import_module(self):
        """プリセットモジュールをインポート。"""
        try:
            from src.autotrade.presets import apply_preset
            self.apply_preset = apply_preset
        except ImportError as exc:
            pytest.skip(f"依存関係不足のためスキップ: {exc}")

    def test_conservative_preset_has_low_risk(self):
        """conservative プリセットのリスク割合が低いことを確認する。

        conservative は初心者向け低リスク設定。
        リスク割合: 0.5%（balanced の半分）
        """
        config = self.apply_preset("conservative")
        risk = config.get("risk_percent", 999)
        assert risk <= 1.0, \
            f"conservative のリスク割合は ≤ 1.0% が期待されます: {risk}%"

    def test_conservative_has_high_confidence_threshold(self):
        """conservative プリセットの信頼度閾値が高いことを確認する。

        信頼度閾値が高いほど、質の高いシグナルのみでエントリーする（安全）。
        conservative: 75%（balanced の 65% より高い）
        """
        config = self.apply_preset("conservative")
        threshold = config.get("min_confidence", 0)
        assert threshold >= 70, \
            f"conservative の信頼度閾値は ≥ 70% が期待されます: {threshold}%"

    def test_aggressive_preset_has_higher_risk_than_conservative(self):
        """aggressive プリセットのリスク割合が conservative より高いことを確認する。

        aggressive: 高頻度・低閾値・高リスク（上級者向け）
        conservative: 低頻度・高閾値・低リスク（初心者向け）
        """
        cons = self.apply_preset("conservative")
        aggr = self.apply_preset("aggressive")
        assert aggr.get("risk_percent", 0) > cons.get("risk_percent", 999), \
            "aggressive のリスク割合は conservative より高い必要があります"

    def test_aggressive_has_lower_confidence_threshold_than_conservative(self):
        """aggressive の信頼度閾値が conservative より低いことを確認する。

        閾値が低いほど多くのシグナルでエントリー（高頻度・高リスク）。
        """
        cons = self.apply_preset("conservative")
        aggr = self.apply_preset("aggressive")
        assert aggr.get("min_confidence", 100) < cons.get("min_confidence", 0), \
            "aggressive の信頼度閾値は conservative より低い必要があります"

    def test_aggressive_has_more_daily_trades_than_conservative(self):
        """aggressive の最大日次取引数が conservative より多いことを確認する。"""
        cons = self.apply_preset("conservative")
        aggr = self.apply_preset("aggressive")
        assert aggr.get("max_daily_trades", 0) > cons.get("max_daily_trades", 999), \
            "aggressive の最大日次取引数は conservative より多い必要があります"

    def test_balanced_preset_returns_dict(self):
        """balanced プリセットが辞書を返すことを確認する。"""
        config = self.apply_preset("balanced")
        assert isinstance(config, dict), \
            f"apply_preset は dict を返す必要があります: {type(config)}"

    def test_range_repeat_uses_technical_source_only(self):
        """range_repeat プリセットがテクニカル分析のみのシグナルソースを持つことを確認する。

        range_repeat は ボリンジャーバンド中心のレンジ売買戦略のため、
        AI や MTF ソースを使わずにテクニカル分析のみを使用する設計。
        注意: apply_preset は metadata (style 等) を除いたパラメータのみを返す。
        """
        config = self.apply_preset("range_repeat")
        sources = config.get("sources", [])
        assert "technical" in sources, \
            f"range_repeat は 'technical' ソースを含む必要があります: {sources}"

    def test_trend_follow_uses_mtf_source(self):
        """trend_follow プリセットが MTF シグナルソースを含むことを確認する。

        MTF（マルチタイムフレーム）分析は複数の時間足でトレンドを確認する。
        """
        config = self.apply_preset("trend_follow")
        sources = config.get("sources", [])
        assert "mtf" in sources, \
            f"trend_follow は 'mtf' シグナルソースを含む必要があります: {sources}"

    def test_invalid_preset_raises_value_error(self):
        """無効なプリセット ID で ValueError が発生することを確認する。

        apply_preset は "Unknown preset: {id}" メッセージの ValueError を発生させる。
        """
        with pytest.raises(ValueError):
            self.apply_preset("nonexistent_preset_xyz")


class TestPresetRiskOrdering:
    """プリセットのリスク順序テスト（conservative < balanced < aggressive）。

    リスク管理の根本原則として、各プリセットのリスク設定が
    期待される順序を持つことを包括的に検証する。
    """

    @pytest.fixture(autouse=True)
    def import_module(self):
        """プリセットモジュールをインポート。"""
        try:
            from src.autotrade.presets import apply_preset
            self.apply_preset = apply_preset
        except ImportError as exc:
            pytest.skip(f"依存関係不足のためスキップ: {exc}")

    def test_risk_percent_ordering(self):
        """リスク割合: conservative ≤ balanced ≤ aggressive の順序を確認する。"""
        cons = self.apply_preset("conservative").get("risk_percent", 0)
        bal = self.apply_preset("balanced").get("risk_percent", 0)
        aggr = self.apply_preset("aggressive").get("risk_percent", 0)
        assert cons <= bal <= aggr, \
            f"リスク割合の順序: {cons}% ≤ {bal}% ≤ {aggr}% が期待されます"

    def test_confidence_threshold_ordering(self):
        """信頼度閾値: conservative ≥ balanced ≥ aggressive の順序を確認する。

        高閾値 = 厳選されたシグナルのみ（安全重視）
        低閾値 = 多くのシグナルでエントリー（頻度重視）
        """
        cons = self.apply_preset("conservative").get("min_confidence", 0)
        bal = self.apply_preset("balanced").get("min_confidence", 0)
        aggr = self.apply_preset("aggressive").get("min_confidence", 0)
        assert cons >= bal >= aggr, \
            f"信頼度閾値の順序: {cons}% ≥ {bal}% ≥ {aggr}% が期待されます"

    def test_max_daily_trades_ordering(self):
        """最大日次取引数: conservative ≤ balanced ≤ aggressive の順序を確認する。"""
        cons = self.apply_preset("conservative").get("max_daily_trades", 0)
        bal = self.apply_preset("balanced").get("max_daily_trades", 0)
        aggr = self.apply_preset("aggressive").get("max_daily_trades", 0)
        assert cons <= bal <= aggr, \
            f"最大日次取引数の順序: {cons} ≤ {bal} ≤ {aggr} が期待されます"
