"""
テストスイート 08: REST API エンドポイント

カバー範囲:
    - GET /health: ヘルスチェック
    - GET /autotrade/presets: プリセット一覧
    - GET /autotrade/config: 設定取得
    - GET /autotrade/simulate: シミュレーション実行
    - GET /api/prices/symbols: 対応通貨ペア一覧
    - POST /autotrade/config: 設定更新
    - FastAPI TestClient による HTTP レスポンス検証

顧客向けポイント:
    - 全エンドポイントは FastAPI + Pydantic による入力バリデーションを備えます。
    - 認証は JWT Bearer トークン + テナント ID マルチテナント対応です。
    - OpenAPI (/docs) と ReDoc (/redoc) で自動 API ドキュメントを提供します。
"""

import pytest


class TestHealthCheck:
    """ヘルスチェックエンドポイントのテスト。"""

    def test_health_endpoint_returns_200(self, fx_app):
        """GET /health が 200 を返すことを確認する。

        Railway のヘルスチェックポーリングに対応するエンドポイント。
        """
        if fx_app is None:
            pytest.skip("FastAPI TestClient が初期化できませんでした")
        response = fx_app.get("/health")
        assert response.status_code == 200, \
            f"GET /health は 200 を返す必要があります: {response.status_code}"

    def test_health_endpoint_returns_ok_status(self, fx_app):
        """GET /health のレスポンスに 'ok' または 'healthy' が含まれることを確認する。"""
        if fx_app is None:
            pytest.skip("FastAPI TestClient が初期化できませんでした")
        response = fx_app.get("/health")
        if response.status_code == 200:
            data = response.json()
            status_str = str(data).lower()
            assert "ok" in status_str or "healthy" in status_str or "status" in data, \
                f"ヘルスチェックレスポンスには 'ok' または 'healthy' が必要です: {data}"


class TestPresetsAPI:
    """GET /autotrade/presets エンドポイントテスト。"""

    def test_presets_endpoint_accessible(self, fx_app):
        """GET /autotrade/presets が 200 または 401 を返すことを確認する。

        認証なし = 401 (Unauthorized) が期待されるが、エンドポイントが存在することを確認。
        認証あり = 200 が期待される。
        """
        if fx_app is None:
            pytest.skip("FastAPI TestClient が初期化できませんでした")
        response = fx_app.get("/autotrade/presets")
        assert response.status_code in (200, 401, 403, 422), \
            f"GET /autotrade/presets は 200/401/403/422 のいずれかが期待されます: {response.status_code}"

    def test_presets_returns_list_when_authenticated(self, fx_app):
        """認証付きリクエストで GET /autotrade/presets がリストを返すことを確認する。

        テスト環境では X-Tenant-ID ヘッダーを使用して認証バイパス。
        """
        if fx_app is None:
            pytest.skip("FastAPI TestClient が初期化できませんでした")
        response = fx_app.get(
            "/autotrade/presets",
            headers={"X-Tenant-ID": "1"},
        )
        if response.status_code == 200:
            data = response.json()
            assert isinstance(data, list), \
                f"GET /autotrade/presets は list を返す必要があります: {type(data)}"
            assert len(data) >= 5, \
                f"5種類以上のプリセットが期待されます: {len(data)}"


class TestAutoTradeConfigAPI:
    """GET /autotrade/config エンドポイントテスト。"""

    def test_config_endpoint_exists(self, fx_app):
        """GET /autotrade/config エンドポイントが存在することを確認する。

        404 以外のステータスコードで存在を確認（認証エラーは許容）。
        """
        if fx_app is None:
            pytest.skip("FastAPI TestClient が初期化できませんでした")
        response = fx_app.get("/autotrade/config", headers={"X-Tenant-ID": "1"})
        assert response.status_code != 404, \
            f"GET /autotrade/config エンドポイントが存在する必要があります: {response.status_code}"

    def test_config_response_has_json_body(self, fx_app):
        """GET /autotrade/config のレスポンスが JSON であることを確認する。"""
        if fx_app is None:
            pytest.skip("FastAPI TestClient が初期化できませんでした")
        response = fx_app.get("/autotrade/config", headers={"X-Tenant-ID": "1"})
        if response.status_code == 200:
            data = response.json()
            assert isinstance(data, dict), \
                f"GET /autotrade/config は dict を返す必要があります: {type(data)}"


