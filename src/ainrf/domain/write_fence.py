"""Shared transactional fence for the first authoritative v2 domain write."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from ainrf.domain_control import DomainCutoverController, DomainCutoverError


class DomainWriteFence:
    """Bind application-service writes to the committed cutover fuse.

    Services call :meth:`record_first_v2_write` while they still own their
    SQLite transaction and before they add their own audit event.  The
    controller verifies the immutable cutover evidence and legacy-source
    stability in that transaction; a failed check rolls the business mutation
    back with it.  Legacy and prepared databases deliberately do not record a
    v2 write here: startup/mode gates decide whether their callers may run.
    """

    def __init__(self, state_root: Path, *, artifact_sha: str | None = None) -> None:
        self._controller = DomainCutoverController(state_root)
        self._artifact_sha = artifact_sha

    def record_first_v2_write(self, conn: sqlite3.Connection, *, actor_id: str) -> None:
        state = conn.execute(
            "SELECT state FROM domain_cutover_state WHERE singleton = 1"
        ).fetchone()
        if state is None or str(state["state"]) != "v2":
            return
        if not self._artifact_sha:
            raise DomainCutoverError(
                "an immutable domain artifact SHA is required for v2 domain writes"
            )
        self._controller.record_first_v2_write_in_transaction(
            conn,
            actor_id=actor_id,
            artifact_sha=self._artifact_sha,
        )

    def v2_ready(self) -> bool:
        """Return readiness only for a committed, stable, compatible fuse."""

        if not self._artifact_sha:
            return False
        try:
            self._controller.assert_v2_writable(artifact_sha=self._artifact_sha)
        except DomainCutoverError:
            return False
        return True
