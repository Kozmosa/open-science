"""Transactional, database-backed controller for the domain v2 cutover fuse."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Iterator
from contextlib import closing, contextmanager
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING
from uuid import uuid4

from ainrf.backup import BackupManifest, BackupService
from ainrf.db import connect, run_pending
from ainrf.db.migrations.agentic_researcher import (
    domain_task_reference_guard_digest,
    install_domain_task_reference_guards,
)
from ainrf.domain_control.legacy_source_guard import (
    LegacySourceDriftError,
    LegacySourceGuard,
    LegacySourceGuardError,
    LegacySourceInventory,
)
from ainrf.domain_control.service import (
    CUTOVER_REQUIRED_PARTICIPANT_TYPES,
    DomainMaintenanceService,
    MaintenanceLease,
    MaintenanceModeError,
)

if TYPE_CHECKING:
    from ainrf.domain_migration import ReconciliationReport


class DomainCutoverError(RuntimeError):
    """Base error for a rejected or unsafe domain cutover operation."""


class CutoverPreconditionError(DomainCutoverError):
    """Raised when an immutable prepare/commit safety gate is not satisfied."""


@dataclass(frozen=True, slots=True)
class CutoverStatus:
    """Persisted cutover fuse plus the current legacy-source monitor result."""

    state: str
    contract_version: int
    schema_version: int
    cutover_epoch: int
    cutover_run_id: str | None
    prepared_at: str | None
    prepared_by_user_id: str | None
    committed_at: str | None
    committed_by_user_id: str | None
    first_v2_write_at: str | None
    first_v2_write_actor_id: str | None
    artifact_sha: str | None
    artifact_contract_min: int | None
    artifact_contract_max: int | None
    artifact_schema_min: int | None
    artifact_schema_max: int | None
    backup_manifest_sha256: str | None
    backup_tree_sha256: str | None
    maintenance_epoch: int | None
    blocking_issue_count: int
    constraints_ready: bool
    cutover_ready: bool
    source_inventory_sha256: str | None
    preparation_digest: str | None
    legacy_sources_stable: bool | None
    legacy_source_drift: str | None

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class ConstraintFinalization:
    """Auditable result of installing the final Task-reference constraint guard."""

    run_id: str
    maintenance_epoch: int
    schema_version: int
    task_reference_count: int
    guard_digest: str
    finalized_at: str
    cutover_allowed: bool

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class _BackupEvidence:
    manifest_sha256: str
    tree_sha256: str
    created_at: str
    version: int
    includes_workspaces: bool
    includes_tenants: bool


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=True, separators=(",", ":"), sort_keys=True)


def _sha256(value: object) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _is_sha256(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value.lower())
    )


def backup_manifest_sha256(manifest: BackupManifest) -> str:
    """Return a canonical digest of a verified backup manifest."""

    return _sha256(asdict(manifest))


class DomainCutoverController:
    """Prepare, commit, abort, and fence the one-way v2 cutover transition.

    The controller performs no deployment or restore.  It binds existing
    backup/reconciliation evidence into the authoritative SQLite fuse and,
    while maintenance holds all writers drained, seals the immutable legacy
    source inventory before the fuse can transition to v2.
    """

    def __init__(
        self,
        state_root: Path,
        *,
        workspace_root: Path | None = None,
        tenant_root: Path | None = None,
    ) -> None:
        self._state_root = state_root
        self._db_path = state_root / "runtime" / "agentic_researcher.sqlite3"
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        with closing(connect(self._db_path)) as conn:
            run_pending(conn, "agentic_researcher")
        self._maintenance = DomainMaintenanceService(
            state_root,
            workspace_root=workspace_root,
            tenant_root=tenant_root,
        )
        self._legacy_sources = LegacySourceGuard(state_root)

    def status(self) -> CutoverStatus:
        """Return the fuse and a non-mutating legacy-source monitor result."""

        with closing(connect(self._db_path)) as conn:
            row = self._state_row(conn)
        inventory = self._inventory_from_row(row)
        stable: bool | None = None
        drift: str | None = None
        if inventory is not None:
            try:
                if str(row["state"]) == "v2":
                    self._legacy_sources.verify_sealed(inventory)
                else:
                    self._legacy_sources.verify(inventory)
            except LegacySourceGuardError as exc:
                stable = False
                drift = str(exc)
            else:
                stable = True
        return self._status_from_row(row, stable, drift)

    def finalize_constraints(
        self,
        *,
        actor_id: str,
        run_id: str,
        stability_window_seconds: float = 5.0,
        maintenance_participant_id: str | None = None,
    ) -> ConstraintFinalization:
        """Install and attest the final Task-reference guard under stopped writes.

        ``tasks`` predates the authoritative domain graph and cannot receive
        the required SQLite foreign keys through a safe ``ALTER TABLE``.  The
        final cutover therefore installs an equivalent insert/update guard only
        after every other migration reconciliation invariant is clean.  The
        operation is deliberately separate from migration finalization: that
        finalization itself requires ``constraints_ready``, so collapsing the
        two would make a real production cutover unreachable.
        """

        self._require_actor(actor_id)
        self._require_text(run_id, "run_id")
        # Keep the legacy no-maintenance failure deterministic before a
        # reconciliation run can make any durable change.
        self._require_preflight(stability_window_seconds)
        before = self._reconcile_for_cutover(
            run_id,
            maintenance_participant_id=maintenance_participant_id,
        )
        blockers = tuple(
            blocker for blocker in before.blocking_issues if blocker != "constraints_not_ready"
        )
        if blockers:
            raise CutoverPreconditionError(
                "domain constraints cannot be finalized while reconciliation is blocked: "
                + ", ".join(blockers)
            )
        preflight_epoch = self._require_preflight(stability_window_seconds)
        with self._maintenance_control_operation(
            source="domain-cutover.finalize-constraints",
            participant_id=maintenance_participant_id,
            expected_epoch=preflight_epoch,
        ):
            finalized = self._finalize_constraints_transaction(
                actor_id=actor_id,
                run_id=run_id,
                preflight_epoch=preflight_epoch,
            )
        after = self._reconcile_for_cutover(
            run_id,
            maintenance_participant_id=maintenance_participant_id,
            expected_epoch=preflight_epoch,
        )
        if after.blocking_issues or not after.cutover_allowed:
            detail = ", ".join(after.blocking_issues) or "migration run is not cutover-allowed"
            raise CutoverPreconditionError(
                "domain constraints were installed but reconciliation is not cutover-ready: "
                + detail
            )
        return ConstraintFinalization(
            run_id=finalized.run_id,
            maintenance_epoch=finalized.maintenance_epoch,
            schema_version=finalized.schema_version,
            task_reference_count=finalized.task_reference_count,
            guard_digest=finalized.guard_digest,
            finalized_at=finalized.finalized_at,
            cutover_allowed=True,
        )

    def prepare(
        self,
        *,
        actor_id: str,
        run_id: str,
        backup_archive: Path,
        artifact_sha: str,
        artifact_contract_min: int,
        artifact_contract_max: int,
        artifact_schema_min: int,
        artifact_schema_max: int,
        stability_window_seconds: float = 5.0,
        maintenance_participant_id: str | None = None,
    ) -> CutoverStatus:
        """Bind final migration and backup evidence while maintenance is active."""

        self._require_actor(actor_id)
        self._require_text(run_id, "run_id")
        self._validate_artifact_bounds(
            artifact_sha,
            artifact_contract_min,
            artifact_contract_max,
            artifact_schema_min,
            artifact_schema_max,
        )
        backup = self._verify_backup(backup_archive)
        self._require_backup_source_roots(backup)
        reconciliation = self._reconcile_for_cutover(
            run_id,
            maintenance_participant_id=maintenance_participant_id,
        )
        if reconciliation.blocking_issues or not reconciliation.cutover_allowed:
            raise CutoverPreconditionError(
                "migration reconciliation is not cutover-ready: "
                + ", ".join(reconciliation.blocking_issues)
            )
        self._legacy_sources.assert_no_pending_seal()
        inventory = self._legacy_sources.capture()
        preflight_epoch = self._require_preflight(stability_window_seconds)
        with self._maintenance_control_operation(
            source="domain-cutover.prepare",
            participant_id=maintenance_participant_id,
            expected_epoch=preflight_epoch,
        ):
            self._verify_legacy_inventory(inventory)
            return self._prepare_transaction(
                actor_id=actor_id,
                run_id=run_id,
                backup=backup,
                artifact_sha=artifact_sha,
                artifact_contract_min=artifact_contract_min,
                artifact_contract_max=artifact_contract_max,
                artifact_schema_min=artifact_schema_min,
                artifact_schema_max=artifact_schema_max,
                inventory=inventory,
                preflight_epoch=preflight_epoch,
            )

    def commit(
        self,
        *,
        actor_id: str,
        run_id: str,
        backup_archive: Path,
        artifact_sha: str,
        artifact_contract_min: int,
        artifact_contract_max: int,
        artifact_schema_min: int,
        artifact_schema_max: int,
        stability_window_seconds: float = 5.0,
        maintenance_participant_id: str | None = None,
    ) -> CutoverStatus:
        """Commit a prepared fuse after repeating all hard safety gates.

        A failed commit before the first v2 write automatically aborts the
        prepared state and records that abort.  The original failure remains
        visible to the caller.
        """

        try:
            self._require_actor(actor_id)
            self._require_text(run_id, "run_id")
            self._validate_artifact_bounds(
                artifact_sha,
                artifact_contract_min,
                artifact_contract_max,
                artifact_schema_min,
                artifact_schema_max,
            )
            backup = self._verify_backup(backup_archive)
            self._require_backup_source_roots(backup)
            reconciliation = self._reconcile_for_cutover(
                run_id,
                maintenance_participant_id=maintenance_participant_id,
            )
            if reconciliation.blocking_issues or not reconciliation.cutover_allowed:
                raise CutoverPreconditionError(
                    "migration reconciliation is not cutover-ready: "
                    + ", ".join(reconciliation.blocking_issues)
                )
            prepared = self._read_prepared_row()
            inventory = self._inventory_from_row(prepared)
            if inventory is None:
                raise CutoverPreconditionError("prepared cutover has no legacy source inventory")
            preflight_epoch = self._require_preflight(stability_window_seconds)
            with self._maintenance_control_operation(
                source="domain-cutover.commit",
                participant_id=maintenance_participant_id,
                expected_epoch=preflight_epoch,
            ):
                self._verify_legacy_inventory(inventory)
                self._seal_legacy_inventory(inventory)
                return self._commit_transaction(
                    actor_id=actor_id,
                    run_id=run_id,
                    backup=backup,
                    artifact_sha=artifact_sha,
                    artifact_contract_min=artifact_contract_min,
                    artifact_contract_max=artifact_contract_max,
                    artifact_schema_min=artifact_schema_min,
                    artifact_schema_max=artifact_schema_max,
                    inventory=inventory,
                    preflight_epoch=preflight_epoch,
                )
        except (CutoverPreconditionError, LegacySourceGuardError) as exc:
            self._abort_after_failed_commit(
                actor_id,
                str(exc),
                maintenance_participant_id=maintenance_participant_id,
            )
            if isinstance(exc, CutoverPreconditionError):
                raise
            raise CutoverPreconditionError("legacy source seal failed") from exc

    def abort(
        self,
        *,
        actor_id: str,
        reason: str,
        maintenance_participant_id: str | None = None,
    ) -> CutoverStatus:
        """Return a prepared cutover to legacy before any v2 write exists."""

        self._require_actor(actor_id)
        self._require_text(reason, "reason")
        # Preserve the explicit irreversible-v2 error even after maintenance
        # has reopened.  This preliminary read is non-mutating; the active
        # maintenance control lease below repeats every mutable-state check.
        with closing(connect(self._db_path)) as conn:
            initial = self._state_row(conn)
        if str(initial["state"]) == "v2" or initial["first_v2_write_at"] is not None:
            raise DomainCutoverError(
                "committed v2 cutover cannot be aborted; restore a complete pre-cutover backup"
            )
        if str(initial["state"]) != "prepared":
            raise DomainCutoverError("only a prepared cutover can be aborted")
        with self._maintenance_control_operation(
            source="domain-cutover.abort",
            participant_id=maintenance_participant_id,
        ):
            # Restore the source modes before returning the database to legacy.
            # If a crash occurs after this step but before the state transition,
            # the prepared fuse remains fail-closed; a retry sees no journal and
            # completes only the durable state transition.
            with closing(connect(self._db_path)) as conn:
                row = self._state_row(conn)
                if str(row["state"]) == "v2" or row["first_v2_write_at"] is not None:
                    raise DomainCutoverError(
                        "committed v2 cutover cannot be aborted; restore a complete pre-cutover backup"
                    )
                if str(row["state"]) != "prepared":
                    raise DomainCutoverError("only a prepared cutover can be aborted")
                inventory = self._inventory_from_row(row)
                if inventory is None:
                    raise DomainCutoverError("prepared cutover has no legacy source inventory")
            self._legacy_sources.unseal(inventory)
            with closing(connect(self._db_path)) as conn:
                conn.execute("BEGIN IMMEDIATE")
                try:
                    row = self._state_row(conn)
                    if str(row["state"]) == "v2" or row["first_v2_write_at"] is not None:
                        raise DomainCutoverError(
                            "committed v2 cutover cannot be aborted; restore a complete pre-cutover backup"
                        )
                    if str(row["state"]) != "prepared":
                        raise DomainCutoverError("only a prepared cutover can be aborted")
                    epoch = int(row["cutover_epoch"])
                    run_id = self._optional_text(row["cutover_run_id"])
                    preparation_digest = self._optional_text(row["preparation_digest"])
                    conn.execute(
                        """
                        UPDATE domain_cutover_state
                        SET state = 'legacy', cutover_run_id = NULL, source_manifest_json = NULL,
                            reconciled_at = NULL, blocking_issue_count = 0, cutover_ready = 0,
                            prepared_at = NULL, prepared_by_user_id = NULL, committed_at = NULL,
                            committed_by_user_id = NULL, first_v2_write_at = NULL,
                            first_v2_write_actor_id = NULL, artifact_sha = NULL,
                            artifact_contract_min = NULL, artifact_contract_max = NULL,
                            artifact_schema_min = NULL, artifact_schema_max = NULL,
                            backup_manifest_sha256 = NULL, backup_tree_sha256 = NULL,
                            backup_created_at = NULL, backup_version = NULL, maintenance_epoch = NULL,
                            source_inventory_json = NULL, source_inventory_sha256 = NULL,
                            restore_evidence_sha256 = NULL, preparation_digest = NULL,
                            prepared_blocking_issue_count = 0
                        WHERE singleton = 1
                        """
                    )
                    self._record_event(
                        conn,
                        epoch=epoch,
                        event_type="aborted",
                        actor_id=actor_id,
                        run_id=run_id,
                        preparation_digest=preparation_digest,
                        payload={"reason": reason},
                    )
                    self._audit(
                        conn,
                        actor_id,
                        "domain_cutover.aborted",
                        "domain_cutover",
                        str(epoch),
                        {"run_id": run_id, "reason": reason},
                    )
                    updated = self._state_row(conn)
                    conn.commit()
                except Exception:
                    conn.rollback()
                    raise
            return self._status_from_row(updated, None, None)

    def assert_v2_writable(self, *, artifact_sha: str | None = None) -> CutoverStatus:
        """Fail closed unless the database fuse authorizes a v2 write."""

        status = self.status()
        if status.state != "v2" or not status.constraints_ready or not status.cutover_ready:
            raise DomainCutoverError("domain v2 cutover fuse is not committed and ready")
        if status.legacy_sources_stable is not True:
            raise DomainCutoverError("legacy source monitor is not stable")
        if artifact_sha is not None and artifact_sha != status.artifact_sha:
            raise DomainCutoverError("running artifact does not match committed domain cutover")
        with closing(connect(self._db_path)) as conn:
            self.assert_v2_writable_in_transaction(conn, artifact_sha=artifact_sha)
        return status

    def assert_v2_writable_in_transaction(
        self, conn: sqlite3.Connection, *, artifact_sha: str | None = None
    ) -> CutoverStatus:
        """Re-check the fuse with a caller-owned write transaction.

        This does not start or commit a transaction, making it safe for Task,
        Context, and Domain writers to use before they mutate their own rows.
        """

        row = self._state_row(conn)
        self._assert_committed_fuse(conn, row, artifact_sha=artifact_sha)
        inventory = self._inventory_from_row(row)
        if inventory is None:
            raise DomainCutoverError("committed cutover has no legacy source inventory")
        self._verify_legacy_inventory(inventory)
        self._verify_legacy_seal(inventory, error_type=DomainCutoverError)
        return self._status_from_row(row, True, None)

    def record_first_v2_write(
        self, *, actor_id: str, artifact_sha: str | None = None
    ) -> CutoverStatus:
        """Open a transaction and persist first-v2-write metadata once."""

        self._require_actor(actor_id)
        with closing(connect(self._db_path)) as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                status = self.record_first_v2_write_in_transaction(
                    conn, actor_id=actor_id, artifact_sha=artifact_sha
                )
                conn.commit()
            except Exception:
                conn.rollback()
                raise
        return status

    def record_first_v2_write_in_transaction(
        self,
        conn: sqlite3.Connection,
        *,
        actor_id: str,
        artifact_sha: str | None = None,
    ) -> CutoverStatus:
        """Record the first v2 write inside a caller-owned transaction.

        The caller retains ownership of commit/rollback.  Calling this more
        than once is idempotent after the first metadata row has been written.
        """

        self._require_actor(actor_id)
        maintenance = conn.execute(
            """
            SELECT is_active FROM domain_maintenance_state
            WHERE singleton = 1
            """
        ).fetchone()
        if maintenance is None or bool(maintenance["is_active"]):
            raise MaintenanceModeError("domain first v2 write is paused for maintenance")
        row = self._state_row(conn)
        self._assert_committed_fuse(conn, row, artifact_sha=artifact_sha)
        inventory = self._inventory_from_row(row)
        if inventory is None:
            raise DomainCutoverError("committed cutover has no legacy source inventory")
        self._verify_legacy_inventory(inventory)
        self._verify_legacy_seal(inventory, error_type=DomainCutoverError)
        if row["first_v2_write_at"] is not None:
            return self._status_from_row(row, True, None)
        now = _now()
        conn.execute(
            """
            UPDATE domain_cutover_state
            SET first_v2_write_at = ?, first_v2_write_actor_id = ?
            WHERE singleton = 1
            """,
            (now, actor_id),
        )
        epoch = int(row["cutover_epoch"])
        run_id = self._optional_text(row["cutover_run_id"])
        preparation_digest = self._optional_text(row["preparation_digest"])
        self._record_event(
            conn,
            epoch=epoch,
            event_type="first_v2_write",
            actor_id=actor_id,
            run_id=run_id,
            preparation_digest=preparation_digest,
            payload={"artifact_sha": self._optional_text(row["artifact_sha"])},
        )
        self._audit(
            conn,
            actor_id,
            "domain_cutover.first_v2_write",
            "domain_cutover",
            str(epoch),
            {"run_id": run_id, "artifact_sha": self._optional_text(row["artifact_sha"])},
        )
        updated = self._state_row(conn)
        return self._status_from_row(updated, True, None)

    def _finalize_constraints_transaction(
        self,
        *,
        actor_id: str,
        run_id: str,
        preflight_epoch: int,
    ) -> ConstraintFinalization:
        """Install the Task guard and its durable audit attestation atomically."""

        with closing(connect(self._db_path)) as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                state = self._state_row(conn)
                if str(state["state"]) != "legacy":
                    raise DomainCutoverError(
                        "domain constraints can only be finalized before cutover prepare"
                    )
                if state["first_v2_write_at"] is not None:
                    raise DomainCutoverError("legacy state unexpectedly records a v2 write")
                self._assert_maintenance_epoch(conn, preflight_epoch)
                schema_version = self._schema_version(conn)
                invalid_task_count = int(
                    conn.execute(
                        """
                        SELECT COUNT(*)
                        FROM tasks AS task
                        WHERE NOT EXISTS (
                            SELECT 1 FROM projects
                            WHERE project_id = task.project_id
                        )
                           OR NOT EXISTS (
                               SELECT 1 FROM workspaces
                               WHERE workspace_id = task.workspace_id
                                 AND environment_id = task.environment_id
                           )
                           OR NOT EXISTS (
                               SELECT 1 FROM project_workspace_links
                               WHERE project_id = task.project_id
                                 AND workspace_id = task.workspace_id
                                 AND status = 'active'
                           )
                        """
                    ).fetchone()[0]
                )
                if invalid_task_count:
                    raise CutoverPreconditionError(
                        "domain constraints cannot be finalized: "
                        f"{invalid_task_count} Task reference(s) do not map to a Project, "
                        "active Project-Workspace link, and derived Environment"
                    )
                task_reference_count = int(conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0])
                integrity = conn.execute("PRAGMA integrity_check").fetchone()
                if integrity is None or str(integrity[0]) != "ok":
                    raise CutoverPreconditionError(
                        "domain constraints cannot be finalized: SQLite integrity check failed"
                    )
                if conn.execute("PRAGMA foreign_key_check").fetchone() is not None:
                    raise CutoverPreconditionError(
                        "domain constraints cannot be finalized: SQLite foreign-key check failed"
                    )

                # This is intentionally done while the maintenance epoch still
                # owns the sole writer slot.  The function uses transactional
                # DDL so either the two equivalent FK guards and their audit
                # evidence commit together, or neither one does.
                install_domain_task_reference_guards(conn)
                guard_digest = domain_task_reference_guard_digest(conn)
                evidence_at = self._constraint_evidence_at(
                    conn,
                    schema_version=schema_version,
                    guard_digest=guard_digest,
                )
                if not bool(state["constraints_ready"]) or evidence_at is None:
                    now = _now()
                    conn.execute(
                        """
                        UPDATE domain_cutover_state
                        SET constraints_ready = 1
                        WHERE singleton = 1
                        """
                    )
                    self._audit(
                        conn,
                        actor_id,
                        "domain_cutover.constraints_finalized",
                        "domain_constraints",
                        "tasks",
                        {
                            "run_id": run_id,
                            "maintenance_epoch": preflight_epoch,
                            "schema_version": schema_version,
                            "task_reference_count": task_reference_count,
                            "guard_digest": guard_digest,
                        },
                    )
                    evidence_at = now
                updated = self._state_row(conn)
                self._assert_constraints_ready(
                    conn,
                    updated,
                    error_type=CutoverPreconditionError,
                )
                conn.commit()
            except Exception:
                conn.rollback()
                raise
        return ConstraintFinalization(
            run_id=run_id,
            maintenance_epoch=preflight_epoch,
            schema_version=schema_version,
            task_reference_count=task_reference_count,
            guard_digest=guard_digest,
            finalized_at=evidence_at,
            cutover_allowed=False,
        )

    def _prepare_transaction(
        self,
        *,
        actor_id: str,
        run_id: str,
        backup: _BackupEvidence,
        artifact_sha: str,
        artifact_contract_min: int,
        artifact_contract_max: int,
        artifact_schema_min: int,
        artifact_schema_max: int,
        inventory: LegacySourceInventory,
        preflight_epoch: int,
    ) -> CutoverStatus:
        with closing(connect(self._db_path)) as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                state = self._state_row(conn)
                if str(state["state"]) != "legacy":
                    raise DomainCutoverError("domain cutover is not in legacy state")
                if state["first_v2_write_at"] is not None:
                    raise DomainCutoverError("legacy state unexpectedly records a v2 write")
                self._assert_constraints_ready(
                    conn,
                    state,
                    error_type=CutoverPreconditionError,
                )
                self._assert_maintenance_epoch(conn, preflight_epoch)
                actual_schema = self._schema_version(conn)
                contract_version = int(state["contract_version"])
                self._assert_artifact_supports(
                    contract_version,
                    actual_schema,
                    artifact_contract_min,
                    artifact_contract_max,
                    artifact_schema_min,
                    artifact_schema_max,
                )
                run = self._assert_finalized_run(
                    conn,
                    run_id=run_id,
                    artifact_sha=artifact_sha,
                    backup_manifest_sha256=backup.manifest_sha256,
                    backup_tree_sha256=backup.tree_sha256,
                )
                self._verify_legacy_inventory(inventory)
                epoch = int(state["cutover_epoch"]) + 1
                source_manifest = str(run["final_manifest_json"])
                preparation_digest = self._preparation_digest(
                    run_id=run_id,
                    backup=backup,
                    artifact_sha=artifact_sha,
                    artifact_contract_min=artifact_contract_min,
                    artifact_contract_max=artifact_contract_max,
                    artifact_schema_min=artifact_schema_min,
                    artifact_schema_max=artifact_schema_max,
                    contract_version=contract_version,
                    schema_version=actual_schema,
                    maintenance_epoch=preflight_epoch,
                    source_manifest_sha256=str(run["final_manifest_sha256"]),
                    source_inventory_sha256=inventory.digest,
                    restore_evidence_sha256=str(run["restore_evidence_sha256"]),
                    maintenance_source_roots_sha256=self._maintenance.source_root_config_digest(),
                )
                now = _now()
                conn.execute(
                    """
                    UPDATE domain_cutover_state
                    SET state = 'prepared', schema_version = ?, cutover_epoch = ?,
                        cutover_run_id = ?, source_manifest_json = ?, reconciled_at = ?,
                        blocking_issue_count = 0, cutover_ready = 0, prepared_at = ?,
                        prepared_by_user_id = ?, committed_at = NULL, committed_by_user_id = NULL,
                        first_v2_write_at = NULL, first_v2_write_actor_id = NULL,
                        artifact_sha = ?, artifact_contract_min = ?, artifact_contract_max = ?,
                        artifact_schema_min = ?, artifact_schema_max = ?, backup_manifest_sha256 = ?,
                        backup_tree_sha256 = ?, backup_created_at = ?, backup_version = ?,
                        maintenance_epoch = ?, source_inventory_json = ?,
                        source_inventory_sha256 = ?, restore_evidence_sha256 = ?,
                        preparation_digest = ?, prepared_blocking_issue_count = 0
                    WHERE singleton = 1
                    """,
                    (
                        actual_schema,
                        epoch,
                        run_id,
                        source_manifest,
                        self._optional_text(run["reconciled_at"]),
                        now,
                        actor_id,
                        artifact_sha,
                        artifact_contract_min,
                        artifact_contract_max,
                        artifact_schema_min,
                        artifact_schema_max,
                        backup.manifest_sha256,
                        backup.tree_sha256,
                        backup.created_at,
                        backup.version,
                        preflight_epoch,
                        _canonical_json(inventory.as_dict()),
                        inventory.digest,
                        str(run["restore_evidence_sha256"]),
                        preparation_digest,
                    ),
                )
                self._record_event(
                    conn,
                    epoch=epoch,
                    event_type="prepared",
                    actor_id=actor_id,
                    run_id=run_id,
                    preparation_digest=preparation_digest,
                    payload={
                        "artifact_sha": artifact_sha,
                        "backup_manifest_sha256": backup.manifest_sha256,
                        "source_inventory_sha256": inventory.digest,
                        "maintenance_source_roots_sha256": self._maintenance.source_root_config_digest(),
                    },
                )
                self._audit(
                    conn,
                    actor_id,
                    "domain_cutover.prepared",
                    "domain_cutover",
                    str(epoch),
                    {"run_id": run_id, "preparation_digest": preparation_digest},
                )
                updated = self._state_row(conn)
                conn.commit()
            except Exception:
                conn.rollback()
                raise
        return self._status_from_row(updated, True, None)

    def _commit_transaction(
        self,
        *,
        actor_id: str,
        run_id: str,
        backup: _BackupEvidence,
        artifact_sha: str,
        artifact_contract_min: int,
        artifact_contract_max: int,
        artifact_schema_min: int,
        artifact_schema_max: int,
        inventory: LegacySourceInventory,
        preflight_epoch: int,
    ) -> CutoverStatus:
        with closing(connect(self._db_path)) as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                state = self._state_row(conn)
                if str(state["state"]) != "prepared":
                    raise CutoverPreconditionError("domain cutover is not prepared")
                self._assert_maintenance_epoch(conn, preflight_epoch)
                self._assert_prepared_binding(
                    conn,
                    state,
                    run_id=run_id,
                    backup=backup,
                    artifact_sha=artifact_sha,
                    artifact_contract_min=artifact_contract_min,
                    artifact_contract_max=artifact_contract_max,
                    artifact_schema_min=artifact_schema_min,
                    artifact_schema_max=artifact_schema_max,
                    inventory=inventory,
                )
                self._assert_finalized_run(
                    conn,
                    run_id=run_id,
                    artifact_sha=artifact_sha,
                    backup_manifest_sha256=backup.manifest_sha256,
                    backup_tree_sha256=backup.tree_sha256,
                )
                self._verify_legacy_inventory(inventory)
                self._verify_legacy_seal(
                    inventory,
                    error_type=CutoverPreconditionError,
                )
                now = _now()
                conn.execute(
                    """
                    UPDATE domain_cutover_state
                    SET state = 'v2', committed_at = ?, committed_by_user_id = ?,
                        constraints_ready = 1, cutover_ready = 1
                    WHERE singleton = 1
                    """,
                    (now, actor_id),
                )
                epoch = int(state["cutover_epoch"])
                digest = str(state["preparation_digest"])
                self._record_event(
                    conn,
                    epoch=epoch,
                    event_type="committed",
                    actor_id=actor_id,
                    run_id=run_id,
                    preparation_digest=digest,
                    payload={
                        "artifact_sha": artifact_sha,
                        "backup_manifest_sha256": backup.manifest_sha256,
                    },
                )
                self._audit(
                    conn,
                    actor_id,
                    "domain_cutover.committed",
                    "domain_cutover",
                    str(epoch),
                    {"run_id": run_id, "preparation_digest": digest},
                )
                updated = self._state_row(conn)
                conn.commit()
            except Exception:
                conn.rollback()
                raise
        return self._status_from_row(updated, True, None)

    def _assert_prepared_binding(
        self,
        conn: sqlite3.Connection,
        state: sqlite3.Row,
        *,
        run_id: str,
        backup: _BackupEvidence,
        artifact_sha: str,
        artifact_contract_min: int,
        artifact_contract_max: int,
        artifact_schema_min: int,
        artifact_schema_max: int,
        inventory: LegacySourceInventory,
    ) -> None:
        expected: dict[str, object] = {
            "cutover_run_id": run_id,
            "artifact_sha": artifact_sha,
            "artifact_contract_min": artifact_contract_min,
            "artifact_contract_max": artifact_contract_max,
            "artifact_schema_min": artifact_schema_min,
            "artifact_schema_max": artifact_schema_max,
            "backup_manifest_sha256": backup.manifest_sha256,
            "backup_tree_sha256": backup.tree_sha256,
            "backup_created_at": backup.created_at,
            "backup_version": backup.version,
            "source_inventory_sha256": inventory.digest,
        }
        mismatched = [name for name, value in expected.items() if state[name] != value]
        if mismatched:
            raise CutoverPreconditionError(
                "prepared cutover binding does not match commit input: " + ", ".join(mismatched)
            )
        if state["first_v2_write_at"] is not None or state["first_v2_write_actor_id"] is not None:
            raise CutoverPreconditionError("prepared cutover unexpectedly has v2 write metadata")
        if not bool(state["constraints_ready"]) or bool(state["cutover_ready"]):
            raise CutoverPreconditionError("prepared cutover has invalid readiness flags")
        self._assert_constraints_ready(
            conn,
            state,
            error_type=CutoverPreconditionError,
        )
        actual_schema = self._schema_version(conn)
        if int(state["schema_version"]) != actual_schema:
            raise CutoverPreconditionError("database schema changed after cutover prepare")
        contract_version = int(state["contract_version"])
        self._assert_artifact_supports(
            contract_version,
            actual_schema,
            artifact_contract_min,
            artifact_contract_max,
            artifact_schema_min,
            artifact_schema_max,
        )
        expected_digest = self._preparation_digest(
            run_id=run_id,
            backup=backup,
            artifact_sha=artifact_sha,
            artifact_contract_min=artifact_contract_min,
            artifact_contract_max=artifact_contract_max,
            artifact_schema_min=artifact_schema_min,
            artifact_schema_max=artifact_schema_max,
            contract_version=contract_version,
            schema_version=actual_schema,
            maintenance_epoch=int(state["maintenance_epoch"]),
            source_manifest_sha256=self._source_manifest_sha256(state),
            source_inventory_sha256=inventory.digest,
            restore_evidence_sha256=str(state["restore_evidence_sha256"]),
            maintenance_source_roots_sha256=self._maintenance.source_root_config_digest(),
        )
        if state["preparation_digest"] != expected_digest:
            raise CutoverPreconditionError("prepared cutover digest does not match bound evidence")

    def _assert_committed_fuse(
        self, conn: sqlite3.Connection, state: sqlite3.Row, *, artifact_sha: str | None
    ) -> None:
        if (
            str(state["state"]) != "v2"
            or not bool(state["constraints_ready"])
            or not bool(state["cutover_ready"])
        ):
            raise DomainCutoverError("domain v2 cutover fuse is not committed and ready")
        self._assert_constraints_ready(conn, state, error_type=DomainCutoverError)
        if artifact_sha is not None and state["artifact_sha"] != artifact_sha:
            raise DomainCutoverError("running artifact does not match committed domain cutover")
        actual_schema = self._schema_version(conn)
        if int(state["schema_version"]) != actual_schema:
            raise DomainCutoverError("database schema changed after the committed cutover")
        minimum_contract = state["artifact_contract_min"]
        maximum_contract = state["artifact_contract_max"]
        minimum_schema = state["artifact_schema_min"]
        maximum_schema = state["artifact_schema_max"]
        if (
            minimum_contract is None
            or maximum_contract is None
            or minimum_schema is None
            or maximum_schema is None
        ):
            raise DomainCutoverError("committed cutover lacks artifact compatibility metadata")
        self._assert_artifact_supports(
            int(state["contract_version"]),
            actual_schema,
            int(minimum_contract),
            int(maximum_contract),
            int(minimum_schema),
            int(maximum_schema),
        )
        if state["preparation_digest"] is None or state["source_inventory_sha256"] is None:
            raise DomainCutoverError("committed cutover is missing immutable preparation evidence")

    def _assert_finalized_run(
        self,
        conn: sqlite3.Connection,
        *,
        run_id: str,
        artifact_sha: str,
        backup_manifest_sha256: str,
        backup_tree_sha256: str,
    ) -> sqlite3.Row:
        run = conn.execute(
            "SELECT * FROM domain_migration_runs WHERE run_id = ?", (run_id,)
        ).fetchone()
        if run is None:
            raise CutoverPreconditionError(f"unknown domain migration run: {run_id}")
        if str(run["status"]) != "completed" or str(run["phase"]) != "completed":
            raise CutoverPreconditionError("migration run is not completed")
        if not bool(run["cutover_allowed"]):
            raise CutoverPreconditionError("migration run is not cutover-allowed")
        if run["finalized_at"] is None or run["reconciled_at"] is None:
            raise CutoverPreconditionError("migration run lacks finalized reconciliation evidence")
        if run["artifact_sha"] != artifact_sha:
            raise CutoverPreconditionError("migration artifact does not match cutover artifact")
        final_manifest = self._optional_text(run["final_manifest_json"])
        final_manifest_sha256 = self._optional_text(run["final_manifest_sha256"])
        source_manifest_sha256 = self._optional_text(run["source_manifest_sha256"])
        if (
            final_manifest is None
            or not _is_sha256(final_manifest_sha256)
            or source_manifest_sha256 != final_manifest_sha256
            or hashlib.sha256(final_manifest.encode("utf-8")).hexdigest() != final_manifest_sha256
        ):
            raise CutoverPreconditionError(
                "migration run source manifest is not immutable and valid"
            )
        evidence_json = self._optional_text(run["restore_evidence_json"])
        evidence_sha256 = self._optional_text(run["restore_evidence_sha256"])
        if (
            evidence_json is None
            or not _is_sha256(evidence_sha256)
            or hashlib.sha256(evidence_json.encode("utf-8")).hexdigest() != evidence_sha256
            or run["restore_evidence_verified_at"] is None
        ):
            raise CutoverPreconditionError("migration run has no valid restore evidence")
        try:
            evidence = json.loads(evidence_json)
        except json.JSONDecodeError as exc:
            raise CutoverPreconditionError("migration restore evidence is invalid JSON") from exc
        if not isinstance(evidence, dict) or evidence.get("status") != "valid":
            raise CutoverPreconditionError("migration restore evidence is not valid")
        if evidence.get("manifest_sha256") not in {
            backup_manifest_sha256,
            backup_tree_sha256,
        }:
            raise CutoverPreconditionError(
                "restore evidence does not bind the verified backup manifest"
            )
        unresolved = int(
            conn.execute(
                """
                SELECT COUNT(*) FROM domain_migration_issues AS issue
                WHERE issue.run_id = ? AND issue.severity = 'blocking'
                  AND NOT (
                      issue.resolution_status = 'resolved'
                      AND EXISTS (
                          SELECT 1 FROM domain_migration_resolutions AS resolution
                          WHERE resolution.run_id = issue.run_id
                            AND resolution.issue_id = issue.issue_id
                            AND resolution.resolution_type = issue.resolution_type
                            AND resolution.applied_at IS NOT NULL
                      )
                  )
                """,
                (run_id,),
            ).fetchone()[0]
        )
        if unresolved != 0:
            raise CutoverPreconditionError("migration run has unresolved blocking issues")
        return run

    def _assert_maintenance_epoch(self, conn: sqlite3.Connection, preflight_epoch: int) -> None:
        maintenance = conn.execute(
            """
            SELECT maintenance_epoch, is_active FROM domain_maintenance_state
            WHERE singleton = 1
            """
        ).fetchone()
        if maintenance is None or not bool(maintenance["is_active"]):
            raise CutoverPreconditionError("domain maintenance mode is not active")
        if int(maintenance["maintenance_epoch"]) != preflight_epoch:
            raise CutoverPreconditionError("domain maintenance epoch changed during cutover")

    def _assert_constraints_ready(
        self,
        conn: sqlite3.Connection,
        state: sqlite3.Row,
        *,
        error_type: type[DomainCutoverError],
    ) -> None:
        """Require both the flag and a matching, audited guard installation."""

        if not bool(state["constraints_ready"]):
            raise error_type("domain constraints are not ready")
        schema_version = self._schema_version(conn)
        try:
            guard_digest = domain_task_reference_guard_digest(conn)
        except RuntimeError as exc:
            raise error_type("domain Task reference guards are missing or invalid") from exc
        if (
            self._constraint_evidence_at(
                conn,
                schema_version=schema_version,
                guard_digest=guard_digest,
            )
            is None
        ):
            raise error_type("domain constraints lack a valid maintenance audit attestation")

    @staticmethod
    def _constraint_evidence_at(
        conn: sqlite3.Connection,
        *,
        schema_version: int,
        guard_digest: str,
    ) -> str | None:
        """Return an append-only finalization audit matching the live guards."""

        rows = conn.execute(
            """
            SELECT metadata_json, created_at
            FROM domain_audit_events
            WHERE event_type = 'domain_cutover.constraints_finalized'
              AND subject_type = 'domain_constraints'
              AND subject_id = 'tasks'
            ORDER BY created_at DESC, event_id DESC
            """
        ).fetchall()
        for row in rows:
            raw_metadata = row["metadata_json"]
            if not isinstance(raw_metadata, str):
                continue
            try:
                metadata = json.loads(raw_metadata)
            except json.JSONDecodeError:
                continue
            if not isinstance(metadata, dict):
                continue
            if (
                metadata.get("schema_version") == schema_version
                and metadata.get("guard_digest") == guard_digest
                and isinstance(row["created_at"], str)
            ):
                return str(row["created_at"])
        return None

    def _require_preflight(self, stability_window_seconds: float) -> int:
        # Do not rely on the service default here.  A cutover controller is a
        # hard safety boundary, so its writer inventory remains explicit even
        # if a future diagnostic caller needs a narrower preflight.
        report = self._maintenance.preflight(
            required_participant_types=CUTOVER_REQUIRED_PARTICIPANT_TYPES,
            stability_window_seconds=stability_window_seconds,
        )
        if report.ready:
            return self._maintenance.status().maintenance_epoch
        detail = {
            "maintenance_active": report.maintenance_active,
            "active_attempt_count": report.active_attempt_count,
            "pending_runtime_launch_count": report.pending_runtime_launch_count,
            "unflushed_output_count": report.unflushed_output_count,
            "source_stable": report.source_stable,
            "participants_drained": report.participants_drained,
            "missing_participant_types": report.missing_participant_types,
            "stale_participant_ids": report.stale_participant_ids,
        }
        raise CutoverPreconditionError(
            "domain maintenance preflight failed: " + _canonical_json(detail)
        )

    def _verify_backup(self, backup_archive: Path) -> _BackupEvidence:
        try:
            manifest = BackupService(self._state_root).verify_backup(backup_archive)
        except (OSError, ValueError) as exc:
            raise CutoverPreconditionError("backup archive verification failed") from exc
        if manifest.version < 3 or not _is_sha256(manifest.tree_sha256):
            raise CutoverPreconditionError("domain cutover requires a verified backup manifest v3")
        return _BackupEvidence(
            manifest_sha256=backup_manifest_sha256(manifest),
            tree_sha256=str(manifest.tree_sha256),
            created_at=manifest.created_at,
            version=manifest.version,
            includes_workspaces=manifest.includes_workspaces,
            includes_tenants=manifest.includes_tenants,
        )

    def _require_backup_source_roots(self, backup: _BackupEvidence) -> None:
        """Require an explicit stability root for every selected backup tree.

        A manifest can prove bytes were copied, but it cannot prove an
        external Workspace or tenant tree stayed still during the cutover
        window.  The operator must therefore pass the exact root for every
        optional tree in the archive.  Conversely, accepting an unrelated
        root when the archive omitted it would turn the prepared binding into
        misleading evidence, so that is rejected as well.
        """

        expected = {
            "workspace": backup.includes_workspaces,
            "tenant": backup.includes_tenants,
        }
        for source_kind, included in expected.items():
            configured = self._maintenance.has_configured_source_root(source_kind)
            if included and not configured:
                raise CutoverPreconditionError(
                    f"backup includes {source_kind} data but no explicit maintenance "
                    f"{source_kind}_root was configured"
                )
            if configured and not included:
                raise CutoverPreconditionError(
                    f"explicit maintenance {source_kind}_root was configured but the backup "
                    f"does not include {source_kind} data"
                )

    @contextmanager
    def _maintenance_control_operation(
        self,
        *,
        source: str,
        participant_id: str | None,
        expected_epoch: int | None = None,
    ) -> Iterator[MaintenanceLease]:
        """Make a cutover write visible to maintenance exit and the registry."""

        lease = self._maintenance.begin_maintenance_operation(
            source=source,
            participant_id=participant_id,
            expected_epoch=expected_epoch,
        )
        try:
            self._maintenance.check_maintenance_operation(lease)
            yield lease
            self._maintenance.check_maintenance_operation(lease)
        finally:
            self._maintenance.finish_mutation(lease)

    def _reconcile_for_cutover(
        self,
        run_id: str,
        *,
        maintenance_participant_id: str | None,
        expected_epoch: int | None = None,
    ) -> ReconciliationReport:
        try:
            from ainrf.domain_migration import DomainReconciliationService

            with self._maintenance_control_operation(
                source="domain-cutover.reconcile",
                participant_id=maintenance_participant_id,
                expected_epoch=expected_epoch,
            ):
                return DomainReconciliationService(self._state_root).reconcile(run_id)
        except (OSError, ValueError) as exc:
            raise CutoverPreconditionError(
                "migration reconciliation could not be verified"
            ) from exc

    def _read_prepared_row(self) -> sqlite3.Row:
        with closing(connect(self._db_path)) as conn:
            row = self._state_row(conn)
        if str(row["state"]) != "prepared":
            raise CutoverPreconditionError("domain cutover is not prepared")
        return row

    def _verify_legacy_inventory(self, inventory: LegacySourceInventory) -> None:
        try:
            self._legacy_sources.verify(inventory)
        except LegacySourceDriftError as exc:
            raise CutoverPreconditionError(str(exc)) from exc
        except LegacySourceGuardError as exc:
            raise CutoverPreconditionError("legacy source guard failed") from exc

    def _seal_legacy_inventory(self, inventory: LegacySourceInventory) -> None:
        """Apply the pre-commit physical seal or reject the cutover."""

        try:
            self._legacy_sources.seal(inventory)
        except LegacySourceGuardError as exc:
            raise CutoverPreconditionError("legacy source seal failed") from exc

    def _verify_legacy_seal(
        self,
        inventory: LegacySourceInventory,
        *,
        error_type: type[DomainCutoverError],
    ) -> None:
        try:
            self._legacy_sources.verify_sealed(inventory)
        except LegacySourceGuardError as exc:
            raise error_type("legacy source seal is not valid") from exc

    def _abort_after_failed_commit(
        self,
        actor_id: str,
        detail: str,
        *,
        maintenance_participant_id: str | None,
    ) -> None:
        if not actor_id:
            return
        try:
            with closing(connect(self._db_path)) as conn:
                row = self._state_row(conn)
            if str(row["state"]) == "prepared" and row["first_v2_write_at"] is None:
                self.abort(
                    actor_id=actor_id,
                    reason=f"automatic commit abort: {detail}",
                    maintenance_participant_id=maintenance_participant_id,
                )
        except (DomainCutoverError, LegacySourceGuardError, MaintenanceModeError):
            return

    @staticmethod
    def _require_actor(actor_id: str) -> None:
        if not actor_id:
            raise ValueError("actor_id is required")

    @staticmethod
    def _require_text(value: str, name: str) -> None:
        if not value:
            raise ValueError(f"{name} is required")

    @staticmethod
    def _validate_artifact_bounds(
        artifact_sha: str,
        artifact_contract_min: int,
        artifact_contract_max: int,
        artifact_schema_min: int,
        artifact_schema_max: int,
    ) -> None:
        if not _is_sha256(artifact_sha):
            raise ValueError("artifact_sha must be a SHA-256 hex digest")
        if (
            artifact_contract_min < 0
            or artifact_contract_max < artifact_contract_min
            or artifact_schema_min < 0
            or artifact_schema_max < artifact_schema_min
        ):
            raise ValueError("artifact contract/schema support ranges are invalid")

    @staticmethod
    def _assert_artifact_supports(
        contract_version: int,
        schema_version: int,
        artifact_contract_min: int,
        artifact_contract_max: int,
        artifact_schema_min: int,
        artifact_schema_max: int,
    ) -> None:
        if not artifact_contract_min <= contract_version <= artifact_contract_max:
            raise CutoverPreconditionError("artifact does not support the domain contract version")
        if not artifact_schema_min <= schema_version <= artifact_schema_max:
            raise CutoverPreconditionError("artifact does not support the domain schema version")

    @staticmethod
    def _state_row(conn: sqlite3.Connection) -> sqlite3.Row:
        row = conn.execute("SELECT * FROM domain_cutover_state WHERE singleton = 1").fetchone()
        if row is None:
            raise RuntimeError("domain cutover state is not initialized")
        return row

    @staticmethod
    def _schema_version(conn: sqlite3.Connection) -> int:
        row = conn.execute(
            "SELECT version FROM _schema_version WHERE database = 'agentic_researcher'"
        ).fetchone()
        if row is None:
            raise RuntimeError("agentic_researcher schema version is not initialized")
        return int(row[0])

    @staticmethod
    def _optional_text(value: object) -> str | None:
        return str(value) if value is not None else None

    @staticmethod
    def _inventory_from_row(row: sqlite3.Row) -> LegacySourceInventory | None:
        raw = row["source_inventory_json"]
        if raw is None:
            return None
        if not isinstance(raw, str):
            raise DomainCutoverError("persisted legacy source inventory is invalid")
        try:
            inventory = LegacySourceInventory.from_dict(json.loads(raw))
        except (ValueError, json.JSONDecodeError) as exc:
            raise DomainCutoverError("persisted legacy source inventory is invalid") from exc
        if row["source_inventory_sha256"] != inventory.digest:
            raise DomainCutoverError("persisted legacy source inventory digest is invalid")
        return inventory

    @staticmethod
    def _source_manifest_sha256(row: sqlite3.Row) -> str:
        source_manifest = row["source_manifest_json"]
        if not isinstance(source_manifest, str):
            raise CutoverPreconditionError("prepared cutover has no source manifest")
        return hashlib.sha256(source_manifest.encode("utf-8")).hexdigest()

    @staticmethod
    def _preparation_digest(
        *,
        run_id: str,
        backup: _BackupEvidence,
        artifact_sha: str,
        artifact_contract_min: int,
        artifact_contract_max: int,
        artifact_schema_min: int,
        artifact_schema_max: int,
        contract_version: int,
        schema_version: int,
        maintenance_epoch: int,
        source_manifest_sha256: str,
        source_inventory_sha256: str,
        restore_evidence_sha256: str,
        maintenance_source_roots_sha256: str,
    ) -> str:
        return _sha256(
            {
                "migration_run_id": run_id,
                "backup_manifest_sha256": backup.manifest_sha256,
                "backup_tree_sha256": backup.tree_sha256,
                "backup_created_at": backup.created_at,
                "backup_version": backup.version,
                "artifact_sha": artifact_sha,
                "artifact_contract_min": artifact_contract_min,
                "artifact_contract_max": artifact_contract_max,
                "artifact_schema_min": artifact_schema_min,
                "artifact_schema_max": artifact_schema_max,
                "contract_version": contract_version,
                "schema_version": schema_version,
                "maintenance_epoch": maintenance_epoch,
                "source_manifest_sha256": source_manifest_sha256,
                "source_inventory_sha256": source_inventory_sha256,
                "restore_evidence_sha256": restore_evidence_sha256,
                "maintenance_source_roots_sha256": maintenance_source_roots_sha256,
                "blocking_issue_count": 0,
            }
        )

    @staticmethod
    def _record_event(
        conn: sqlite3.Connection,
        *,
        epoch: int,
        event_type: str,
        actor_id: str,
        run_id: str | None,
        preparation_digest: str | None,
        payload: dict[str, object],
    ) -> None:
        conn.execute(
            """
            INSERT INTO domain_cutover_events (
                event_id, cutover_epoch, event_type, actor_user_id, migration_run_id,
                preparation_digest, payload_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                uuid4().hex,
                epoch,
                event_type,
                actor_id,
                run_id,
                preparation_digest,
                _canonical_json(payload),
                _now(),
            ),
        )

    @staticmethod
    def _audit(
        conn: sqlite3.Connection,
        actor_id: str,
        event_type: str,
        subject_type: str,
        subject_id: str,
        metadata: dict[str, object],
    ) -> None:
        conn.execute(
            """
            INSERT INTO domain_audit_events (
                event_id, actor_id, event_type, subject_type, subject_id, metadata_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                uuid4().hex,
                actor_id,
                event_type,
                subject_type,
                subject_id,
                _canonical_json(metadata),
                _now(),
            ),
        )

    @staticmethod
    def _status_from_row(
        row: sqlite3.Row,
        legacy_sources_stable: bool | None,
        legacy_source_drift: str | None,
    ) -> CutoverStatus:
        def optional_int(name: str) -> int | None:
            return int(row[name]) if row[name] is not None else None

        return CutoverStatus(
            state=str(row["state"]),
            contract_version=int(row["contract_version"]),
            schema_version=int(row["schema_version"]),
            cutover_epoch=int(row["cutover_epoch"]),
            cutover_run_id=DomainCutoverController._optional_text(row["cutover_run_id"]),
            prepared_at=DomainCutoverController._optional_text(row["prepared_at"]),
            prepared_by_user_id=DomainCutoverController._optional_text(row["prepared_by_user_id"]),
            committed_at=DomainCutoverController._optional_text(row["committed_at"]),
            committed_by_user_id=DomainCutoverController._optional_text(
                row["committed_by_user_id"]
            ),
            first_v2_write_at=DomainCutoverController._optional_text(row["first_v2_write_at"]),
            first_v2_write_actor_id=DomainCutoverController._optional_text(
                row["first_v2_write_actor_id"]
            ),
            artifact_sha=DomainCutoverController._optional_text(row["artifact_sha"]),
            artifact_contract_min=optional_int("artifact_contract_min"),
            artifact_contract_max=optional_int("artifact_contract_max"),
            artifact_schema_min=optional_int("artifact_schema_min"),
            artifact_schema_max=optional_int("artifact_schema_max"),
            backup_manifest_sha256=DomainCutoverController._optional_text(
                row["backup_manifest_sha256"]
            ),
            backup_tree_sha256=DomainCutoverController._optional_text(row["backup_tree_sha256"]),
            maintenance_epoch=optional_int("maintenance_epoch"),
            blocking_issue_count=int(row["blocking_issue_count"]),
            constraints_ready=bool(row["constraints_ready"]),
            cutover_ready=bool(row["cutover_ready"]),
            source_inventory_sha256=DomainCutoverController._optional_text(
                row["source_inventory_sha256"]
            ),
            preparation_digest=DomainCutoverController._optional_text(row["preparation_digest"]),
            legacy_sources_stable=legacy_sources_stable,
            legacy_source_drift=legacy_source_drift,
        )
