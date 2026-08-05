"""Lazy persistent maintenance exports."""

from typing import Any

from ainrf._lazy_exports import resolve_export

_SERVICE = "ainrf.domain_control.service"
_EXPORTS = {
    name: (_SERVICE, name)
    for name in (
        "REQUIRED_PARTICIPANT_TYPES",
        "DomainMaintenanceService",
        "DomainWriteParticipant",
        "MaintenancePreflight",
        "MaintenanceLease",
        "MaintenanceModeError",
        "MaintenanceStatus",
        "ParticipantStatus",
    )
}
__all__ = list(_EXPORTS)


def __getattr__(name: str) -> Any:
    return resolve_export(name, _EXPORTS, globals())
