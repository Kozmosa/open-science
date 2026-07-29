"""HTTP Adapter compatibility exports."""

from typing import Any

from ainrf._lazy_exports import resolve_export

_EXPORTS = {
    "ApiConfig": ("ainrf.runtime.product_config", "ApiConfig"),
    "create_app": ("ainrf.api.app", "create_app"),
}
__all__ = list(_EXPORTS)


def __getattr__(name: str) -> Any:
    return resolve_export(name, _EXPORTS, globals())
