"""Read-only legacy audit exports."""

from typing import Any

from ainrf._lazy_exports import resolve_export

_EXPORTS = {
    "LegacyDomainRecordAuditService": (
        "ainrf.domain_migration.audit",
        "LegacyDomainRecordAuditService",
    ),
}
__all__ = list(_EXPORTS)


def __getattr__(name: str) -> Any:
    return resolve_export(name, _EXPORTS, globals())
