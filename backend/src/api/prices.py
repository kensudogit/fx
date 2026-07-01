"""
リアルタイム価格 WebSocket モジュール

このモジュールは、FX 通貨ペアのリアルタイム価格を提供する
WebSocket エンドポイントと REST エンドポイントを定義する。

提供するエンドポイント:
  - WebSocket /api/ws/prices: リアルタイム価格ストリーミング
  - GET /api/prices/live: 最新価格の REST 取得

WebSocket 設計方針:
  - クライアントは接続後にサーバープッシュ方式で価格データを受信する
  - クライアントからのメッセージ（symbols・interval の更新）を非ブロッキングで受信する
    ため、asyncio.wait_for の短いタイムアウト（50ms）でポーリングする
  - 配信間隔はデフォルト 3 秒だが、クライアントが 1〜30 秒の範囲で変更可能
  - JWT トークンによるオプション認証: トークンなしでも接続可能（公開価格データ）
  - 接続断（WebSocketDisconnect）は正常終了として処理し、その他のエラーは
    コード 1011（Internal Error）でクロージングする

認証設計:
  - WebSocket は HTTP ヘッダーでの認証が難しいため、クエリパラメータでトークンを受け取る
  - トークンがない場合でも接続は許可し、テナント ID なし（None）として処理する
  - テナント ID がある場合は OANDA のリアルタイムレートを使用できる
"""

from __future__ import annotations

import asyncio
import json
import logging

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect

from src.auth.security import decode_access_token
from src.broker.oanda import fetch_live_prices
from src.data.sample_data import SYMBOL_BASE_PRICES

# モジュールレベルのロガー（WebSocket の接続・切断・エラーのデバッグ用）
logger = logging.getLogger(__name__)
# 価格配信専用の APIRouter（タグで Swagger UI にグループ表示）
router = APIRouter(tags=["Prices"])


def _tenant_from_token(token: str | None) -> int | None:
    """
    JWT アクセストークンからテナント ID を抽出する内部ユーティリティ。

    WebSocket 接続ではリクエストヘッダーによる認証が難しいため、
    クエリパラメータとして渡されたトークンを直接デコードする。
    トークンが不正・期限切れの場合は None を返し、エラーにはしない
    （価格データは公開情報のため、認証なしでも基本的なデータを返す）。

    Args:
        token (str | None): JWT アクセストークン文字列（クエリパラメータ由来）

    Returns:
        int | None: テナント ID（トークンが無効または未指定の場合は None）
    """
    # トークンが指定されていない場合はテナント ID なし（匿名接続）
    if not token:
        return None
    # JWT トークンをデコードしてペイロードを取得
    payload = decode_access_token(token)
    if payload and payload.get("tenant_id"):
        # ペイロードに tenant_id が含まれている場合は整数に変換して返す
        return int(payload["tenant_id"])
    # トークンが不正または tenant_id が含まれていない場合は None
    return None


