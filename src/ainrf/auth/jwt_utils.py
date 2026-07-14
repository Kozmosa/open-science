# src/ainrf/auth/jwt_utils.py
from __future__ import annotations

import hashlib
import os
import secrets
import time
from pathlib import Path

import jwt  # PyJWT

_SECRET_PATH = Path.home() / ".ainrf" / "jwt_secret"
_ALGORITHM = "HS256"
_ACCESS_TTL_SEC = 15 * 60  # 15 minutes


def _ensure_secret() -> str:
    env_secret = os.environ.get(
        "OPENSCIENCE_JWT_SECRET",
        os.environ.get("AINRF_JWT_SECRET"),
    )
    if env_secret:
        return env_secret
    if _SECRET_PATH.exists():
        return _SECRET_PATH.read_text().strip()
    secret = secrets.token_hex(32)  # 64-char hex
    _SECRET_PATH.parent.mkdir(parents=True, exist_ok=True)
    _SECRET_PATH.write_text(secret)
    # Set restrictive permissions to prevent other users from reading
    os.chmod(_SECRET_PATH, 0o600)
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
