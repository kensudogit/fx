"""オートセレクト（3 問アンケート） — src.autotrade.autoselect のテスト"""

import pytest

from src.autotrade.autoselect import (
    CAPITAL_MAP,
    HORIZON_MAP,
    RISK_PRESET,
    STYLE_PRESET,
    autoselect,
)
from src.autotrade.presets import STRATEGY_PRESETS
from src.data.sample_data import SYMBOL_BASE_PRICES


class TestMappings:
    """選択肢マッピング定数のテスト"""

    def test_capital_amounts_increase(self):
        """運用資金は小額 < 中程度 < 大額 の順であること"""
        assert CAPITAL_MAP["small"] < CAPITAL_MAP["medium"] < CAPITAL_MAP["large"]

    def test_longer_horizon_trades_less(self):
        """期間が長いほど取引頻度を下げること"""
        assert (HORIZON_MAP["long"]["max_daily_trades"]
                <= HORIZON_MAP["medium"]["max_daily_trades"]
                <= HORIZON_MAP["short"]["max_daily_trades"])

    def test_longer_horizon_uses_longer_cooldown(self):
        """期間が長いほどクールダウンを長くすること"""
        assert (HORIZON_MAP["long"]["cooldown_minutes"]
                > HORIZON_MAP["medium"]["cooldown_minutes"]
                > HORIZON_MAP["short"]["cooldown_minutes"])

    def test_risk_presets_point_to_real_presets(self):
        """リスク許容度のマッピング先が実在するプリセットであること"""
        assert set(RISK_PRESET.values()) <= set(STRATEGY_PRESETS)

    def test_style_presets_point_to_real_presets(self):
        """スタイルのマッピング先が実在するプリセットであること"""
        named = {v for v in STYLE_PRESET.values() if v}
        assert named <= set(STRATEGY_PRESETS)

    def test_auto_style_defers_to_risk(self):
        """auto スタイルはリスク許容度に委ねること"""
        assert STYLE_PRESET["auto"] is None


class TestAutoselect:
    """autoselect() のテスト"""

    def test_returns_expected_keys(self):
        """推奨結果のキーが揃っていること"""
        assert set(autoselect()) == {
            "recommended_preset", "preset_label", "config", "rationale", "questions_answered",
        }

    @pytest.mark.parametrize("risk,preset", [
        ("low", "conservative"), ("medium", "balanced"), ("high", "aggressive"),
    ])
    def test_risk_appetite_drives_the_preset(self, risk, preset):
        """リスク許容度に応じたプリセットを推奨すること"""
        assert autoselect(risk_appetite=risk)["recommended_preset"] == preset

    @pytest.mark.parametrize("style,preset", [
        ("range", "range_repeat"), ("trend", "trend_follow"),
    ])
    def test_explicit_style_overrides_risk(self, style, preset):
        """スタイル指定はリスク許容度より優先されること"""
        assert autoselect(risk_appetite="high", style=style)["recommended_preset"] == preset

    def test_auto_style_uses_risk_appetite(self):
        """auto ではリスク許容度で決定すること"""
        assert autoselect(risk_appetite="low", style="auto")["recommended_preset"] == "conservative"

    @pytest.mark.parametrize("capital,balance", [
        ("small", 5000), ("medium", 20000), ("large", 100000),
    ])
    def test_capital_sets_the_account_balance(self, capital, balance):
        """運用資金の回答を口座残高へ反映すること"""
        assert autoselect(capital=capital)["config"]["account_balance"] == balance

    def test_horizon_sets_scheduling_parameters(self):
        """運用期間の回答をクールダウン・取引回数・実行間隔へ反映すること"""
        config = autoselect(horizon="long")["config"]
        for key, value in HORIZON_MAP["long"].items():
            assert config[key] == value

    def test_defaults_to_usdjpy(self):
        """通貨ペア未指定なら USDJPY を対象にすること"""
        assert autoselect()["config"]["symbols"] == ["USDJPY"]

    def test_filters_out_unknown_symbols(self):
        """対応していない通貨ペアは除外すること"""
        config = autoselect(preferred_symbols=["EURUSD", "XAUUSD"])["config"]
        assert config["symbols"] == ["EURUSD"]

    def test_falls_back_when_all_symbols_are_unknown(self):
        """すべて未対応なら USDJPY にフォールバックすること"""
        assert autoselect(preferred_symbols=["XAUUSD"])["config"]["symbols"] == ["USDJPY"]

    def test_limits_symbols_to_three(self):
        """対象通貨ペアは最大 3 つまでに絞ること"""
        config = autoselect(preferred_symbols=list(SYMBOL_BASE_PRICES))["config"]
        assert len(config["symbols"]) <= 3

    def test_symbols_are_uppercased(self):
        """通貨ペアは大文字へ正規化すること"""
        assert autoselect(preferred_symbols=["eurusd"])["config"]["symbols"] == ["EURUSD"]

    @pytest.mark.parametrize("field,value", [
        ("capital", "gigantic"), ("horizon", "forever"),
        ("risk_appetite", "extreme"), ("style", "scalping"),
    ])
    def test_unknown_answers_fall_back_to_defaults(self, field, value):
        """未知の回答は既定値へフォールバックすること（例外にしない）"""
        result = autoselect(**{field: value})
        assert result["questions_answered"][field] in (
            "medium", "auto") or result["recommended_preset"] in STRATEGY_PRESETS

    def test_echoes_the_answers(self):
        """回答内容をそのまま返すこと（UI の再表示用）"""
        answers = autoselect(capital="large", horizon="short",
                             risk_appetite="high", style="trend")["questions_answered"]
        assert answers == {"capital": "large", "horizon": "short",
                           "risk_appetite": "high", "style": "trend"}

    def test_preset_label_matches_the_catalog(self):
        """プリセットの表示名が定義と一致すること"""
        result = autoselect(risk_appetite="low")
        assert result["preset_label"] == STRATEGY_PRESETS["conservative"]["label"]

    def test_rationale_mentions_the_answers(self):
        """選定理由に回答内容とプリセット名を含めること"""
        rationale = autoselect(capital="small", horizon="short", risk_appetite="low")["rationale"]
        assert "小額" in rationale
        assert "短期" in rationale
        assert "低リスク" in rationale
        assert STRATEGY_PRESETS["conservative"]["label"] in rationale

    def test_config_carries_the_preset_id(self):
        """設定にプリセット ID が記録されること"""
        assert autoselect(risk_appetite="high")["config"]["strategy_preset"] == "aggressive"

    def test_low_risk_answers_produce_conservative_parameters(self):
        """低リスクの回答では信頼度閾値が高くリスク%が小さい設定になること"""
        low = autoselect(risk_appetite="low")["config"]
        high = autoselect(risk_appetite="high")["config"]

        assert low["min_confidence"] > high["min_confidence"]
        assert low["risk_percent"] < high["risk_percent"]
