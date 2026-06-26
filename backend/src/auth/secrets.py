"""機密値の暗号化（OANDA トークン等）"""

from __future__ import annotations

import base64
import hashlib
import logging

from cryptography.fernet import Fernet, InvalidToken

from src.config import settings

logger = logging.getLogger(__name__)


def _fernet() -> Fernet | None:
    secret = (settings.jwt_secret or "").strip()
    if not secret or secret == "change-me-in-production-use-long-random-string":
        return None
    digest = hashlib.sha256(secret.encode()).digest()
    key = base64.urlsafe_b64encode(digest)
    return Fernet(key)


def encrypt_secret(value: str) -> str:
    f = _fernet()
    if not f:
        return value
    return "enc:" + f.encrypt(value.encode()).decode()


def decrypt_secret(value: str | None) -> str | None:
    if not value:
        return None
    if not value.startswith("enc:"):
        return value
    f = _fernet()
    if not f:
        logger.warning("encrypted secret present but JWT_SECRET not configured for decryption")
        return None
    try:
        return f.decrypt(value[4:].encode()).decode()
    except InvalidToken:
        logger.warning("failed to decrypt secret")
        return None
