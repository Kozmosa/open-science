"""Lazy domain migration exports."""

from typing import Any

from ainrf._lazy_exports import resolve_export

_EXPORTS = {
    "LegacyDomainRecordAuditService": (
        "ainrf.domain_migration.audit",
        "LegacyDomainRecordAuditService",
    ),
    "DomainImporter": ("ainrf.domain_migration.importer", "DomainImporter"),
    "MigrationInspection": ("ainrf.domain_migration.importer", "MigrationInspection"),
    "MigrationInterruptedError": ("ainrf.domain_migration.importer", "MigrationInterruptedError"),
    "MigrationRecordResult": ("ainrf.domain_migration.importer", "MigrationRecordResult"),
    "MigrationReport": ("ainrf.domain_migration.importer", "MigrationReport"),
    "ReconciliationReport": ("ainrf.domain_migration.importer", "ReconciliationReport"),
    "DomainReconciliationService": (
        "ainrf.domain_migration.reconciliation",
        "DomainReconciliationService",
    ),
    "MigrationFinalization": ("ainrf.domain_migration.reconciliation", "MigrationFinalization"),
    "MigrationIssue": ("ainrf.domain_migration.reconciliation", "MigrationIssue"),
    "SourceManifest": ("ainrf.domain_migration.sources", "SourceManifest"),
    "SourceSnapshotSet": ("ainrf.domain_migration.sources", "SourceSnapshotSet"),
    "SourceStaleError": ("ainrf.domain_migration.sources", "SourceStaleError"),
    "capture_source_manifest": ("ainrf.domain_migration.sources", "capture_source_manifest"),
}
__all__ = list(_EXPORTS)


def __getattr__(name: str) -> Any:
    return resolve_export(name, _EXPORTS, globals())
