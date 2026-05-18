# src/ainrf/auth/models.py
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class UserRole(StrEnum):
    ADMIN = "admin"
    MEMBER = "member"


class UserStatus(StrEnum):
    PENDING = "pending"
    ACTIVE = "active"
    DISABLED = "disabled"


class AuthError(RuntimeError):
    """Base error for auth operations."""


@dataclass(slots=True)
class User:
    id: str
    username: str
    password_hash: str
    display_name: str
    role: UserRole
    status: UserStatus
    created_at: str
    activated_at: str | None
    last_login_at: str | None
