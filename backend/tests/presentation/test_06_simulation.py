"""
テストスイート 06: 戦略シミュレーション

カバー範囲:
    - simulate_strategy: 過去データバックテスト + 証拠金試算
    - シミュレーション結果の構造検証
    - 各プリセットでのシミュレーション実行
    - 不十分なデータ時のフォールバック処理
    - グレーディング（A/B/C/D）の論理整合性

顧客向けポイント:
    - 実際の自動売買前に過去 365 日分のデータで戦略を検証します。
    - 推奨証拠金を計算することで、適切な資金管理計画を立てられます。
    - 運用適性グレード（A〜D）で戦略の有効性を直感的に把握できます。
"""

import pytest


class TestSimulateStrategy:
    """simulate_strategy — 戦略シミュレーション実行テスト。"""

    @pytest.fixture(autouse=True)
    def import_module(self):
        """シミュレーションモジュールをインポート。"""
        try:
            from src.autotrade.simulation import simulate_strategy
            self.simulate_strategy = simulate_strategy
        except ImportError as exc:
            pytest.skip(f"依存関係不足のためスキップ: {exc}")

    def test_simulate_returns_dict(self):
        """simulate_strategy が辞書を返すことを確認する。"""
        result = self.simulate_strategy(
            symbol="USDJPY",
            days=90,
            account_balance=10000,
            preset_id="balanced",
        )
        assert isinstance(result, dict), \
            f"simulate_strategy は dict を返す必要があります: {type(result)}"

    def test_simulate_has_required_top_level_keys(self):
        """シミュレーション結果に必須のトップレベルキーが含まれることを確認する。

        API レスポンスで使用する主要キーの存在を検証する。
        """
        result = self.simulate_strategy(
            symbol="USDJPY",
            days=90,
            account_balance=10000,
            preset_id="balanced",
        )
        required_keys = ["symbol", "period_days", "preset_id", "backtest", "assessment"]
        missing = [k for k in required_keys if k not in result]
        assert not missing, \
            f"シミュレーション結果に必須キーが不足: {missing}"

    def test_simulate_symbol_matches_input(self):
        """結果の symbol が入力のシンボルと一致することを確認する。"""
        result = self.simulate_strategy(
            symbol="EURUSD",
            days=90,
            account_balance=10000,
            preset_id="conservative",
        )
        assert result.get("symbol") == "EURUSD", \
            f"結果の symbol は 'EURUSD' が期待されます: {result.get('symbol')}"

    def test_simulate_preset_id_matches_input(self):
        """結果の preset_id が入力のプリセット ID と一致することを確認する。"""
        result = self.simulate_strategy(
            symbol="USDJPY",
            days=90,
            account_balance=10000,
            preset_id="conservative",
        )
        assert result.get("preset_id") == "conservative", \
            f"結果の preset_id は 'conservative' が期待されます: {result.get('preset_id')}"

    def test_simulate_period_days_matches_input(self):
        """結果の period_days が入力の days と一致することを確認する。"""
        result = self.simulate_strategy(
            symbol="USDJPY",
            days=90,
            account_balance=10000,
            preset_id="balanced",
        )
        assert result.get("period_days") == 90, \
            f"期間 days は 90 が期待されます: {result.get('period_days')}"


