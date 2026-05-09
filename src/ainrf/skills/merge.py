from __future__ import annotations

import os
import re
from typing import Any

_ENV_PATTERN = re.compile(r"\$\{([^}]+)\}")


def deep_merge_settings(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = dict(base)
    for key, value in overlay.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = deep_merge_settings(result[key], value)
        else:
            result[key] = value
    return result


def _resolve_value(value: Any) -> Any:
    if isinstance(value, str):

        def replacer(match: re.Match[str]) -> str:
            var_name = match.group(1)
            return os.environ.get(var_name, match.group(0))

        return _ENV_PATTERN.sub(replacer, value)
    if isinstance(value, dict):
        return resolve_env_placeholders(value)
    if isinstance(value, list):
        return [_resolve_value(item) for item in value]
    return value


def resolve_env_placeholders(data: dict[str, Any]) -> dict[str, Any]:
    return {key: _resolve_value(value) for key, value in data.items()}
