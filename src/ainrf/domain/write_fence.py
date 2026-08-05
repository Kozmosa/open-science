"""Shared release-artifact fence for authoritative domain writes."""

from __future__ import annotations

import sqlite3
from pathlib import Path


class DomainWriteFenceError(RuntimeError):
    """A write was attempted without the current immutable release artifact."""


class DomainWriteFence:
    """Keep current writes bound to the running release artifact.

    The historical domain cutover fuse and legacy-source seal are gone after
    the committed-v2 production migration.  Maintenance mode remains the
    operational write barrier; this small Module only prevents an unbound
    development or stale process from claiming current-domain writes.
    """

    def __init__(self, state_root: Path, *, artifact_sha: str | None = None) -> None:
        _ = state_root
        self._artifact_sha = artifact_sha

    def record_first_v2_write(self, conn: sqlite3.Connection, *, actor_id: str) -> None:
        """Validate the release binding before the caller's transaction commits."""
        _ = conn, actor_id
        if not self._artifact_sha:
            raise DomainWriteFenceError(
                "an immutable domain artifact SHA is required for current domain writes"
            )

    def v2_ready(self) -> bool:
        """Return whether this Module carries a current release identity."""
        return bool(self._artifact_sha)