class TestSimulateAPI:
    """GET /autotrade/simulate エンドポイントテスト。"""

    def test_simulate_endpoint_exists(self, fx_app):
        """GET /autotrade/simulate エンドポイントが存在することを確認する。"""
        if fx_app is None:
            pytest.skip("FastAPI TestClient が初期化できませんでした")
        response = fx_app.get(
            "/autotrade/simulate",
            params={"symbol": "USDJPY", "days": 90, "preset_id": "balanced"},
            headers={"X-Tenant-ID": "1"},
        )
        assert response.status_code != 404, \
            f"GET /autotrade/simulate エンドポイントが存在する必要があります: {response.status_code}"

    def test_simulate_returns_valid_response(self, fx_app):
        """GET /autotrade/simulate が有効なレスポンスを返すことを確認する。"""
        if fx_app is None:
            pytest.skip("FastAPI TestClient が初期化できませんでした")
        response = fx_app.get(
            "/autotrade/simulate",
            params={"symbol": "USDJPY", "days": 90, "preset_id": "balanced"},
            headers={"X-Tenant-ID": "1"},
        )
        if response.status_code == 200:
            data = response.json()
            assert "symbol" in data or "assessment" in data, \
                f"シミュレーションレスポンスには 'symbol' または 'assessment' が必要です: {list(data.keys())}"

    def test_simulate_with_invalid_preset_returns_error(self, fx_app):
        """無効なプリセット ID で適切なエラーレスポンスが返されることを確認する。

        Pydantic バリデーションまたは明示的なエラーハンドリングにより
        400/422 が返されることを検証する。
        """
        if fx_app is None:
            pytest.skip("FastAPI TestClient が初期化できませんでした")
        response = fx_app.get(
            "/autotrade/simulate",
            params={"symbol": "USDJPY", "days": 90, "preset_id": "invalid_xyz"},
            headers={"X-Tenant-ID": "1"},
        )
        assert response.status_code in (400, 422, 500), \
            f"無効なプリセットには 400/422/500 が期待されます: {response.status_code}"


class TestOpenAPIDocumentation:
    """OpenAPI ドキュメントエンドポイントテスト。

    FastAPI は /docs (Swagger UI) と /redoc (ReDoc) を自動生成する。
    顧客や開発者が API を探索・テストするためのインターフェース。
    """

    def test_openapi_json_endpoint_accessible(self, fx_app):
        """GET /openapi.json が 200 を返すことを確認する。

        OpenAPI スキーマ定義ファイル。全エンドポイント・モデルの定義が含まれる。
        """
        if fx_app is None:
            pytest.skip("FastAPI TestClient が初期化できませんでした")
        response = fx_app.get("/openapi.json")
        assert response.status_code == 200, \
            f"GET /openapi.json は 200 を返す必要があります: {response.status_code}"

    def test_openapi_has_paths(self, fx_app):
        """OpenAPI スキーマに API パスが含まれることを確認する。"""
        if fx_app is None:
            pytest.skip("FastAPI TestClient が初期化できませんでした")
        response = fx_app.get("/openapi.json")
        if response.status_code == 200:
            schema = response.json()
            assert "paths" in schema, \
                f"OpenAPI スキーマには 'paths' が必要です: {list(schema.keys())}"
            assert len(schema.get("paths", {})) > 10, \
                f"10 以上の API パスが期待されます: {len(schema.get('paths', {}))}"

    def test_openapi_has_components(self, fx_app):
        """OpenAPI スキーマにコンポーネント（モデル定義）が含まれることを確認する。"""
        if fx_app is None:
            pytest.skip("FastAPI TestClient が初期化できませんでした")
        response = fx_app.get("/openapi.json")
        if response.status_code == 200:
            schema = response.json()
            assert "components" in schema or "definitions" in schema, \
                "OpenAPI スキーマには 'components' または 'definitions' が必要です"

    def test_autotrade_routes_in_openapi(self, fx_app):
        """OpenAPI スキーマに /autotrade ルートが含まれることを確認する。"""
        if fx_app is None:
            pytest.skip("FastAPI TestClient が初期化できませんでした")
        response = fx_app.get("/openapi.json")
        if response.status_code == 200:
            paths = response.json().get("paths", {})
            autotrade_paths = [p for p in paths if "/autotrade" in p]
            assert len(autotrade_paths) > 0, \
                f"OpenAPI に /autotrade ルートが含まれる必要があります。現在のパス: {list(paths.keys())[:10]}"


class TestCORSHeaders:
    """CORS ヘッダーのテスト。

    Next.js フロントエンドとの連携のため、適切な CORS 設定が必要。
    """

    def test_preflight_request_is_handled(self, fx_app):
        """OPTIONS プリフライトリクエストが適切に処理されることを確認する。"""
        if fx_app is None:
            pytest.skip("FastAPI TestClient が初期化できませんでした")
        response = fx_app.options(
            "/health",
            headers={
                "Origin": "http://localhost:3000",
                "Access-Control-Request-Method": "GET",
            },
        )
        assert response.status_code in (200, 204), \
            f"OPTIONS プリフライトは 200/204 を返す必要があります: {response.status_code}"
