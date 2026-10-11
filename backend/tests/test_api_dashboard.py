"""統合ダッシュボード — src.api.dashboard のテスト

各分析コンポーネントはモックへ差し替え、集約と障害時の耐性を検証する。
"""

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from src.api.dashboard import build_dashboard


@pytest.fixture
def stubs(ohlcv):
    """ダッシュボードが依存する全コンポーネントをモックする。"""
    with patch("src.api.dashboard.get_ohlcv_data", return_value=(ohlcv, "database")), \
         patch("src.api.dashboard.fetch_rss_news",
               new=AsyncMock(return_value=[{"title": "ドル円が上昇", "source": "Reuters"}])), \
         patch("src.api.dashboard.analyze_multi_timeframe",
               return_value={"alignment": "bullish", "alignment_label": "一致"}), \
         patch("src.api.dashboard.run_backtrader_backtest",
               return_value={"status": "success", "total_return_pct": 8.5}), \
         patch("src.api.dashboard.list_signals", return_value=[{"id": 1, "action": "buy"}]), \
         patch("src.api.dashboard.get_account_summary",
               return_value={"configured": False, "balance": 10000}), \
         patch("src.api.dashboard.list_orders", return_value=[{"id": 1}]), \
         patch("src.api.dashboard.resolve_openai_api_key", return_value="sk-test"), \
         patch("src.api.dashboard.get_tenant_id", return_value=1):
        yield


class TestBuildDashboard:
    """build_dashboard() のテスト"""

    def test_returns_all_sections(self, stubs):
        """ダッシュボードの全セクションを返すこと"""
        result = asyncio.run(build_dashboard("USDJPY"))

        assert set(result) == {
            "symbol", "price", "source", "signals", "multi_timeframe", "news_ml",
            "openai_configured", "backtest_simple", "backtest_backtrader",
            "tradingview_signals", "oanda", "recent_orders", "stack",
        }

    def test_normalizes_the_symbol(self, stubs):
        """シンボルを大文字化すること"""
        assert asyncio.run(build_dashboard("usdjpy"))["symbol"] == "USDJPY"

    def test_reports_price_and_source(self, stubs, ohlcv):
        """現在価格とデータソースを返すこと"""
        result = asyncio.run(build_dashboard("USDJPY"))

        assert result["price"] == round(float(ohlcv["close"].iloc[-1]), 4)
        assert result["source"] == "database"

    def test_signals_are_valid(self, stubs):
        """テクニカルシグナルが買い / 売りのいずれかであること"""
        for signal in asyncio.run(build_dashboard("USDJPY"))["signals"]:
            assert signal["signal"] in ("buy", "sell")

    def test_news_section_includes_article_count(self, stubs):
        """ニュース分析に記事数を付けること"""
        news = asyncio.run(build_dashboard("USDJPY"))["news_ml"]

        assert news["article_count"] == 1
        assert news["sentiment"] in ("bullish", "bearish", "neutral")

    def test_openai_flag_reflects_configuration(self, stubs):
        """OpenAI の設定状態を返すこと"""
        assert asyncio.run(build_dashboard("USDJPY"))["openai_configured"] is True

    def test_openai_flag_is_false_without_a_key(self, ohlcv):
        """API キーが無ければ False を返すこと"""
        with patch("src.api.dashboard.get_ohlcv_data", return_value=(ohlcv, "database")), \
             patch("src.api.dashboard.fetch_rss_news", new=AsyncMock(return_value=[])), \
             patch("src.api.dashboard.analyze_multi_timeframe", return_value={}), \
             patch("src.api.dashboard.run_backtrader_backtest", return_value={}), \
             patch("src.api.dashboard.list_signals", return_value=[]), \
             patch("src.api.dashboard.get_account_summary", return_value={}), \
             patch("src.api.dashboard.list_orders", return_value=[]), \
             patch("src.api.dashboard.resolve_openai_api_key", return_value=""), \
             patch("src.api.dashboard.get_tenant_id", return_value=1):
            assert asyncio.run(build_dashboard("USDJPY"))["openai_configured"] is False

    def test_backtrader_failure_is_reported_not_raised(self, ohlcv):
        """Backtrader が失敗してもダッシュボード全体は返すこと"""
        with patch("src.api.dashboard.get_ohlcv_data", return_value=(ohlcv, "database")), \
             patch("src.api.dashboard.fetch_rss_news", new=AsyncMock(return_value=[])), \
             patch("src.api.dashboard.analyze_multi_timeframe", return_value={}), \
             patch("src.api.dashboard.run_backtrader_backtest",
                   side_effect=RuntimeError("backtrader 未インストール")), \
             patch("src.api.dashboard.list_signals", return_value=[]), \
             patch("src.api.dashboard.get_account_summary", return_value={}), \
             patch("src.api.dashboard.list_orders", return_value=[]), \
             patch("src.api.dashboard.resolve_openai_api_key", return_value=""), \
             patch("src.api.dashboard.get_tenant_id", return_value=1):
            result = asyncio.run(build_dashboard("USDJPY"))

        assert result["backtest_backtrader"]["status"] == "error"
        assert "backtrader" in result["backtest_backtrader"]["message"]

    def test_simple_backtest_is_included(self, stubs):
        """簡易バックテストの結果を含めること"""
        bt = asyncio.run(build_dashboard("USDJPY"))["backtest_simple"]
        assert "win_rate" in bt
        assert "total_trades" in bt

    def test_broker_data_is_tenant_scoped(self, stubs):
        """ブローカー情報をテナント単位で取得すること"""
        with patch("src.api.dashboard.get_tenant_id", return_value=42), \
             patch("src.api.dashboard.list_orders", return_value=[]) as list_orders:
            asyncio.run(build_dashboard("USDJPY"))

        assert list_orders.call_args[0][1] == 42

    def test_stack_metadata_is_present(self, stubs):
        """技術スタックの説明を返すこと（フロントの注記用）"""
        stack = asyncio.run(build_dashboard("USDJPY"))["stack"]

        assert stack["api"].startswith("FastAPI")
        assert stack["frontend"].startswith("Next.js")

    def test_days_parameter_is_forwarded(self, ohlcv):
        """指定した日数で市場データを取得すること"""
        with patch("src.api.dashboard.get_ohlcv_data",
                   return_value=(ohlcv, "database")) as get_data, \
             patch("src.api.dashboard.fetch_rss_news", new=AsyncMock(return_value=[])), \
             patch("src.api.dashboard.analyze_multi_timeframe", return_value={}), \
             patch("src.api.dashboard.run_backtrader_backtest", return_value={}), \
             patch("src.api.dashboard.list_signals", return_value=[]), \
             patch("src.api.dashboard.get_account_summary", return_value={}), \
             patch("src.api.dashboard.list_orders", return_value=[]), \
             patch("src.api.dashboard.resolve_openai_api_key", return_value=""), \
             patch("src.api.dashboard.get_tenant_id", return_value=1):
            asyncio.run(build_dashboard("USDJPY", days=90))

        assert get_data.call_args[0][1] == 90
