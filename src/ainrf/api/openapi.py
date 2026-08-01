"""Stable OpenAPI transport contract helpers."""

from __future__ import annotations

import re

from fastapi.routing import APIRoute

_NON_IDENTIFIER = re.compile(r"[^a-zA-Z0-9]+")


def stable_operation_id(route: APIRoute) -> str:
    """Return a path-and-method based operation ID independent of function names."""

    methods = sorted(method.lower() for method in route.methods or () if method != "HEAD")
    if len(methods) != 1:
        raise ValueError(
            f"transport routes must declare exactly one non-HEAD method: {route.path_format}"
        )
    normalized_path = _NON_IDENTIFIER.sub("_", route.path_format).strip("_").lower()
    return f"{methods[0]}_{normalized_path}"