@router.websocket("/api/ws/prices")
async def websocket_prices(
    websocket: WebSocket,
    token: str | None = Query(default=None),
):
    """
    リアルタイム FX 価格をサーバープッシュ方式で配信する WebSocket エンドポイント。

    接続後、サーバーは設定された間隔（デフォルト: 3 秒）で全通貨ペアの
    最新価格を自動的にクライアントへ送信し続ける。

    クライアントからの動的設定変更（JSON メッセージで送信）:
        - symbols: 購読する通貨ペアリスト（例: {"symbols": ["USDJPY", "EURUSD"]}）
        - interval: 配信間隔（秒、1〜30 の範囲、例: {"interval": 5}）

    配信データフォーマット:
        {
            "type": "prices",
            "data": {<symbol>: {<bid, ask, mid, ...>}, ...},
            "symbols": [<symbol>, ...]
        }

    認証:
        token クエリパラメータに JWT を指定するとテナント認証済みとして処理され、
        OANDA の実レートにアクセスできる。省略した場合はサンプルデータを使用。

    エラーハンドリング:
        - WebSocketDisconnect: 正常切断としてログに記録して終了
        - その他の例外: WebSocket コード 1011（Internal Error）でクロージング

    Args:
        websocket (WebSocket): FastAPI WebSocket コネクションオブジェクト
        token (str | None): JWT アクセストークン（クエリパラメータ、省略可能）
    """
    # WebSocket 接続を受け入れる（HTTP 101 Switching Protocols）
    await websocket.accept()
    # JWT トークンからテナント ID を抽出（認証失敗・未指定時は None）
    tenant_id = _tenant_from_token(token)
    # 初期購読シンボルリスト（全サポート通貨ペア）
    symbols = list(SYMBOL_BASE_PRICES.keys())
    # デフォルトの価格配信間隔（秒）
    interval_sec = 3

    try:
        while True:
            try:
                # クライアントからのメッセージを非ブロッキングで受信する
                # タイムアウト 50ms: クライアントメッセージがない場合は即座に次のステップへ進む
                # これにより、配信ループをメッセージ受信でブロックしない設計を実現
                raw = await asyncio.wait_for(websocket.receive_text(), timeout=0.05)
                msg = json.loads(raw)
                if msg.get("symbols"):
                    # クライアントが購読シンボルを更新した場合、大文字に正規化してサポート済みのみ残す
                    symbols = [s.upper() for s in msg["symbols"] if s.upper() in SYMBOL_BASE_PRICES]
                if msg.get("interval"):
                    # クライアントが配信間隔を更新した場合、1〜30 秒の範囲にクランプ
                    interval_sec = max(1, min(30, int(msg["interval"])))
            except asyncio.TimeoutError:
                # タイムアウトは正常（クライアントからのメッセージなし）のため無視
                pass
            except json.JSONDecodeError:
                # 不正な JSON は無視してループを継続する
                pass

            # 購読中のシンボルの最新価格をブローカーから取得
            # テナント ID がある場合は OANDA のリアルタイムレート、なければサンプルデータを使用
            prices = fetch_live_prices(symbols, tenant_id, trading_mode="live")
            # クライアントへ価格データを JSON で送信
            await websocket.send_json(
                {
                    "type": "prices",
                    "data": prices,
                    "symbols": symbols,
                }
            )
            # 次の配信まで待機（イベントループを解放して他のコルーチンを実行可能にする）
            await asyncio.sleep(interval_sec)
    except WebSocketDisconnect:
        # クライアントが正常に切断した場合はデバッグログに記録して終了
        logger.debug("price websocket disconnected tenant=%s", tenant_id)
    except Exception as e:
        # 予期しないエラーが発生した場合は警告ログに記録し、
        # WebSocket コード 1011（Internal Error）でクロージング
        logger.warning("price websocket error: %s", e)
        await websocket.close(code=1011)


@router.get("/api/prices/live")
async def live_prices(symbols: str = "USDJPY,EURUSD"):
    """
    複数の通貨ペアの最新価格を REST API で取得する。

    WebSocket が使えない環境（HTTP ポーリング方式）向けの代替エンドポイント。
    カンマ区切りで複数のシンボルを指定できる。

    認証不要（公開エンドポイント）: テナント ID なし（None）でサンプルデータまたは
    グローバル設定の OANDA アカウントを使用する。

    Args:
        symbols (str): カンマ区切りの通貨ペア文字列（デフォルト: "USDJPY,EURUSD"）

    Returns:
        dict:
            - prices (dict): シンボルをキーとした価格情報の辞書
                - <symbol>: {"bid": float, "ask": float, "mid": float, ...}

    Example:
        GET /api/prices/live?symbols=USDJPY,EURUSD,GBPJPY
    """
    # カンマ区切り文字列を分割してシンボルリストに変換（空文字・空白を除外・大文字化）
    sym_list = [s.strip().upper() for s in symbols.split(",") if s.strip()]
    # テナント ID なし（None）で最新価格を取得（公開エンドポイントのため認証不要）
    return {"prices": fetch_live_prices(sym_list, None, trading_mode="live")}
