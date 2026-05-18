"""Permission checking helpers for route handlers."""

from __future__ import annotations

from fastapi import HTTPException, Request


def get_current_user(request: Request) -> dict:
    user = getattr(request.state, "current_user", None)
    if user is None:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return user


def require_admin(user: dict) -> None:
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")


def is_admin(user: dict) -> bool:
    return user.get("role") == "admin"


def check_resource_owner(user: dict, owner_user_id: str | None) -> bool:
    """Check if user owns the resource. Admin sees everything. NULL owner is invisible to non-admin."""
    if is_admin(user):
        return True
    if owner_user_id is None:
        return False
    return owner_user_id == user["id"]