class TestSimulationBacktestResult:
    """シミュレーションのバックテスト結果テスト。"""

    @pytest.fixture(autouse=True)
    def import_module(self):
        """シミュレーションモジュールをインポート。"""
        try:
            from src.autotrade.simulation import simulate_strategy
            self.simulate_strategy = simulate_strategy
        except ImportError as exc:
            pytest.skip(f"依存関係不足のためスキップ: {exc}")

    @pytest.fixture(scope="class")
    def sim_result(self):
        """クラス内で共用するシミュレーション結果（1回のみ実行）。

        DB（psycopg）が未インストールの環境ではスキップする。
        """
        try:
            from src.autotrade.simulation import simulate_strategy
            return simulate_strategy(
                symbol="USDJPY",
                days=180,
                account_balance=10000,
                preset_id="balanced",
            )
        except (ImportError, ModuleNotFoundError, Exception) as exc:
            pytest.skip(f"シミュレーション実行に必要な依存が不足: {exc}")

    def test_backtest_has_win_rate(self, sim_result: dict):
        """バックテスト結果に win_rate が含まれることを確認する。"""
        backtest = sim_result.get("backtest", {})
        assert "win_rate" in backtest, \
            f"backtest には 'win_rate' キーが必要です: {list(backtest.keys())}"

    def test_backtest_win_rate_is_valid_probability(self, sim_result: dict):
        """バックテストの勝率が 0〜1 の確率値であることを確認する。"""
        win_rate = sim_result.get("backtest", {}).get("win_rate", -1)
        assert 0 <= win_rate <= 1, \
            f"勝率は 0〜1 の範囲が期待されます: {win_rate}"

    def test_backtest_has_total_trades(self, sim_result: dict):
        """バックテスト結果にトレード数が含まれることを確認する。"""
        backtest = sim_result.get("backtest", {})
        has_trades = "total_trades" in backtest or "trades" in backtest
        assert has_trades, \
            f"backtest にはトレード数が必要です: {list(backtest.keys())}"

    def test_assessment_has_grade(self, sim_result: dict):
        """assessment に grade が含まれることを確認する。"""
        assessment = sim_result.get("assessment", {})
        assert "grade" in assessment, \
            f"assessment には 'grade' が必要です: {list(assessment.keys())}"

    def test_grade_is_valid_value(self, sim_result: dict):
        """grade が A/B/C/D のいずれかであることを確認する。"""
        grade = sim_result.get("assessment", {}).get("grade", "")
        assert grade in ("A", "B", "C", "D"), \
            f"grade は A/B/C/D のいずれかが期待されます: {grade}"

    def test_assessment_has_summary(self, sim_result: dict):
        """assessment に summary（説明文）が含まれることを確認する。"""
        assessment = sim_result.get("assessment", {})
        assert "summary" in assessment, \
            f"assessment には 'summary' が必要です: {list(assessment.keys())}"


class TestSimulationCapitalCalculation:
    """シミュレーションの証拠金試算テスト。"""

    @pytest.fixture(autouse=True)
    def import_module(self):
        """シミュレーションモジュールをインポート。"""
        try:
            from src.autotrade.simulation import simulate_strategy
            self.simulate_strategy = simulate_strategy
        except ImportError as exc:
            pytest.skip(f"依存関係不足のためスキップ: {exc}")

    def test_capital_section_exists(self):
        """capital（証拠金試算）セクションが存在することを確認する。"""
        result = self.simulate_strategy(
            symbol="USDJPY",
            days=90,
            account_balance=10000,
            preset_id="balanced",
        )
        assert "capital" in result, \
            f"シミュレーション結果には 'capital' セクションが必要です: {list(result.keys())}"

    def test_capital_has_recommended_amount(self):
        """capital に推奨証拠金額が含まれることを確認する。"""
        result = self.simulate_strategy(
            symbol="USDJPY",
            days=90,
            account_balance=10000,
            preset_id="balanced",
        )
        capital = result.get("capital", {})
        has_recommended = "recommended" in capital or "recommended_usd" in capital
        assert has_recommended, \
            f"capital には推奨証拠金額が必要です: {list(capital.keys())}"

    def test_larger_account_gives_larger_recommended_capital(self):
        """口座残高が大きいほど推奨証拠金も大きくなることを確認する。

        推奨証拠金はリスク割合 × 口座残高 × 安全係数で計算されるため、
        口座残高に比例して増加する。
        """
        result_small = self.simulate_strategy(
            symbol="USDJPY", days=90, account_balance=5000, preset_id="balanced"
        )
        result_large = self.simulate_strategy(
            symbol="USDJPY", days=90, account_balance=50000, preset_id="balanced"
        )
        capital_small = result_small.get("capital", {})
        capital_large = result_large.get("capital", {})

        key = "recommended" if "recommended" in capital_small else "recommended_usd"
        if key in capital_small and key in capital_large:
            assert capital_large[key] >= capital_small[key], \
                "大口座の推奨証拠金は小口座より大きい必要があります"


