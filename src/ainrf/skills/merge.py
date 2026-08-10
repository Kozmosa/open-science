from __future__ import annotations

from typing import Any


def deep_merge_settings(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = dict(base)
    for key, value in overlay.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = deep_merge_settings(result[key], value)
        else:
            result[key] = value
    return result
