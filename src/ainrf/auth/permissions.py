"""Permission checking helpers for route handlers."""

from __future__ import annotations

from fastapi import HTTPException, Request


def get_current_user(request: Request) -> dict:
    """获取当前认证用户。未认证时抛出 401。"""
    user = getattr(request.state, "current_user", None)
    if user is None:
        raise HTTPException(status_code=401, detail="未认证")
    return user


def check_user_authenticated(request: Request) -> dict:
    """第一层：用户认证检查

    确保请求已认证。如果未认证，返回 401。
    """
    user = getattr(request.state, "current_user", None)
    if user is None:
        raise HTTPException(status_code=401, detail="未认证")
    return user


def check_resource_ownership(
    user: dict,
    resource_owner_id: str | None,
    allow_admin: bool = True,
) -> None:
    """第三层：资源所有权检查

    确保用户有权访问指定资源。管理员可以访问所有资源。
    NULL owner 对非管理员不可见。
    """
    if allow_admin and user.get("role") == "admin":
        return
    if resource_owner_id is None:
        raise HTTPException(status_code=403, detail="无权访问此资源")
    if user.get("id") != resource_owner_id:
        raise HTTPException(status_code=403, detail="无权访问此资源")


def require_admin(user: dict) -> None:
    """要求用户为管理员，否则抛出 403。"""
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")


def is_admin(user: dict) -> bool:
    """检查用户是否为管理员"""
    return user.get("role") == "admin"