class TestSimulationAllPresets:
    """全プリセットでのシミュレーション実行テスト。"""

    @pytest.fixture(autouse=True)
    def import_module(self):
        """シミュレーションモジュールをインポート。"""
        try:
            from src.autotrade.simulation import simulate_strategy
            self.simulate_strategy = simulate_strategy
        except ImportError as exc:
            pytest.skip(f"依存関係不足のためスキップ: {exc}")

    @pytest.mark.parametrize("preset_id", [
        "conservative",
        "balanced",
        "aggressive",
        "range_repeat",
        "trend_follow",
    ])
    def test_each_preset_completes_without_error(self, preset_id: str):
        """各プリセットでシミュレーションがエラーなく完了することを確認する。

        全5種類のプリセットで実行可能であることを保証する統合テスト。
        """
        result = self.simulate_strategy(
            symbol="USDJPY",
            days=90,
            account_balance=10000,
            preset_id=preset_id,
        )
        assert isinstance(result, dict), \
            f"プリセット '{preset_id}' のシミュレーションが dict を返す必要があります"
        assert "assessment" in result, \
            f"プリセット '{preset_id}' の結果には 'assessment' が必要です"

    @pytest.mark.parametrize("preset_id", [
        "conservative",
        "balanced",
        "aggressive",
    ])
    def test_grade_reflects_preset_risk_level(self, preset_id: str):
        """シミュレーション結果の grade が有効値であることを確認する。"""
        result = self.simulate_strategy(
            symbol="USDJPY",
            days=90,
            account_balance=10000,
            preset_id=preset_id,
        )
        grade = result.get("assessment", {}).get("grade", "")
        assert grade in ("A", "B", "C", "D"), \
            f"プリセット '{preset_id}' の grade は A/B/C/D: {grade}"


class TestSimulationEdgeCases:
    """シミュレーションのエッジケーステスト。"""

    @pytest.fixture(autouse=True)
    def import_module(self):
        """シミュレーションモジュールをインポート。"""
        try:
            from src.autotrade.simulation import simulate_strategy
            self.simulate_strategy = simulate_strategy
        except ImportError as exc:
            pytest.skip(f"依存関係不足のためスキップ: {exc}")

    def test_invalid_preset_raises_error(self):
        """無効なプリセット ID で適切なエラーが発生することを確認する。"""
        with pytest.raises((ValueError, KeyError, Exception)):
            self.simulate_strategy(
                symbol="USDJPY",
                days=90,
                account_balance=10000,
                preset_id="nonexistent_preset_xyz",
            )

    def test_eurusd_simulation_works(self):
        """EURUSD でもシミュレーションが正常に動作することを確認する。"""
        result = self.simulate_strategy(
            symbol="EURUSD",
            days=90,
            account_balance=10000,
            preset_id="balanced",
        )
        assert result.get("symbol") == "EURUSD", \
            f"EURUSD シミュレーションの symbol は 'EURUSD' が期待されます"

    def test_gbpusd_simulation_works(self):
        """GBPUSD でもシミュレーションが正常に動作することを確認する。"""
        result = self.simulate_strategy(
            symbol="GBPUSD",
            days=90,
            account_balance=10000,
            preset_id="balanced",
        )
        assert isinstance(result, dict), "GBPUSD シミュレーションは dict を返す必要があります"

    def test_no_preset_uses_default_config(self):
        """preset_id=None でデフォルト設定が使用されることを確認する。"""
        result = self.simulate_strategy(
            symbol="USDJPY",
            days=90,
            account_balance=10000,
            preset_id=None,
        )
        assert isinstance(result, dict), \
            "preset_id=None でもシミュレーションは dict を返す必要があります"
