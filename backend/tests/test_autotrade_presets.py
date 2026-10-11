"""自動売買のストラテジープリセット — src.autotrade.presets のテスト"""

import pytest

from src.autotrade.models import DEFAULT_CONFIG
from src.autotrade.presets import STRATEGY_PRESETS, apply_preset, list_presets

# 各プリセットが必ず備えるべきキー
REQUIRED_KEYS = {
    "id", "label", "description", "style", "min_confidence", "risk_percent",
    "max_daily_trades", "cooldown_minutes", "require_mtf_alignment",
    "event_blackout_hours", "sources", "risk_reward", "auto_exit_on_reverse", "min_units",
}

# 公開 API が返すキー（内部パラメータは含めない）
PUBLIC_KEYS = {"id", "label", "description", "style", "min_confidence",
               "risk_percent", "risk_reward"}


class TestPresetCatalog:
    """STRATEGY_PRESETS 定数のテスト"""

    def test_five_presets_are_defined(self):
        """5 種類のプリセットを提供すること"""
        assert set(STRATEGY_PRESETS) == {
            "conservative", "balanced", "aggressive", "range_repeat", "trend_follow",
        }

    @pytest.mark.parametrize("preset_id", sorted(STRATEGY_PRESETS))
    def test_every_preset_has_required_keys(self, preset_id):
        """すべてのプリセットが必要なキーを備えること"""
        assert set(STRATEGY_PRESETS[preset_id]) == REQUIRED_KEYS

    @pytest.mark.parametrize("preset_id", sorted(STRATEGY_PRESETS))
    def test_id_matches_the_dict_key(self, preset_id):
        """id フィールドが辞書キーと一致すること"""
        assert STRATEGY_PRESETS[preset_id]["id"] == preset_id

    @pytest.mark.parametrize("preset_id", sorted(STRATEGY_PRESETS))
    def test_parameters_are_within_sane_ranges(self, preset_id):
        """各パラメータが運用上妥当な範囲であること"""
        preset = STRATEGY_PRESETS[preset_id]
        assert 30 <= preset["min_confidence"] <= 95
        assert 0 < preset["risk_percent"] <= 10
        assert preset["max_daily_trades"] >= 1
        assert preset["cooldown_minutes"] >= 0
        assert preset["risk_reward"] > 0
        assert preset["min_units"] > 0

    @pytest.mark.parametrize("preset_id", sorted(STRATEGY_PRESETS))
    def test_style_is_a_known_value(self, preset_id):
        """取引スタイルは既知の値であること"""
        assert STRATEGY_PRESETS[preset_id]["style"] in ("trend", "range")

    @pytest.mark.parametrize("preset_id", sorted(STRATEGY_PRESETS))
    def test_sources_are_known_signal_types(self, preset_id):
        """シグナルソースは既定の設定で使われる種類に収まること"""
        known = set(DEFAULT_CONFIG["sources"]) | {"tradingview"}
        assert set(STRATEGY_PRESETS[preset_id]["sources"]) <= known
        assert STRATEGY_PRESETS[preset_id]["sources"], "ソースが空のプリセットがある"

    def test_conservative_is_stricter_than_aggressive(self):
        """安定型は積極型より信頼度閾値が高くリスクが小さいこと"""
        conservative = STRATEGY_PRESETS["conservative"]
        aggressive = STRATEGY_PRESETS["aggressive"]

        assert conservative["min_confidence"] > aggressive["min_confidence"]
        assert conservative["risk_percent"] < aggressive["risk_percent"]
        assert conservative["max_daily_trades"] <= aggressive["max_daily_trades"]

    def test_conservative_avoids_events_longer(self):
        """安定型はイベント回避時間が長いこと"""
        assert (STRATEGY_PRESETS["conservative"]["event_blackout_hours"]
                >= STRATEGY_PRESETS["aggressive"]["event_blackout_hours"])

    def test_balanced_matches_the_default_config(self):
        """バランス型は既定設定と同じ水準であること（既定プリセットのため）"""
        assert STRATEGY_PRESETS["balanced"]["min_confidence"] == DEFAULT_CONFIG["min_confidence"]
        assert STRATEGY_PRESETS["balanced"]["risk_percent"] == DEFAULT_CONFIG["risk_percent"]

    def test_range_preset_uses_range_style(self):
        """レンジ系プリセットは range スタイルであること"""
        assert STRATEGY_PRESETS["range_repeat"]["style"] == "range"

    def test_trend_preset_uses_trend_style(self):
        """トレンド系プリセットは trend スタイルであること"""
        assert STRATEGY_PRESETS["trend_follow"]["style"] == "trend"


