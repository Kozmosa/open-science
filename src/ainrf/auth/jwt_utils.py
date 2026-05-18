# src/ainrf/auth/jwt_utils.py
from __future__ import annotations

import hashlib
import secrets
import time
from pathlib import Path

import jwt  # PyJWT

_SECRET_PATH = Path.home() / ".ainrf" / "jwt_secret"
_ALGORITHM = "HS256"
_ACCESS_TTL_SEC = 15 * 60       # 15 minutes


def _ensure_secret() -> str:
    if _SECRET_PATH.exists():
        return _SECRET_PATH.read_text().strip()
    secret = secrets.token_hex(32)  # 64-char hex
    _SECRET_PATH.parent.mkdir(parents=True, exist_ok=True)
    _SECRET_PATH.write_text(secret)
    return secret


def create_access_token(user_id: str, username: str, role: str) -> str:
    now = int(time.time())
    payload = {
        "sub": user_id,
        "username": username,
        "role": role,
        "iat": now,
        "exp": now + _ACCESS_TTL_SEC,
    }
    return jwt.encode(payload, _ensure_secret(), algorithm=_ALGORITHM)


def decode_access_token(token: str) -> dict:
    return jwt.decode(token, _ensure_secret(), algorithms=[_ALGORITHM])


def create_refresh_token() -> tuple[str, str]:
    """Returns (plain_token, sha256_hash)."""
    plain = secrets.token_hex(32)
    return plain, hashlib.sha256(plain.encode()).hexdigest()
