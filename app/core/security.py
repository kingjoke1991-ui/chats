from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from typing import Any

import bcrypt
from jose import JWTError, jwt

from app.core.config import settings
from app.core.exceptions import AppException


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))


def hash_refresh_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def create_access_token(user_id: str, session_id: str) -> tuple[str, datetime]:
    expires_at = datetime.now(UTC) + timedelta(minutes=settings.jwt_access_expire_minutes)
    payload: dict[str, Any] = {
        "sub": user_id,
        "sid": session_id,
        "type": "access",
        "exp": expires_at,
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm), expires_at


def create_refresh_token(user_id: str, session_id: str) -> tuple[str, datetime]:
    expires_at = datetime.now(UTC) + timedelta(days=settings.jwt_refresh_expire_days)
    payload: dict[str, Any] = {
        "sub": user_id,
        "sid": session_id,
        "type": "refresh",
        "exp": expires_at,
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm), expires_at


def decode_token(token: str, expected_type: str) -> dict[str, Any]:
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    except JWTError as exc:
        raise AppException(401, "AUTH_REQUIRED", "invalid or expired token") from exc
    if payload.get("type") != expected_type:
        raise AppException(401, "AUTH_REQUIRED", "invalid token type")
    return payload