class TestListPresets:
    """list_presets() のテスト"""

    def test_returns_every_preset(self):
        """すべてのプリセットを返すこと"""
        assert len(list_presets()) == len(STRATEGY_PRESETS)

    def test_exposes_only_public_fields(self):
        """内部パラメータ（sources 等）は公開しないこと"""
        for entry in list_presets():
            assert set(entry) == PUBLIC_KEYS

    def test_ids_match_the_catalog(self):
        """ID が定義と一致すること"""
        assert [e["id"] for e in list_presets()] == list(STRATEGY_PRESETS)

    def test_labels_and_descriptions_are_present(self):
        """UI 表示用のラベルと説明が空でないこと"""
        for entry in list_presets():
            assert entry["label"]
            assert entry["description"]


class TestApplyPreset:
    """apply_preset() のテスト"""

    def test_unknown_preset_raises(self):
        """未知のプリセット ID は ValueError になること"""
        with pytest.raises(ValueError, match="Unknown preset: nope"):
            apply_preset("nope")

    def test_records_the_preset_id(self):
        """適用したプリセット ID を設定へ記録すること"""
        assert apply_preset("aggressive")["strategy_preset"] == "aggressive"

    def test_copies_the_trading_parameters(self):
        """取引パラメータをプリセットの値で設定すること"""
        result = apply_preset("conservative")
        preset = STRATEGY_PRESETS["conservative"]

        assert result["min_confidence"] == preset["min_confidence"]
        assert result["risk_percent"] == preset["risk_percent"]
        assert result["sources"] == preset["sources"]

    def test_excludes_metadata_fields(self):
        """id / label / description / style は設定へ持ち込まないこと"""
        result = apply_preset("balanced")
        for key in ("id", "label", "description", "style"):
            assert key not in result

    def test_overrides_the_existing_config(self):
        """既存設定のパラメータをプリセットで上書きすること"""
        existing = {"min_confidence": 10, "risk_percent": 9.0}
        result = apply_preset("conservative", existing)

        assert result["min_confidence"] == STRATEGY_PRESETS["conservative"]["min_confidence"]
        assert result["risk_percent"] == STRATEGY_PRESETS["conservative"]["risk_percent"]

    def test_preserves_unrelated_settings(self):
        """プリセットが持たない設定項目は維持すること"""
        existing = {"enabled": True, "symbols": ["EURUSD"], "mode": "live"}
        result = apply_preset("balanced", existing)

        assert result["enabled"] is True
        assert result["symbols"] == ["EURUSD"]
        assert result["mode"] == "live"

    def test_does_not_mutate_the_input(self):
        """渡された設定辞書を書き換えないこと"""
        existing = {"min_confidence": 10}
        apply_preset("conservative", existing)
        assert existing == {"min_confidence": 10}

    def test_works_without_an_existing_config(self):
        """設定を渡さなくても適用できること"""
        assert apply_preset("balanced")["min_confidence"] > 0

    @pytest.mark.parametrize("preset_id", sorted(STRATEGY_PRESETS))
    def test_result_merges_cleanly_with_defaults(self, preset_id):
        """どのプリセットも既定設定とマージして矛盾のない設定になること"""
        merged = {**DEFAULT_CONFIG, **apply_preset(preset_id)}
        assert merged["strategy_preset"] == preset_id
        assert merged["symbols"]
