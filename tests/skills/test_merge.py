from __future__ import annotations

import os
from typing import Any

from ainrf.skills.merge import deep_merge_settings, resolve_env_placeholders


def test_deep_merge_dicts() -> None:
    base: dict[str, Any] = {"a": {"b": 1, "c": 2}, "d": 3}
    overlay: dict[str, Any] = {"a": {"c": 4, "e": 5}}
    result = deep_merge_settings(base, overlay)
    assert result == {"a": {"b": 1, "c": 4, "e": 5}, "d": 3}


def test_deep_merge_overlay_wins() -> None:
    base: dict[str, Any] = {"a": {"b": 1}, "c": [1, 2]}
    overlay: dict[str, Any] = {"a": {"b": 2}, "c": [3, 4]}
    result = deep_merge_settings(base, overlay)
    assert result == {"a": {"b": 2}, "c": [3, 4]}


def test_resolve_env_placeholders() -> None:
    os.environ["TEST_VAR"] = "hello"
    data: dict[str, Any] = {"key": "value is ${TEST_VAR}"}
    result = resolve_env_placeholders(data)
    assert result == {"key": "value is hello"}
    del os.environ["TEST_VAR"]


def test_resolve_env_missing_placeholder() -> None:
    data: dict[str, Any] = {"key": "value is ${MISSING_VAR}"}
    result = resolve_env_placeholders(data)
    assert result == {"key": "value is ${MISSING_VAR}"}
