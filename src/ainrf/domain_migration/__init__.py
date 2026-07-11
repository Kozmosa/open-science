"""Read-only source snapshots used by the domain migration CLI."""

from ainrf.domain_migration.sources import SourceManifest, capture_source_manifest

__all__ = ["SourceManifest", "capture_source_manifest"]
