"""Lazy persistent maintenance and cutover exports."""

from typing import Any

from ainrf._lazy_exports import resolve_export

_SERVICE = "ainrf.domain_control.service"
_GUARD = "ainrf.domain_control.legacy_source_guard"
_CUTOVER = "ainrf.domain_control.cutover"
_EXPORTS = {
    name: (_SERVICE, name)
    for name in (
        "CUTOVER_REQUIRED_PARTICIPANT_TYPES",
        "DomainMaintenanceService",
        "DomainWriteParticipant",
        "MaintenancePreflight",
        "MaintenanceLease",
        "MaintenanceModeError",
        "MaintenanceStatus",
        "ParticipantStatus",
    )
}
_EXPORTS.update(
    {
        name: (_GUARD, name)
        for name in (
            "LegacySourceDriftError",
            "LegacySourceFile",
            "LegacySourceGuard",
            "LegacySourceGuardError",
            "LegacySourceInventory",
            "LegacySourceSeal",
            "LegacySourceSealError",
            "LegacySourceSealFile",
        )
    }
)
_EXPORTS.update(
    {
        name: (_CUTOVER, name)
        for name in (
            "ConstraintFinalization",
            "CutoverPreconditionError",
            "CutoverStatus",
            "DomainCutoverController",
            "DomainCutoverError",
            "backup_manifest_sha256",
        )
    }
)
__all__ = list(_EXPORTS)


def __getattr__(name: str) -> Any:
    return resolve_export(name, _EXPORTS, globals())
