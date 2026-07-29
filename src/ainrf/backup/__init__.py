"""Lazy backup and restore exports."""

from typing import Any

from ainrf._lazy_exports import resolve_export

_EXPORTS = {
    name: ("ainrf.backup.service", name)
    for name in (
        "BackupManifest",
        "BackupService",
        "StagedRestoreValidator",
        "validate_staged_domain_restore",
    )
}
__all__ = list(_EXPORTS)


def __getattr__(name: str) -> Any:
    return resolve_export(name, _EXPORTS, globals())
