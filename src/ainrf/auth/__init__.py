"""Lazy authentication and authorization exports."""

from typing import Any

from ainrf._lazy_exports import resolve_export

_EXPORTS = {
    "AuthError": ("ainrf.auth.models", "AuthError"),
    "User": ("ainrf.auth.models", "User"),
    "UserRole": ("ainrf.auth.models", "UserRole"),
    "UserStatus": ("ainrf.auth.models", "UserStatus"),
    "AuthService": ("ainrf.auth.service", "AuthService"),
    "check_resource_ownership": ("ainrf.auth.permissions", "check_resource_ownership"),
    "get_current_user": ("ainrf.auth.permissions", "get_current_user"),
    "is_admin": ("ainrf.auth.permissions", "is_admin"),
    "require_admin": ("ainrf.auth.permissions", "require_admin"),
}
__all__ = list(_EXPORTS)


def __getattr__(name: str) -> Any:
    return resolve_export(name, _EXPORTS, globals())
