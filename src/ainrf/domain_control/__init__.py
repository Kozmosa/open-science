"""Persistent maintenance controls for domain migration safety."""

# Import the low-level barrier first.  Domain migration reaches the domain
# service package while the cutover controller is importing, and that package
# in turn imports ``MaintenanceModeError`` from this public namespace.
# Keeping the barrier exports available first avoids an import-order-dependent
# partial-module cycle for the CLI and administrative cutover paths.
from ainrf.domain_control.service import (
    DomainMaintenanceService,
    DomainModelMode,
    DomainWriteParticipant,
    MaintenancePreflight,
    MaintenanceLease,
    MaintenanceModeError,
    MaintenanceStatus,
    ParticipantStatus,
)
from ainrf.domain_control.legacy_source_guard import (
    LegacySourceDriftError,
    LegacySourceFile,
    LegacySourceGuard,
    LegacySourceGuardError,
    LegacySourceInventory,
    LegacySourceSeal,
    LegacySourceSealError,
    LegacySourceSealFile,
)
from ainrf.domain_control.cutover import (
    ConstraintFinalization,
    CutoverPreconditionError,
    CutoverStatus,
    DomainCutoverController,
    DomainCutoverError,
    backup_manifest_sha256,
)

__all__ = [
    "ConstraintFinalization",
    "CutoverPreconditionError",
    "CutoverStatus",
    "DomainCutoverController",
    "DomainCutoverError",
    "DomainMaintenanceService",
    "DomainModelMode",
    "DomainWriteParticipant",
    "LegacySourceDriftError",
    "LegacySourceFile",
    "LegacySourceGuard",
    "LegacySourceGuardError",
    "LegacySourceInventory",
    "LegacySourceSeal",
    "LegacySourceSealError",
    "LegacySourceSealFile",
    "MaintenancePreflight",
    "MaintenanceLease",
    "MaintenanceModeError",
    "MaintenanceStatus",
    "ParticipantStatus",
    "backup_manifest_sha256",
]
