"""Lazy environment Module exports."""

from typing import Any
from ainrf._lazy_exports import resolve_export

_EXPORTS = {
    name: ("ainrf.environments.models", name)
    for name in (
        "AnthropicEnvStatus",
        "DetectionSnapshot",
        "DetectionStatus",
        "EnvironmentAuthKind",
        "EnvironmentRegistryEntry",
        "ProjectEnvironmentReference",
        "ToolStatus",
    )
}
_EXPORTS.update(
    {
        name: ("ainrf.environments.service", name)
        for name in (
            "AliasConflictError",
            "DeleteReferencedEnvironmentError",
            "DeleteSeedEnvironmentError",
            "EnvironmentNotFoundError",
            "InMemoryEnvironmentService",
            "ProjectReferenceConflictError",
            "ProjectReferenceNotFoundError",
        )
    }
)
__all__ = list(_EXPORTS)


def __getattr__(name: str) -> Any:
    return resolve_export(name, _EXPORTS, globals())
