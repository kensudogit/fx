"""JWT・パスワードハッシュ"""

import hashlib
import secrets
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt

from src.config import settings

API_KEY_PREFIX = "fx_"


def hash_password(password: str) -> str:
    pwd_bytes = password.encode("utf-8")[:72]
    return bcrypt.hashpw(pwd_bytes, bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except (ValueError, TypeError):
        return False


def create_access_token(user_id: int, tenant_id: int, email: str, role: str) -> str:
    now = datetime.now(timezone.utc)
    expire = now + timedelta(hours=settings.jwt_expire_hours)
    payload = {
        "sub": str(user_id),
        "tenant_id": tenant_id,
        "email": email,
        "role": role,
        "exp": int(expire.timestamp()),
        "iat": int(now.timestamp()),
    }
    token = jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)
    return token if isinstance(token, str) else token.decode("utf-8")


def decode_access_token(token: str) -> dict | None:
    try:
        return jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    except jwt.PyJWTError:
        return None


def generate_api_key() -> str:
    return f"{API_KEY_PREFIX}{secrets.token_urlsafe(32)}"


def hash_api_key(raw_key: str) -> str:
    return hashlib.sha256(raw_key.encode()).hexdigest()


def api_key_prefix(raw_key: str) -> str:
    return raw_key[:12] + "..." if len(raw_key) > 12 else raw_key
