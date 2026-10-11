"""FastAPI アプリ本体 — src.main のテスト

サービス層はモックへ差し替え、HTTP 層（検証・応答形・エラー変換）と
アプリ構成（ルーター登録・CORS・ライフサイクル）を検証する。
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from src.analysis.technical import compute_all_indicators
from src.data.sample_data import SYMBOL_BASE_PRICES
from src.main import (
    _build_technical_response,
    _require_openai,
    _run_tradingview_autotrade,
    _validate_symbol,
    app,
    lifespan,
)


def with_timestamp(df):
    """DatetimeIndex を timestamp 列へ移した DataFrame を返す。

    API 層は index ではなく timestamp 列を参照するため。
    """
    out = df.copy()
    out.insert(0, "timestamp", out.index)
    return out.reset_index(drop=True)


@pytest.fixture
def timed_ohlcv(ohlcv):
    """timestamp 列を備えた 200 行の OHLCV データ。"""
    return with_timestamp(ohlcv)


@pytest.fixture
def client(monkeypatch):
    """SaaS 認証を無効化したテストクライアント。

    認証そのものは test_auth_middleware.py で検証しているため、
    ここでは各エンドポイントの振る舞いに集中する。
    """
    from src.config import settings

    monkeypatch.setattr(settings, "saas_enabled", False, raising=False)
    # TestClient を with なしで使うと lifespan（DB 初期化）は走らない
    return TestClient(app, raise_server_exceptions=False)


class TestAppConfiguration:
    """アプリ構成のテスト"""

    def test_metadata(self):
        """タイトルとバージョンを公開すること"""
        assert app.title == "FX Tool API"
        assert app.version == "2.1.0"

    def test_registers_every_feature_router(self):
        """認証・AI Pro・自動売買・ブローカー・価格の各ルーターを登録すること"""
        paths = {r.path for r in app.routes}
        for prefix in ("/api/auth/", "/api/pro/", "/api/autotrade/",
                       "/api/broker/", "/api/prices/"):
            assert any(p.startswith(prefix) for p in paths), prefix

    def test_installs_the_saas_auth_middleware(self):
        """SaaS 認証ミドルウェアを組み込むこと"""
        names = [m.cls.__name__ for m in app.user_middleware]
        assert "SaaSAuthMiddleware" in names

    def test_installs_cors(self):
        """フロントエンドからの呼び出しのため CORS を有効にすること"""
        names = [m.cls.__name__ for m in app.user_middleware]
        assert "CORSMiddleware" in names


class TestLifespan:
    """lifespan() のテスト"""

    def _run(self, **settings_overrides):
        from src.config import settings

        originals = {k: getattr(settings, k) for k in settings_overrides}
        for key, value in settings_overrides.items():
            setattr(settings, key, value)
        try:
            with patch("src.main.init_database") as init_db, \
                 patch("src.main.bootstrap_auth") as bootstrap, \
                 patch("src.main.refresh_economic_calendar", new=AsyncMock()) as calendar, \
                 patch("src.main.start_scheduler") as scheduler, \
                 patch("src.main.warm_analysis_cache", new=AsyncMock()) as warmup:
                async def drive():
                    async with lifespan(app):
                        pass
                    # create_task で起動されたウォームアップに実行機会を与える
                    await asyncio.sleep(0)

                asyncio.run(drive())
                return SimpleResult(init_db, bootstrap, calendar, scheduler, warmup)
        finally:
            for key, value in originals.items():
                setattr(settings, key, value)

    def test_initialises_the_database_and_auth(self):
        """起動時に DB と認証基盤を初期化すること"""
        calls = self._run(autotrade_enabled=False, cache_warmup_enabled=False)

        calls.init_db.assert_called_once()
        calls.bootstrap.assert_called_once()

    def test_warms_the_economic_calendar(self):
        """経済カレンダーを事前に読み込むこと"""
        calls = self._run(autotrade_enabled=False, cache_warmup_enabled=False)
        calls.calendar.assert_awaited_once()

    def test_calendar_failures_do_not_block_startup(self):
        """経済カレンダーの取得に失敗しても起動を続けること"""
        with patch("src.main.init_database"), \
             patch("src.main.bootstrap_auth"), \
             patch("src.main.refresh_economic_calendar",
                   new=AsyncMock(side_effect=OSError("api down"))), \
             patch("src.main.start_scheduler"):
            from src.config import settings

            autotrade, warmup = settings.autotrade_enabled, settings.cache_warmup_enabled
            settings.autotrade_enabled = settings.cache_warmup_enabled = False
            try:
                async def drive():
                    async with lifespan(app):
                        pass

                asyncio.run(drive())  # 例外が漏れないこと
            finally:
                settings.autotrade_enabled, settings.cache_warmup_enabled = autotrade, warmup

    def test_scheduler_starts_only_when_enabled(self):
        """自動売買スケジューラは設定が有効なときだけ起動すること"""
        assert self._run(autotrade_enabled=True,
                         cache_warmup_enabled=False).scheduler.called is True
        assert self._run(autotrade_enabled=False,
                         cache_warmup_enabled=False).scheduler.called is False

    def test_cache_warmup_only_when_enabled(self):
        """キャッシュのウォームアップは設定が有効なときだけ行うこと"""
        assert self._run(autotrade_enabled=False,
                         cache_warmup_enabled=True).warmup.called is True
        assert self._run(autotrade_enabled=False,
                         cache_warmup_enabled=False).warmup.called is False


class SimpleResult:
    """lifespan テストで参照するモック群。"""

    def __init__(self, init_db, bootstrap, calendar, scheduler, warmup):
        self.init_db = init_db
        self.bootstrap = bootstrap
        self.calendar = calendar
        self.scheduler = scheduler
        self.warmup = warmup


class TestValidateSymbol:
    """_validate_symbol() のテスト"""

    def test_uppercases_known_symbols(self):
        """対応シンボルは大文字化して返すこと"""
        assert _validate_symbol("usdjpy") == "USDJPY"

    def test_accepts_every_supported_symbol(self):
        """サポート対象の全シンボルを受け付けること"""
        for symbol in SYMBOL_BASE_PRICES:
            assert _validate_symbol(symbol) == symbol

    def test_unknown_symbol_raises_404(self):
        """未対応シンボルは 404 にすること"""
        with pytest.raises(HTTPException) as exc:
            _validate_symbol("XAUUSD")

        assert exc.value.status_code == 404
        assert "XAUUSD" in exc.value.detail


class TestBuildTechnicalResponse:
    """_build_technical_response() のテスト"""

    @pytest.fixture(scope="class")
    def response(self):
        from tests.conftest import make_ohlcv

        df = compute_all_indicators(with_timestamp(make_ohlcv(120)))
        return _build_technical_response("USDJPY", df, "database")

    def test_top_level_keys(self, response):
        """トップレベルのキーを揃えること"""
        assert set(response) == {"symbol", "source", "timestamps", "ohlcv",
                                 "indicators", "latest"}

    def test_timestamps_are_iso_formatted(self, response):
        """タイムスタンプを ISO 8601 文字列で返すこと（JSON 化のため）"""
        assert all(isinstance(t, str) and "T" in t for t in response["timestamps"])

    def test_ohlcv_series_align_with_timestamps(self, response):
        """OHLC の各系列がタイムスタンプと同じ長さであること"""
        n = len(response["timestamps"])
        assert all(len(v) == n for v in response["ohlcv"].values())

    def test_indicator_groups(self, response):
        """インジケーターを種別ごとにまとめて返すこと"""
        assert set(response["indicators"]) == {
            "ma", "bollinger_bands", "macd", "rsi", "stochastic", "ichimoku"}

    def test_moving_average_series(self, response):
        """移動平均は SMA20/50・EMA12/26 を返すこと"""
        assert set(response["indicators"]["ma"]) == {"sma_20", "sma_50", "ema_12", "ema_26"}

    def test_ichimoku_series(self, response):
        """一目均衡表は 5 本の線を返すこと"""
        assert set(response["indicators"]["ichimoku"]) == {
            "tenkan", "kijun", "senkou_a", "senkou_b", "chikou"}

    def test_latest_values(self, response):
        """最新足の終値・RSI・MACD を返すこと"""
        assert isinstance(response["latest"]["close"], float)
        assert isinstance(response["latest"]["rsi"], float)
        assert isinstance(response["latest"]["macd"], float)

    def test_latest_rsi_is_none_without_enough_history(self):
        """RSI は 14 本に満たなければ None にすること（NaN を JSON に出さない）"""
        from tests.conftest import make_ohlcv

        df = compute_all_indicators(with_timestamp(make_ohlcv(5)))
        latest = _build_technical_response("USDJPY", df, "sample")["latest"]

        assert latest["rsi"] is None
        # MACD は EMA ベースで最初の足から値が出るため None にはならない
        assert latest["macd"] is not None

    def test_source_is_passed_through(self, response):
        """データ取得元をそのまま返すこと"""
        assert response["source"] == "database"


class TestHealthEndpoint:
    """GET /health のテスト"""

    def test_reports_ok(self, client):
        """稼働中を示す status を返すこと"""
        assert client.get("/health").json()["status"] == "ok"

    def test_reports_the_ml_backend(self, client):
        """ML フレームワークとバックエンドの状況を返すこと"""
        body = client.get("/health").json()

        assert "ml_frameworks" in body
        assert "ml_price_backend" in body
        assert "ml_price_backend_config" in body

    def test_needs_no_authentication(self, client):
        """監視用途のため認証なしで応答すること"""
        assert client.get("/health").status_code == 200


class TestRootEndpoint:
    """GET / のテスト"""

    def test_redirects_to_the_docs(self, client):
        """Swagger UI へ誘導する HTML を返すこと"""
        body = client.get("/").text

        assert "/docs" in body
        assert "refresh" in body


class TestSymbolsEndpoint:
    """GET /api/symbols のテスト"""

    def test_lists_supported_symbols(self, client):
        """対応通貨ペアの一覧を返すこと"""
        assert client.get("/api/symbols").json()["symbols"] == list(SYMBOL_BASE_PRICES)


class TestSyncDataEndpoint:
    """POST /api/data/sync/{symbol} のテスト"""

    def test_returns_the_sync_result(self, client):
        """同期結果を返すこと"""
        with patch("src.main.sync_symbol_data", return_value={"rows_synced": 200}):
            body = client.post("/api/data/sync/USDJPY").json()

        assert body["rows_synced"] == 200

    def test_unknown_symbol_returns_404(self, client):
        """未対応シンボルは 404 にすること"""
        assert client.post("/api/data/sync/XAUUSD").status_code == 404

    @pytest.mark.parametrize("days", [10, 900])
    def test_days_is_range_checked(self, client, days):
        """期間の範囲外指定は 422 にすること"""
        assert client.post(f"/api/data/sync/USDJPY?days={days}").status_code == 422

    def test_sync_failures_become_500(self, client):
        """同期に失敗したら 500 とエラー内容を返すこと"""
        with patch("src.main.sync_symbol_data", side_effect=ValueError("yahoo down")):
            res = client.post("/api/data/sync/USDJPY")

        assert res.status_code == 500
        assert "yahoo down" in res.json()["detail"]


class TestOhlcvEndpoint:
    """GET /api/ohlcv/{symbol} のテスト"""

    def test_returns_rows(self, client, timed_ohlcv):
        """OHLCV の各足を返すこと"""
        with patch("src.main.get_ohlcv_data", return_value=(timed_ohlcv, "database")):
            body = client.get("/api/ohlcv/USDJPY").json()

        assert body["symbol"] == "USDJPY"
        assert body["source"] == "database"
        assert len(body["data"]) == len(timed_ohlcv)

    def test_rows_carry_the_ohlcv_fields(self, client, timed_ohlcv):
        """各足に OHLCV 一式を含めること"""
        with patch("src.main.get_ohlcv_data", return_value=(timed_ohlcv, "database")):
            row = client.get("/api/ohlcv/USDJPY").json()["data"][0]

        assert set(row) == {"timestamp", "open", "high", "low", "close", "volume"}

    def test_unknown_symbol_returns_404(self, client):
        """未対応シンボルは 404 にすること"""
        assert client.get("/api/ohlcv/XAUUSD").status_code == 404

    def test_days_is_forwarded(self, client, timed_ohlcv):
        """指定した日数をデータ層へ渡すこと"""
        with patch("src.main.get_ohlcv_data",
                   return_value=(timed_ohlcv, "database")) as get_data:
            client.get("/api/ohlcv/USDJPY?days=90")

        assert get_data.call_args[0][1] == 90


class TestTechnicalEndpoints:
    """テクニカル分析エンドポイントのテスト"""

    def test_signals_endpoint(self, client, timed_ohlcv):
        """最新足のシグナルと価格を返すこと"""
        with patch("src.main.get_ohlcv_data", return_value=(timed_ohlcv, "database")):
            body = client.get("/api/technical/USDJPY/signals").json()

        assert body["symbol"] == "USDJPY"
        assert all({"indicator", "signal", "reason"} <= set(s) for s in body["signals"])
        assert body["price"] == pytest.approx(float(timed_ohlcv["close"].iloc[-1]), abs=1e-4)

    def test_signals_unknown_symbol_returns_404(self, client):
        """未対応シンボルは 404 にすること"""
        assert client.get("/api/technical/XAUUSD/signals").status_code == 404

    def test_technical_endpoint_returns_indicators(self, client, timed_ohlcv):
        """インジケーター一式を返すこと"""
        with patch("src.main.get_ohlcv_data", return_value=(timed_ohlcv, "database")):
            body = client.get("/api/technical/USDJPY").json()

        assert "indicators" in body
        assert "latest" in body


class TestRequireOpenAI:
    """_require_openai() のテスト"""

    def test_passes_when_configured(self):
        """API キーが設定されていれば通過すること"""
        with patch("src.main.resolve_openai_api_key", return_value="sk-test"):
            _require_openai()  # 例外を投げないこと

    def test_missing_key_raises_503(self):
        """API キー未設定なら 503 と設定方法を返すこと"""
        with patch("src.main.resolve_openai_api_key", return_value=""):
            with pytest.raises(HTTPException) as exc:
                _require_openai()

        assert exc.value.status_code == 503
        assert "OPENAI_API_KEY" in exc.value.detail


class TestAiStatusEndpoint:
    """GET /api/ai/status のテスト"""

    def test_reports_configured(self, client):
        """設定済みであることとモデル名を返すこと"""
        with patch("src.main.resolve_openai_api_key", return_value="sk-abcdefghijkl"):
            body = client.get("/api/ai/status").json()

        assert body["configured"] is True
        assert body["model"]

    def test_only_previews_the_key(self, client):
        """API キーは先頭 8 文字のみ返すこと（全体を露出しない）"""
        with patch("src.main.resolve_openai_api_key", return_value="sk-abcdefghijkl"):
            body = client.get("/api/ai/status").json()

        assert body["key_preview"] == "sk-abcde..."
        assert "ghijkl" not in str(body)

    def test_reports_unconfigured(self, client):
        """未設定なら configured を False にすること"""
        with patch("src.main.resolve_openai_api_key", return_value=""):
            body = client.get("/api/ai/status").json()

        assert body["configured"] is False
        assert body["key_preview"] is None


class TestRunTradingviewAutotrade:
    """_run_tradingview_autotrade() のテスト"""

    def test_delegates_to_the_engine(self):
        """シグナルとテナントを自動売買エンジンへ渡すこと"""
        process = AsyncMock()
        with patch("src.autotrade.engine.process_tradingview_signal", new=process):
            asyncio.run(_run_tradingview_autotrade({"action": "buy"}, 7))

        process.assert_awaited_once_with({"action": "buy"}, 7)

    def test_errors_are_swallowed(self):
        """バックグラウンド実行のため例外は握りつぶしてログに残すこと"""
        with patch("src.autotrade.engine.process_tradingview_signal",
                   new=AsyncMock(side_effect=RuntimeError("engine down"))):
            asyncio.run(_run_tradingview_autotrade({"action": "buy"}, 7))


class TestTradingviewWebhook:
    """POST /api/tradingview/webhook のテスト"""

    def test_saves_the_signal(self, client, monkeypatch):
        """受信したシグナルを保存して 202 を返すこと"""
        from src.config import settings

        monkeypatch.setattr(settings, "tradingview_webhook_secret", "", raising=False)
        with patch("src.main.save_signal", return_value={"id": 1, "action": "buy"}), \
             patch("src.autotrade.models.get_config", return_value={"enabled": False}):
            res = client.post("/api/tradingview/webhook", json={"action": "buy"})

        assert res.status_code == 202
        assert res.json()["ok"] is True
        assert res.json()["autotrade"] is None

    def test_invalid_json_returns_400(self, client):
        """JSON として解釈できないボディは 400 にすること"""
        res = client.post("/api/tradingview/webhook", content=b"not json",
                          headers={"Content-Type": "application/json"})

        assert res.status_code == 400

    def test_wrong_secret_returns_401(self, client, monkeypatch):
        """Webhook シークレットが一致しなければ 401 にすること"""
        from src.config import settings

        monkeypatch.setattr(settings, "tradingview_webhook_secret", "s3cret", raising=False)
        res = client.post("/api/tradingview/webhook", json={"action": "buy"},
                          headers={"X-Webhook-Secret": "wrong"})

        assert res.status_code == 401

    def test_secret_can_come_from_the_header(self, client, monkeypatch):
        """ヘッダーのシークレットで認証できること"""
        from src.config import settings

        monkeypatch.setattr(settings, "tradingview_webhook_secret", "s3cret", raising=False)
        with patch("src.main.save_signal", return_value={"id": 1}), \
             patch("src.autotrade.models.get_config", return_value={"enabled": False}):
            res = client.post("/api/tradingview/webhook", json={"action": "buy"},
                              headers={"X-Webhook-Secret": "s3cret"})

        assert res.status_code == 202

    def test_secret_can_come_from_the_payload(self, client, monkeypatch):
        """ペイロード内の secret でも認証できること（TradingView はヘッダーを送れない）"""
        from src.config import settings

        monkeypatch.setattr(settings, "tradingview_webhook_secret", "s3cret", raising=False)
        with patch("src.main.save_signal", return_value={"id": 1}), \
             patch("src.autotrade.models.get_config", return_value={"enabled": False}):
            res = client.post("/api/tradingview/webhook",
                              json={"action": "buy", "secret": "s3cret"})

        assert res.status_code == 202

    def test_schedules_autotrade_when_enabled(self, client, monkeypatch):
        """自動実行が有効ならバックグラウンドで発注すること"""
        from src.config import settings

        monkeypatch.setattr(settings, "tradingview_webhook_secret", "", raising=False)
        process = AsyncMock()
        with patch("src.main.save_signal", return_value={"id": 1, "action": "buy"}), \
             patch("src.autotrade.models.get_config",
                   return_value={"enabled": True, "auto_execute_tradingview": True}), \
             patch("src.autotrade.engine.process_tradingview_signal", new=process):
            body = client.post("/api/tradingview/webhook", json={"action": "buy"}).json()

        assert body["autotrade"] == "processing"
        process.assert_awaited_once()

    def test_autotrade_is_skipped_when_disabled(self, client, monkeypatch):
        """自動売買が無効なら発注しないこと"""
        from src.config import settings

        monkeypatch.setattr(settings, "tradingview_webhook_secret", "", raising=False)
        with patch("src.main.save_signal", return_value={"id": 1}), \
             patch("src.autotrade.models.get_config",
                   return_value={"enabled": False, "auto_execute_tradingview": True}), \
             patch("src.autotrade.engine.process_tradingview_signal",
                   new=AsyncMock()) as process:
            client.post("/api/tradingview/webhook", json={"action": "buy"})

        process.assert_not_awaited()


class TestTradingviewSignalsEndpoint:
    """GET /api/tradingview/signals のテスト"""

    def test_returns_signals(self, client):
        """保存済みシグナルを返すこと"""
        with patch("src.main.list_signals", return_value=[{"id": 1}]):
            assert client.get("/api/tradingview/signals").json()["signals"] == [{"id": 1}]

    def test_filters_are_forwarded(self, client):
        """シンボルと件数の指定をサービス層へ渡すこと"""
        with patch("src.main.list_signals", return_value=[]) as list_fn:
            client.get("/api/tradingview/signals?symbol=USDJPY&limit=5")

        assert list_fn.call_args[0][:2] == ("USDJPY", 5)

    def test_limit_is_capped(self, client):
        """件数の上限（100）を超える指定は 422 にすること"""
        assert client.get("/api/tradingview/signals?limit=500").status_code == 422


class TestOandaEndpoints:
    """OANDA エンドポイントのテスト"""

    def test_status_returns_the_account_summary(self, client):
        """口座サマリーを返すこと"""
        with patch("src.main.get_account_summary", return_value={"configured": False}):
            assert client.get("/api/oanda/status").json()["configured"] is False

    def test_orders_returns_the_history(self, client):
        """注文履歴を返すこと"""
        with patch("src.main.list_orders", return_value=[{"id": 1}]):
            assert client.get("/api/oanda/orders").json()["orders"] == [{"id": 1}]

    def test_place_order_returns_the_confirmation(self, client):
        """発注結果を返すこと"""
        with patch("src.main.place_market_order", return_value={"status": "FILLED"}):
            res = client.post("/api/oanda/orders?symbol=USDJPY&side=buy&units=1000")

        assert res.json()["status"] == "FILLED"

    @pytest.mark.parametrize("side", ["hold", "BUY", ""])
    def test_place_order_rejects_invalid_sides(self, client, side):
        """buy / sell 以外の売買方向は 422 にすること"""
        res = client.post(f"/api/oanda/orders?symbol=USDJPY&side={side}&units=1000")
        assert res.status_code == 422

    @pytest.mark.parametrize("units", [0, 2_000_000])
    def test_place_order_range_checks_units(self, client, units):
        """取引単位の範囲外指定は 422 にすること"""
        res = client.post(f"/api/oanda/orders?symbol=USDJPY&side=buy&units={units}")
        assert res.status_code == 422

    def test_place_order_unknown_symbol_returns_404(self, client):
        """未対応シンボルは 404 にすること"""
        res = client.post("/api/oanda/orders?symbol=XAUUSD&side=buy&units=1000")
        assert res.status_code == 404

    def test_place_order_value_errors_become_400(self, client):
        """入力エラーは 400 にすること"""
        with patch("src.main.place_market_order", side_effect=ValueError("bad units")):
            res = client.post("/api/oanda/orders?symbol=USDJPY&side=buy&units=1000")

        assert res.status_code == 400
        assert "bad units" in res.json()["detail"]

    def test_place_order_broker_errors_become_502(self, client):
        """OANDA 側の障害は 502 にすること（クライアント起因と区別する）"""
        with patch("src.main.place_market_order", side_effect=OSError("oanda down")):
            res = client.post("/api/oanda/orders?symbol=USDJPY&side=buy&units=1000")

        assert res.status_code == 502
        assert "OANDA error" in res.json()["detail"]


class TestDashboardEndpoint:
    """GET /api/dashboard のテスト"""

    def test_returns_the_dashboard(self, client):
        """統合ダッシュボードを返すこと"""
        with patch("src.main.build_dashboard",
                   new=AsyncMock(return_value={"symbol": "USDJPY"})):
            assert client.get("/api/dashboard").json()["symbol"] == "USDJPY"

    def test_defaults_to_usdjpy(self, client):
        """シンボル未指定なら USDJPY を使うこと"""
        with patch("src.main.build_dashboard", new=AsyncMock(return_value={})) as build:
            client.get("/api/dashboard")

        assert build.await_args[0][0] == "USDJPY"

    def test_unknown_symbol_returns_404(self, client):
        """未対応シンボルは 404 にすること"""
        assert client.get("/api/dashboard?symbol=XAUUSD").status_code == 404

    def test_failures_become_500(self, client):
        """構築に失敗したら 500 にすること"""
        with patch("src.main.build_dashboard",
                   new=AsyncMock(side_effect=RuntimeError("boom"))):
            res = client.get("/api/dashboard")

        assert res.status_code == 500


class TestTestReportEndpoint:
    """GET /test-report のテスト"""

    def test_serves_the_generated_report(self, client, tmp_path):
        """生成済みレポートがあればその内容を返すこと"""
        report = tmp_path / "test_report.html"
        report.write_text("<html>report</html>", encoding="utf-8")
        with patch("src.main._REPORT_DIR", str(tmp_path)):
            assert "report" in client.get("/test-report").text

    def test_explains_how_to_generate_it(self, client, tmp_path):
        """レポート未生成なら生成方法を案内すること"""
        with patch("src.main._REPORT_DIR", str(tmp_path)):
            res = client.get("/test-report")

        assert res.status_code == 200
        assert "run_presentation_tests.bat" in res.text

    def test_is_hidden_from_the_schema(self):
        """OpenAPI スキーマには公開しないこと"""
        assert "/test-report" not in app.openapi()["paths"]


class TestAnalysisEndpoints:
    """5 大分析エンドポイントのテスト"""

    @pytest.mark.parametrize("path", [
        "/api/analysis/trend/XAUUSD",
        "/api/analysis/news/XAUUSD",
        "/api/analysis/sns/XAUUSD",
        "/api/analysis/economic/XAUUSD",
        "/api/analysis/volatility/XAUUSD",
        "/api/analysis/market/XAUUSD",
    ])
    def test_unknown_symbol_returns_404(self, client, path):
        """未対応シンボルは 404 にすること"""
        assert client.get(path).status_code == 404

    def test_trend_delegates_to_the_ml_predictor(self, client):
        """トレンド予測を ML 層へ委譲すること（スレッドへ退避される）"""
        with patch("src.main.predict_trend", return_value={"trend": "up"}) as predict:
            body = client.get("/api/analysis/trend/USDJPY?days=120").json()

        assert body["trend"] == "up"
        assert predict.call_args[0] == ("USDJPY", 120)

    def test_volatility_delegates_to_the_ml_predictor(self, client):
        """ボラティリティ予測を ML 層へ委譲すること"""
        with patch("src.main.predict_volatility", return_value={"atr": 0.5}):
            assert client.get("/api/analysis/volatility/USDJPY").json()["atr"] == 0.5

    def test_sns_returns_the_sentiment(self, client):
        """SNS センチメントを返すこと"""
        with patch("src.main.analyze_sns",
                   new=AsyncMock(return_value={"sentiment": "bullish"})):
            assert client.get("/api/analysis/sns/USDJPY").json()["sentiment"] == "bullish"

    def test_market_returns_the_report(self, client):
        """マーケット分析レポートを返すこと"""
        with patch("src.main.build_market_analysis", return_value={"regime": "trending"}):
            assert client.get("/api/analysis/market/USDJPY").json()["regime"] == "trending"

    def test_market_failures_become_500(self, client):
        """マーケット分析の失敗は 500 にすること"""
        with patch("src.main.build_market_analysis", side_effect=RuntimeError("boom")):
            assert client.get("/api/analysis/market/USDJPY").status_code == 500

    @pytest.mark.parametrize("days", [10, 900])
    def test_days_is_range_checked(self, client, days):
        """期間の範囲外指定は 422 にすること"""
        assert client.get(f"/api/analysis/trend/USDJPY?days={days}").status_code == 422
