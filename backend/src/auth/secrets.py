"""
機密値の暗号化・復号モジュール（OANDA トークン等の保護用）。

このモジュールは、データベースに保存する必要のある機密情報（OANDA API トークン等）を
対称暗号（Fernet = AES-128-CBC + HMAC-SHA256）で暗号化・復号する。

設計のポイント:
  - 暗号化キーは jwt_secret から SHA-256 で派生させる（専用のシークレット不要）
  - 暗号化済みの値は "enc:" プレフィックスで識別できる（平文との区別）
  - jwt_secret が未設定・デフォルト値の場合は暗号化をスキップ（開発環境での利便性）
  - Fernet は認証付き暗号（改ざん検知あり）のため、InvalidToken で改ざんを検出できる

注意: jwt_secret を変更すると既存の暗号化済みデータが復号できなくなる。
"""

from __future__ import annotations

import base64
import hashlib
import logging

from cryptography.fernet import Fernet, InvalidToken

from src.config import settings

logger = logging.getLogger(__name__)


def _fernet() -> Fernet | None:
    """
    JWT シークレットから Fernet 暗号化インスタンスを生成する内部ヘルパー関数。

    Fernet は 32 バイトの URL-safe Base64 エンコードキーを必要とするが、
    jwt_secret は任意の長さの文字列のため、SHA-256 ハッシュで 32 バイトに揃える。

    Fernet キー生成のアルゴリズム:
      1. jwt_secret を UTF-8 エンコード
      2. SHA-256 ダイジェスト（32 バイト）を計算
      3. URL-safe Base64 エンコードして Fernet キー形式（44 文字）に変換

    jwt_secret が未設定またはデフォルト値の場合は None を返し、
    呼び出し元は暗号化をスキップする。

    Returns:
        Fernet: 暗号化・復号に使用するインスタンス。
                jwt_secret が無効な場合は None。
    """
    secret = (settings.jwt_secret or "").strip()
    # デフォルト値（プレースホルダー）または空文字列の場合は暗号化不可とする
    # 本番環境ではこのデフォルト値を必ず変更すること
    if not secret or secret == "change-me-in-production-use-long-random-string":
        return None
    # SHA-256 で 32 バイトのダイジェストを生成（Fernet は 32 バイトキーが必要）
    digest = hashlib.sha256(secret.encode()).digest()
    # Fernet が要求する URL-safe Base64 エンコード形式（44 文字）に変換
    key = base64.urlsafe_b64encode(digest)
    return Fernet(key)


def encrypt_secret(value: str) -> str:
    """
    機密文字列を Fernet で暗号化する。

    暗号化が成功した場合、返り値は "enc:" プレフィックスが付いた文字列になる。
    このプレフィックスにより、decrypt_secret が暗号化済み値かどうかを判別できる。

    jwt_secret が未設定の場合は暗号化せず平文のまま返す（開発環境向け）。
    本番環境では必ず jwt_secret を設定して暗号化を有効にすること。

    Args:
        value: 暗号化する機密文字列（例: OANDA API トークン）。

    Returns:
        str: "enc:" + Fernet 暗号化文字列（URL-safe Base64 形式）、
             または jwt_secret 未設定時は平文のまま返す。
    """
    f = _fernet()
    if not f:
        # jwt_secret 未設定時は暗号化をスキップ（平文で返す）
        return value
    # Fernet の暗号化: AES-128-CBC + HMAC-SHA256 で認証付き暗号化
    # タイムスタンプ付きのトークンが生成される（有効期限チェックも可能）
    return "enc:" + f.encrypt(value.encode()).decode()


def decrypt_secret(value: str | None) -> str | None:
    """
    "enc:" プレフィックス付きの暗号化文字列を復号する。

    "enc:" プレフィックスがない場合は平文とみなしてそのまま返す
    （古いデータや開発環境での平文保存との互換性のため）。

    Args:
        value: 復号する文字列。None の場合は None を返す。
               "enc:" プレフィックスがない場合は平文とみなす。

    Returns:
        str: 復号された平文文字列。
             value が None の場合は None。
             復号失敗（InvalidToken）の場合は None（エラーログ付き）。
    """
    if not value:
        return None
    # "enc:" プレフィックスがない場合は平文として扱う（後方互換性）
    if not value.startswith("enc:"):
        return value
    f = _fernet()
    if not f:
        # 暗号化済みデータが存在するが、復号キー（jwt_secret）が設定されていない
        # この状態ではデータにアクセスできない（設定漏れの可能性）
        logger.warning("encrypted secret present but JWT_SECRET not configured for decryption")
        return None
    try:
        # "enc:" プレフィックス（4文字）を除去してから復号
        # Fernet は HMAC 検証を行い、改ざんや不正なトークンは InvalidToken で弾く
        return f.decrypt(value[4:].encode()).decode()
    except InvalidToken:
        # 改ざん検知またはキーの不一致（jwt_secret が変更された可能性）
        logger.warning("failed to decrypt secret")
        return None
