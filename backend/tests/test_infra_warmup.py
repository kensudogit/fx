"""起動時キャッシュウォームアップ — src.infra.warmup のテスト

重い分析処理はすべてモックへ差し替え、
対象シンボルの決定・並列実行・エラー隔離を検証する。
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.infra.warmup import warm_analysis_cache


@pytest.fixture
def warm_targets():
    """ウォームアップが呼び出す 5 つの処理をモックする。"""
    with patch("src.infra.warmup.analyze_multi_timeframe") as mtf, \
         patch("src.infra.warmup.predict_trend") as trend, \
         patch("src.infra.warmup.predict_price") as price, \
         patch("src.infra.warmup.build_intelligence", new_callable=AsyncMock) as intel, \
         patch("src.infra.warmup.gather_signal_context", new_callable=AsyncMock) as ctx:
        yield {"mtf": mtf, "trend": trend, "price": price, "intel": intel, "ctx": ctx}


class TestWarmAnalysisCache:
    """warm_analysis_cache() のテスト"""

    def test_does_nothing_when_disabled(self, warm_targets, override_settings):
        """設定で無効化されていれば何も実行しないこと"""
        override_settings(cache_warmup_enabled=False)
        asyncio.run(warm_analysis_cache())

        for mock in warm_targets.values():
            mock.assert_not_called()

    def test_does_nothing_for_empty_symbol_list(self, warm_targets, override_settings):
        """対象シンボルが空なら何も実行しないこと"""
        override_settings(cache_warmup_enabled=True, cache_warmup_symbols="  , ,")
        asyncio.run(warm_analysis_cache())

        warm_targets["mtf"].assert_not_called()

    def test_warms_every_configured_symbol(self, warm_targets, override_settings):
        """設定された全シンボルを処理すること"""
        override_settings(cache_warmup_enabled=True, cache_warmup_symbols="USDJPY,EURUSD")
        asyncio.run(warm_analysis_cache())

        warmed = {c.args[0] for c in warm_targets["mtf"].call_args_list}
        assert warmed == {"USDJPY", "EURUSD"}

    def test_normalizes_symbols(self, warm_targets, override_settings):
        """前後の空白を除去し大文字へ正規化すること"""
        override_settings(cache_warmup_enabled=True, cache_warmup_symbols=" usdjpy , eurusd ")
        asyncio.run(warm_analysis_cache())

        warmed = {c.args[0] for c in warm_targets["mtf"].call_args_list}
        assert warmed == {"USDJPY", "EURUSD"}

    def test_runs_all_five_analyses(self, warm_targets, override_settings):
        """MTF・トレンド・価格・統合分析・シグナル文脈をすべて事前計算すること"""
        override_settings(cache_warmup_enabled=True, cache_warmup_symbols="USDJPY")
        asyncio.run(warm_analysis_cache())

        for mock in warm_targets.values():
            mock.assert_called_once()

    def test_uses_200_bars_of_history(self, warm_targets, override_settings):
        """ML 予測は 200 本の履歴で事前計算すること"""
        override_settings(cache_warmup_enabled=True, cache_warmup_symbols="USDJPY")
        asyncio.run(warm_analysis_cache())

        assert warm_targets["trend"].call_args.args == ("USDJPY", 200)
        assert warm_targets["price"].call_args.args == ("USDJPY", 200)

    def test_one_symbol_failure_does_not_stop_others(self, warm_targets, override_settings):
        """1 シンボルが失敗しても他シンボルの処理を継続すること"""
        override_settings(cache_warmup_enabled=True, cache_warmup_symbols="USDJPY,EURUSD")
        warm_targets["mtf"].side_effect = lambda sym: (
            _ for _ in ()).throw(RuntimeError("boom")) if sym == "USDJPY" else None

        asyncio.run(warm_analysis_cache())

        # EURUSD 側は後続処理まで到達している
        assert warm_targets["trend"].call_args.args[0] == "EURUSD"

    def test_failure_is_not_propagated(self, warm_targets, override_settings):
        """すべて失敗しても呼び出し元へ例外を伝えないこと（起動を止めない）"""
        override_settings(cache_warmup_enabled=True, cache_warmup_symbols="USDJPY")
        warm_targets["mtf"].side_effect = RuntimeError("boom")

        asyncio.run(warm_analysis_cache())  # 例外が出なければ成功

    def test_single_symbol_configuration(self, warm_targets, override_settings):
        """1 シンボルのみの設定でも動作すること"""
        override_settings(cache_warmup_enabled=True, cache_warmup_symbols="GBPUSD")
        asyncio.run(warm_analysis_cache())

        assert warm_targets["mtf"].call_args.args == ("GBPUSD",)
