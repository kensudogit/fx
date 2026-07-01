"""
ブローカー設定 API モジュール

このモジュールは、ブローカー（取引業者）との連携設定を管理する
REST API エンドポイントを定義する。現在は OANDA との連携に対応しており、
以下の機能を提供する:
  - OANDA API 設定の取得（トークンマスキング済み）とアカウントサマリー表示
  - OANDA API トークン・アカウント ID・環境（practice/live）の保存・更新
  - API トークンのクリア（セキュリティ目的）

セキュリティ設計:
  - API トークンはデータベースに暗号化して保存し、取得時はマスキングして返す
  - 認証が必要なエンドポイントのみ: テナント ID が取得できない場合は 401 を返す
"""

from pydantic import BaseModel, Field

from fastapi import APIRouter, HTTPException, Request

from src.auth.context import get_tenant_id
from src.broker.oanda import get_account_summary
from src.broker.tenant_oanda import get_tenant_oanda_settings, save_tenant_oanda_settings

# ブローカー設定専用の APIRouter（タグで Swagger UI にグループ表示）
router = APIRouter(tags=["Broker"])


class OandaSettingsBody(BaseModel):
    """
    OANDA 設定更新リクエストボディスキーマ。

    全フィールドは省略可能（Optional）で、指定したフィールドのみ更新される（部分更新）。
    clear_token=True を指定すると既存のAPIトークンを削除できる（セキュリティ用途）。

    Attributes:
        api_token (str | None): OANDA API トークン（省略時は変更なし）
        account_id (str | None): OANDA アカウント ID（省略時は変更なし）
        environment (str | None): 接続環境（"practice" = デモ / "live" = 本番）
        clear_token (bool): True の場合は既存の API トークンを削除する
    """
    api_token: str | None = None
    account_id: str | None = None
    environment: str | None = Field(default=None, pattern="^(practice|live)$")
    clear_token: bool = False


def _tenant(request: Request) -> int:
    """
    リクエストオブジェクトからテナント ID を取得する内部ユーティリティ。

    ブローカー設定は認証必須のため、テナント ID が取得できない場合は
    401 Unauthorized を返す（autotrade.py の同名関数と異なり認証チェックが厳格）。

    Args:
        request (Request): FastAPI リクエストオブジェクト

    Returns:
        int: テナント ID

    Raises:
        HTTPException: テナント ID が取得できない場合は 401 を返す（認証必須）
    """
    # ミドルウェアがセットしたテナント情報を優先して確認
    tenant = getattr(request.state, "tenant", None)
    if tenant:
        return tenant.tenant_id
    # コンテキスト変数からテナント ID を取得（シングルテナント・開発環境用）
    tid = get_tenant_id()
    if tid is None:
        # ブローカー設定は認証が必須のため、未認証の場合は 401 を返す
        raise HTTPException(status_code=401, detail="認証が必要です")
    return tid


@router.get("/api/broker/oanda/settings")
async def get_oanda_settings(request: Request):
    """
    テナントの OANDA 設定とアカウントサマリーを取得する。

    保存されている OANDA 設定（API トークンはマスキング済み）と、
    OANDA API に接続してリアルタイムのアカウントサマリー（残高・証拠金など）を返す。
    OANDA が未設定の場合は account_summary が null または空の状態で返る。

    認証必須: テナント ID が取得できない場合は 401 を返す。

    Args:
        request (Request): テナント情報取得のための FastAPI リクエスト

    Returns:
        dict:
            - settings: 保存済みの OANDA 設定（トークンはマスキング表示）
                - account_id: アカウント ID
                - environment: 接続環境（practice / live）
                - has_token: API トークンが設定されているかのフラグ
            - account_summary: OANDA API から取得したアカウントサマリー
                - balance: 口座残高
                - margin_available: 利用可能証拠金
                - open_trade_count: オープントレード数
    """
    # 認証チェック: テナント ID 取得（未認証の場合は 401 を返す）
    tid = _tenant(request)
    # データベースから保存済みの OANDA 設定を取得（トークンはマスキング済み）
    settings_row = get_tenant_oanda_settings(tid)
    # OANDA API に接続してリアルタイムのアカウントサマリーを取得
    # "live" 環境で取得（practice モードでも内部でテナント設定を参照）
    summary = get_account_summary(tid, "live")
    return {
        "settings": settings_row,
        "account_summary": summary,
    }


@router.put("/api/broker/oanda/settings")
async def update_oanda_settings(body: OandaSettingsBody, request: Request):
    """
    テナントの OANDA 設定を更新・保存する。

    指定されたフィールドのみを更新する部分更新方式。
    API トークンはデータベースに暗号化して保存される。
    clear_token=True を指定すると既存のトークンを安全に削除できる。

    認証必須: テナント ID が取得できない場合は 401 を返す。

    Args:
        body (OandaSettingsBody): 更新する OANDA 設定（api_token / account_id / environment / clear_token）
        request (Request): テナント情報取得のための FastAPI リクエスト

    Returns:
        dict:
            - settings: 保存後の OANDA 設定（トークンはマスキング表示）

    Raises:
        HTTPException: 保存処理でバリデーションエラーが発生した場合は 400 を返す
    """
    # 認証チェック: テナント ID 取得（未認証の場合は 401 を返す）
    tid = _tenant(request)
    try:
        # OANDA 設定を保存（API トークンは暗号化して永続化）
        saved = save_tenant_oanda_settings(
            tid,
            api_token=body.api_token,
            account_id=body.account_id,
            environment=body.environment,
            clear_token=body.clear_token,
        )
    except ValueError as e:
        # バリデーションエラー（例: 不正なアカウント ID 形式）は 400 で返す
        raise HTTPException(status_code=400, detail=str(e))
    return {"settings": saved}
