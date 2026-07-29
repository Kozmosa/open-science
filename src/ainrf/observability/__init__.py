"""Lazy LLM observability exports."""

from typing import Any
from ainrf._lazy_exports import resolve_export

_EXPORTS = {
    name: ("ainrf.observability.protocol", name)
    for name in ("NullReporter", "ObservabilityConfig", "ObservabilityReporter", "SafeReporter")
}
_EXPORTS.update(
    {name: ("ainrf.observability.factory", name) for name in ("get_reporter", "reset_reporter")}
)
__all__ = list(_EXPORTS)


def __getattr__(name: str) -> Any:
    return resolve_export(name, _EXPORTS, globals())
