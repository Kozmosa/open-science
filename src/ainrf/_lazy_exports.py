"""Small helper for compatibility package exports without eager import cycles."""

from __future__ import annotations

import importlib
from collections.abc import Mapping
from types import ModuleType
from typing import Any


def resolve_export(
    name: str,
    exports: Mapping[str, tuple[str, str]],
    namespace: dict[str, Any],
) -> Any:
    """Resolve and cache one explicitly declared package export."""

    target = exports.get(name)
    if target is None:
        raise AttributeError(name)
    module_name, attribute_name = target
    module: ModuleType = importlib.import_module(module_name)
    value = getattr(module, attribute_name)
    namespace[name] = value
    return value
