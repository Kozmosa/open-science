"""Typed, audited remediation for domain migration reconciliation issues."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import closing
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING
from uuid import uuid4

from ainrf.db import connect, run_pending
from ainrf.domain.context import (
    context_version_fingerprint,
    empty_fragment_manifest_json,
    record_context_version_fragment_provenance_in_transaction,
    unresolved_legacy_fragment_provenance_evidence,
)

if TYPE_CHECKING:
    from ainrf.domain_migration.importer import ReconciliationReport

_RESOLUTION_KINDS = {
    "assign_project_owner": "owner_mapping",
    "assign_workspace_owner": "owner_mapping",
    "assign_task_owner": "owner_mapping",
    "assign_workspace_environment": "environment_mapping",
    "set_primary_workspace": "primary_workspace",
    "map_runtime_session": "session_mapping",
}

_ALLOWED_CATEGORIES = {
    "assign_project_owner": frozenset({"owner_missing", "owner_unmapped"}),
    "assign_workspace_owner": frozenset({"workspace_owner_unmapped"}),
    "assign_task_owner": frozenset({"task_owner_unmapped"}),
    "assign_workspace_environment": frozenset(
        {
            "workspace_environment_missing",
            "workspace_environment_invalid",
            "workspace_environment_ambiguous",
            "legacy_environment_placeholder",
            "task_domain_mapping_invalid",
        }
    ),
    "set_primary_workspace": frozenset(
        {
            "primary_workspace_missing",
            "primary_workspace_conflict",
            "primary_link_inactive",
            "workspace_project_missing",
        }
    ),
    "map_runtime_session": frozenset(
        {
            "session_mapping_missing",
            "session_unmapped",
            "session_attempt_unmapped",
            "runtime_checkpoint_unmapped",
        }
    ),
}


@dataclass(frozen=True, slots=True)
class MigrationIssue:
    issue_id: str
    run_id: str
    category: str
    record_type: str
    record_id: str
    severity: str
    detail: str
    resolution_status: str
    resolution_type: str | None
    resolution: dict[str, object]
    resolved_by_user_id: str | None
    resolved_at: str | None

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class MigrationFinalization:
    run_id: str
    artifact_sha: str
    source_manifest_sha256: str
    restore_evidence_sha256: str
    restore_evidence_verified_at: str
    cutover_allowed: bool
    finalized_at: str

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))


def _parse_json_object(value: object) -> dict[str, object]:
    if not isinstance(value, str):
        return {}
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return {}
    if not isinstance(parsed, dict):
        return {}
    return {str(key): item for key, item in parsed.items()}


class DomainReconciliationService:
    """Apply only explicit, domain-specific migration remediations.

    There is intentionally no generic ``ignore`` operation.  A resolution is
    materialized in the target control plane, recorded in an append-only
    resolution row and audit event, then marks the issue resolved in the same
    transaction.
    """

    def __init__(self, state_root: Path) -> None:
        self._state_root = state_root
        self._db_path = state_root / "runtime" / "agentic_researcher.sqlite3"
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        with closing(connect(self._db_path)) as conn:
            run_pending(conn, "agentic_researcher")

    def _connect(self) -> sqlite3.Connection:
        return connect(self._db_path)

    def list_issues(
        self, run_id: str, *, include_resolved: bool = False
    ) -> tuple[MigrationIssue, ...]:
        with closing(self._connect()) as conn:
            clauses = ["run_id = ?"]
            params: list[object] = [run_id]
            if not include_resolved:
                clauses.append(
                    """
                    NOT (
                        resolution_status = 'resolved'
                        AND EXISTS (
                            SELECT 1 FROM domain_migration_resolutions AS resolution
                            WHERE resolution.run_id = domain_migration_issues.run_id
                              AND resolution.issue_id = domain_migration_issues.issue_id
                              AND resolution.resolution_type = domain_migration_issues.resolution_type
                              AND resolution.applied_at IS NOT NULL
                        )
                    )
                    """
                )
            rows = conn.execute(
                f"""
                SELECT * FROM domain_migration_issues
                WHERE {" AND ".join(clauses)}
                ORDER BY severity DESC, category, record_type, record_id, issue_id
                """,
                tuple(params),
            ).fetchall()
        return tuple(self._issue_from_row(row) for row in rows)

    def inspect_issue(self, issue_id: str) -> MigrationIssue:
        with closing(self._connect()) as conn:
            row = conn.execute(
                "SELECT * FROM domain_migration_issues WHERE issue_id = ?", (issue_id,)
            ).fetchone()
        if row is None:
            raise LookupError(f"Unknown domain migration issue: {issue_id}")
        return self._issue_from_row(row)

    def resolve_issue(
        self,
        run_id: str,
        issue_id: str,
        resolution_type: str,
        payload: dict[str, object],
        *,
        actor_id: str,
    ) -> MigrationIssue:
        """Apply an explicit resolution and write an audit trail atomically."""

        if not actor_id:
            raise ValueError("actor_id is required for a migration resolution")
        internal_type = _RESOLUTION_KINDS.get(resolution_type)
        if internal_type is None:
            raise ValueError(f"Unsupported migration resolution type: {resolution_type}")
        if not isinstance(payload, dict):
            raise ValueError("resolution payload must be an object")
        with closing(self._connect()) as conn:
            issue = conn.execute(
                "SELECT * FROM domain_migration_issues WHERE issue_id = ? AND run_id = ?",
                (issue_id, run_id),
            ).fetchone()
            if issue is None:
                raise LookupError(f"Issue {issue_id} does not belong to migration run {run_id}")
            if str(issue["resolution_status"]) == "resolved":
                raise ValueError("Migration issue has already been resolved")
            category = str(issue["category"])
            if category not in _ALLOWED_CATEGORIES[resolution_type]:
                raise ValueError(
                    f"Resolution {resolution_type} cannot resolve issue category {category}"
                )
            if resolution_type == "assign_project_owner":
                self._assign_project_owner(conn, issue, payload)
            elif resolution_type == "assign_workspace_owner":
                self._assign_workspace_owner(conn, issue, payload)
            elif resolution_type == "assign_task_owner":
                self._assign_task_owner(conn, issue, payload)
            elif resolution_type == "assign_workspace_environment":
                self._assign_workspace_environment(conn, issue, payload)
            elif resolution_type == "set_primary_workspace":
                self._set_primary_workspace(conn, issue, payload)
            else:
                self._map_runtime_session(conn, issue, payload)
            now = _now()
            resolution_payload = dict(payload)
            resolution_payload["requested_resolution_type"] = resolution_type
            conn.execute(
                """
                INSERT INTO domain_migration_resolutions (
                    resolution_id, run_id, issue_id, resolution_type, actor_user_id,
                    payload_json, created_at, updated_at, applied_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    uuid4().hex,
                    run_id,
                    issue_id,
                    internal_type,
                    actor_id,
                    _canonical_json(resolution_payload),
                    now,
                    now,
                    now,
                ),
            )
            conn.execute(
                """
                UPDATE domain_migration_issues
                SET resolution_status = 'resolved', resolution_type = ?, resolution_json = ?,
                    resolved_by_user_id = ?, resolved_at = ?
                WHERE issue_id = ? AND run_id = ?
                """,
                (
                    internal_type,
                    _canonical_json(resolution_payload),
                    actor_id,
                    now,
                    issue_id,
                    run_id,
                ),
            )
            self._audit(
                conn,
                actor_id,
                "domain_migration_issue.resolved",
                "migration_issue",
                issue_id,
                {"run_id": run_id, "resolution_type": resolution_type},
            )
            updated = conn.execute(
                "SELECT * FROM domain_migration_issues WHERE issue_id = ?", (issue_id,)
            ).fetchone()
            conn.commit()
        if updated is None:
            raise RuntimeError("Resolved migration issue disappeared")
        return self._issue_from_row(updated)

    def reconcile(self, run_id: str | None = None) -> ReconciliationReport:
        """Re-run structural checks and verify every claimed repair still holds."""

        from ainrf.domain_migration.importer import DomainImporter, ReconciliationReport

        report = DomainImporter(self._state_root).reconcile(run_id)
        with closing(self._connect()) as conn:
            residual = self._resolved_invariant_blockers(conn, report.run_id)
            if residual:
                conn.execute(
                    "UPDATE domain_migration_runs SET cutover_allowed = 0 WHERE run_id = ?",
                    (report.run_id,),
                )
                conn.commit()
        if not residual:
            return report
        return ReconciliationReport(
            run_id=report.run_id,
            counts=report.counts,
            blocking_issues=tuple(sorted(set(report.blocking_issues).union(residual))),
            non_blocking_issues=report.non_blocking_issues,
            cutover_allowed=False,
        )

    def finalize_run(
        self,
        run_id: str,
        actor_id: str,
        artifact_sha: str,
        restore_evidence: dict[str, object],
    ) -> MigrationFinalization:
        """Record immutable pre-prepare evidence without switching v2 writes.

        This is deliberately an eligibility step, not the B7 cutover state
        transition.  It cannot enable v2 mode or alter ``constraints_ready``.
        """

        if not actor_id:
            raise ValueError("actor_id is required to finalize a migration run")
        if not self._is_sha256(artifact_sha):
            raise ValueError("artifact_sha must be a SHA-256 hex digest")
        evidence = self._validate_restore_evidence(restore_evidence)
        reconciliation = self.reconcile(run_id)
        if reconciliation.blocking_issues:
            raise ValueError("Migration run still has unresolved reconciliation blockers")
        with closing(self._connect()) as conn:
            run = conn.execute(
                "SELECT * FROM domain_migration_runs WHERE run_id = ?", (run_id,)
            ).fetchone()
            if run is None:
                raise LookupError(f"Unknown domain migration run: {run_id}")
            if str(run["status"]) != "completed" or str(run["phase"]) != "completed":
                raise ValueError("Only a completed migration run may be finalized")
            if run["finalized_at"] is not None:
                raise ValueError("Migration run has already been finalized")
            source_manifest = str(run["source_manifest_json"])
            source_manifest_sha256 = str(run["source_manifest_sha256"] or "")
            if not self._is_sha256(source_manifest_sha256) or (
                hashlib.sha256(source_manifest.encode("utf-8")).hexdigest()
                != source_manifest_sha256
            ):
                raise ValueError("Migration run has no valid immutable source manifest")
            stored_artifact = run["artifact_sha"]
            if stored_artifact is not None and str(stored_artifact) != artifact_sha:
                raise ValueError("artifact_sha does not match the migration run")
            unresolved = int(
                conn.execute(
                    """
                    SELECT COUNT(*) FROM domain_migration_issues issue
                    WHERE issue.run_id = ? AND issue.severity = 'blocking'
                      AND (
                          issue.resolution_status != 'resolved'
                          OR NOT EXISTS (
                              SELECT 1 FROM domain_migration_resolutions resolution
                              WHERE resolution.issue_id = issue.issue_id
                                AND resolution.run_id = issue.run_id
                                AND resolution.resolution_type = issue.resolution_type
                                AND resolution.applied_at IS NOT NULL
                          )
                      )
                    """,
                    (run_id,),
                ).fetchone()[0]
            )
            if unresolved:
                raise ValueError("Migration run still has unresolved blocking issues")
            now = _now()
            evidence_json = _canonical_json(evidence)
            evidence_sha256 = hashlib.sha256(evidence_json.encode("utf-8")).hexdigest()
            conn.execute(
                """
                UPDATE domain_migration_runs
                SET artifact_sha = ?, final_manifest_json = ?, final_manifest_sha256 = ?,
                    restore_evidence_json = ?, restore_evidence_sha256 = ?,
                    restore_evidence_verified_at = ?, finalized_at = ?,
                    reconciled_at = ?, cutover_allowed = 1
                WHERE run_id = ?
                """,
                (
                    artifact_sha,
                    source_manifest,
                    source_manifest_sha256,
                    evidence_json,
                    evidence_sha256,
                    str(evidence["validated_at"]),
                    now,
                    now,
                    run_id,
                ),
            )
            self._audit(
                conn,
                actor_id,
                "domain_migration_run.finalized",
                "migration_run",
                run_id,
                {
                    "artifact_sha": artifact_sha,
                    "source_manifest_sha256": source_manifest_sha256,
                    "restore_evidence_sha256": evidence_sha256,
                },
            )
            conn.commit()
        return MigrationFinalization(
            run_id=run_id,
            artifact_sha=artifact_sha,
            source_manifest_sha256=source_manifest_sha256,
            restore_evidence_sha256=evidence_sha256,
            restore_evidence_verified_at=str(evidence["validated_at"]),
            cutover_allowed=True,
            finalized_at=now,
        )

    def _assign_project_owner(
        self, conn: sqlite3.Connection, issue: sqlite3.Row, payload: dict[str, object]
    ) -> None:
        owner_user_id = payload.get("owner_user_id")
        if not isinstance(owner_user_id, str) or not owner_user_id:
            raise ValueError("assign_project_owner requires owner_user_id")
        username = self._auth_username(owner_user_id)
        project_id = payload.get("project_id", issue["record_id"])
        if not isinstance(project_id, str) or not project_id:
            raise ValueError("assign_project_owner requires a project_id")
        project = conn.execute(
            "SELECT 1 FROM projects WHERE project_id = ?", (project_id,)
        ).fetchone()
        if project is not None:
            conn.execute(
                "UPDATE projects SET owner_user_id = ?, updated_at = ? WHERE project_id = ?",
                (owner_user_id, _now(), project_id),
            )
            return

        archived = conn.execute(
            """
            SELECT payload_json FROM legacy_domain_records
            WHERE run_id = ? AND record_type = 'project' AND source_record_id = ?
            ORDER BY created_at, legacy_record_id
            LIMIT 1
            """,
            (str(issue["run_id"]), project_id),
        ).fetchone()
        if archived is None:
            raise LookupError(
                "Unknown Project for owner assignment; no archived source record is available"
            )
        source = _parse_json_object(archived["payload_json"])
        source_project_id = source.get("project_id")
        if source_project_id != project_id:
            raise ValueError("Archived Project source does not match the migration issue")
        name = source.get("name")
        description = source.get("description")
        created_at = source.get("created_at")
        updated_at = source.get("updated_at")
        status = "archived" if source.get("status") == "archived" else "active"
        wants_default = (
            source.get("is_default") is True
            or project_id == "default"
            or project_id == f"{username}_default"
        )
        has_default = conn.execute(
            """
            SELECT 1 FROM projects
            WHERE owner_user_id = ? AND status = 'active' AND is_default = 1
            """,
            (owner_user_id,),
        ).fetchone()
        now = _now()
        conn.execute(
            """
            INSERT INTO projects (
                project_id, owner_user_id, name, description, status, is_default,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                project_id,
                owner_user_id,
                name if isinstance(name, str) and name else project_id,
                description if isinstance(description, str) else None,
                status,
                int(status == "active" and wants_default and has_default is None),
                created_at if isinstance(created_at, str) and created_at else now,
                updated_at if isinstance(updated_at, str) and updated_at else now,
            ),
        )
        self._ensure_legacy_project_context(conn, project_id, owner_user_id, now)

    def _assign_workspace_owner(
        self, conn: sqlite3.Connection, issue: sqlite3.Row, payload: dict[str, object]
    ) -> None:
        """Rehydrate an archived Workspace only after explicit owner and Environment choices.

        A Workspace with an unresolved legacy owner is deliberately not inserted
        by the importer.  Reconciliation must therefore materialize its durable
        identity, rather than merely marking an issue resolved.  It never
        silently restores Primary status: that remains a separate, audited
        ``set_primary_workspace`` decision.
        """

        owner_user_id = self._required_owner_user_id(payload, "assign_workspace_owner")
        workspace_id = self._required_record_id(payload, issue, "workspace_id")
        source = self._archived_source(conn, issue, "workspace", workspace_id)
        path = source.get("default_workdir")
        if not isinstance(path, str) or not Path(path).is_absolute():
            raise ValueError("Archived Workspace has no absolute canonical path")
        environment_id = payload.get("environment_id")
        if not isinstance(environment_id, str) or not environment_id:
            raise ValueError("assign_workspace_owner requires an active environment_id")
        environment = conn.execute(
            "SELECT 1 FROM environments WHERE environment_id = ? AND status = 'active'",
            (environment_id,),
        ).fetchone()
        if environment is None:
            raise LookupError("Workspace owner resolution requires an active Environment")
        project_id = source.get("project_id")
        if project_id is not None and (not isinstance(project_id, str) or not project_id):
            raise ValueError("Archived Workspace has an invalid Project reference")
        if isinstance(project_id, str):
            project = conn.execute(
                "SELECT owner_user_id FROM projects WHERE project_id = ?", (project_id,)
            ).fetchone()
            if project is None:
                raise LookupError("Resolve the Workspace Project before assigning its owner")
        canonical_path = str(Path(path).expanduser().resolve())
        existing = conn.execute(
            """
            SELECT environment_id, canonical_path FROM workspaces
            WHERE workspace_id = ?
            """,
            (workspace_id,),
        ).fetchone()
        now = _now()
        if existing is None:
            status = "unregistered" if source.get("status") == "unregistered" else "active"
            conn.execute(
                """
                INSERT INTO workspaces (
                    workspace_id, owner_user_id, environment_id, canonical_path, label,
                    description, workspace_context, legacy_project_id, status, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    workspace_id,
                    owner_user_id,
                    environment_id,
                    canonical_path,
                    str(source.get("label", workspace_id)),
                    source.get("description")
                    if isinstance(source.get("description"), str)
                    else None,
                    (
                        source.get("workspace_prompt")
                        if isinstance(source.get("workspace_prompt"), str)
                        else None
                    ),
                    project_id,
                    status,
                    source.get("created_at") if isinstance(source.get("created_at"), str) else now,
                    source.get("updated_at") if isinstance(source.get("updated_at"), str) else now,
                ),
            )
        elif (
            str(existing["environment_id"]) != environment_id
            or str(existing["canonical_path"]) != canonical_path
        ):
            raise ValueError(
                "Workspace ID is already bound to a different Environment or canonical path"
            )
        else:
            conn.execute(
                "UPDATE workspaces SET owner_user_id = ?, updated_at = ? WHERE workspace_id = ?",
                (owner_user_id, now, workspace_id),
            )

        if isinstance(project_id, str):
            workspace = conn.execute(
                "SELECT status FROM workspaces WHERE workspace_id = ?", (workspace_id,)
            ).fetchone()
            if workspace is not None and str(workspace["status"]) == "active":
                conn.execute(
                    """
                    INSERT INTO project_workspace_links (
                        project_id, workspace_id, status, is_primary, actor_id, created_at, updated_at
                    ) VALUES (?, ?, 'active', 0, ?, ?, ?)
                    ON CONFLICT(project_id, workspace_id) DO UPDATE SET
                        status = 'active', actor_id = excluded.actor_id, updated_at = excluded.updated_at
                    """,
                    (project_id, workspace_id, owner_user_id, now, now),
                )
                if source.get("is_primary") is True:
                    self._record_issue(
                        conn,
                        str(issue["run_id"]),
                        category="primary_workspace_missing",
                        record_type="workspace",
                        record_id=workspace_id,
                        detail=(
                            "Legacy Workspace was Primary; select the Primary explicitly after "
                            "owner remediation"
                        ),
                    )

    def _assign_task_owner(
        self, conn: sqlite3.Connection, issue: sqlite3.Row, payload: dict[str, object]
    ) -> None:
        """Map an archived Task owner and finish its immutable legacy context pin."""

        owner_user_id = self._required_owner_user_id(payload, "assign_task_owner")
        task_id = self._required_record_id(payload, issue, "task_id")
        source = self._archived_source(conn, issue, "task", task_id)
        task = conn.execute(
            """
            SELECT task_id, project_id, workspace_id, environment_id,
                   project_context_version_id, project_context_snapshot_id, latest_attempt_id
            FROM tasks WHERE task_id = ?
            """,
            (task_id,),
        ).fetchone()
        if task is None:
            raise LookupError("Unknown Task for owner assignment")
        project = conn.execute(
            "SELECT owner_user_id FROM projects WHERE project_id = ?", (str(task["project_id"]),)
        ).fetchone()
        workspace = conn.execute(
            "SELECT environment_id FROM workspaces WHERE workspace_id = ?",
            (str(task["workspace_id"]),),
        ).fetchone()
        if project is None or workspace is None:
            raise ValueError("Resolve the Task Project and Workspace before assigning its owner")
        if str(workspace["environment_id"]) != str(task["environment_id"]):
            raise ValueError(
                "Resolve the Task Workspace/Environment mapping before assigning its owner"
            )

        project_id = str(task["project_id"])
        version_id = task["project_context_version_id"]
        if not isinstance(version_id, str) or not version_id:
            version_id = self._ensure_legacy_project_context(
                conn, project_id, str(project["owner_user_id"]), _now()
            )
        snapshot_id = task["project_context_snapshot_id"]
        if not isinstance(snapshot_id, str) or not snapshot_id:
            snapshot_id = f"legacy-snapshot-{task_id}"
            conn.execute(
                """
                INSERT OR IGNORE INTO context_snapshots (
                    context_snapshot_id, context_version_id, fingerprint, content,
                    source_manifest_json, created_at
                ) VALUES (?, ?, ?, '', '[]', ?)
                """,
                (snapshot_id, version_id, hashlib.sha256(b"").hexdigest(), _now()),
            )
        now = _now()
        conn.execute(
            """
            UPDATE tasks
            SET owner_user_id = ?, project_context_version_id = ?,
                project_context_snapshot_id = ?
            WHERE task_id = ?
            """,
            (owner_user_id, version_id, snapshot_id, task_id),
        )
        attempt = conn.execute(
            "SELECT attempt_id FROM agent_task_attempts WHERE task_id = ? ORDER BY attempt_seq LIMIT 1",
            (task_id,),
        ).fetchone()
        if attempt is None:
            attempt_id = f"legacy-task-attempt-{task_id}"
            raw_status = source.get("status")
            attempt_status = self._legacy_attempt_status(raw_status)
            conn.execute(
                """
                INSERT INTO agent_task_attempts (
                    attempt_id, task_id, attempt_seq, trigger, status, context_snapshot_id,
                    started_at, finished_at, token_usage_json, created_at
                ) VALUES (?, ?, 1, 'legacy_task', ?, ?, ?, ?, ?, ?)
                """,
                (
                    attempt_id,
                    task_id,
                    attempt_status,
                    snapshot_id,
                    source.get("started_at") if isinstance(source.get("started_at"), str) else None,
                    source.get("completed_at")
                    if isinstance(source.get("completed_at"), str)
                    else None,
                    self._json_text(source.get("token_usage_json")),
                    now,
                ),
            )
            conn.execute(
                "UPDATE tasks SET latest_attempt_id = ? WHERE task_id = ?",
                (attempt_id, task_id),
            )

    def _required_owner_user_id(self, payload: dict[str, object], action: str) -> str:
        owner_user_id = payload.get("owner_user_id")
        if not isinstance(owner_user_id, str) or not owner_user_id:
            raise ValueError(f"{action} requires owner_user_id")
        self._auth_username(owner_user_id)
        return owner_user_id

    @staticmethod
    def _required_record_id(payload: dict[str, object], issue: sqlite3.Row, field: str) -> str:
        record_id = payload.get(field, issue["record_id"])
        if not isinstance(record_id, str) or not record_id:
            raise ValueError(f"Resolution requires {field}")
        if record_id != str(issue["record_id"]):
            raise ValueError(f"Resolution {field} does not match the migration issue")
        return record_id

    @staticmethod
    def _archived_source(
        conn: sqlite3.Connection, issue: sqlite3.Row, record_type: str, record_id: str
    ) -> dict[str, object]:
        row = conn.execute(
            """
            SELECT payload_json FROM legacy_domain_records
            WHERE run_id = ? AND record_type = ? AND source_record_id = ?
            ORDER BY created_at, legacy_record_id LIMIT 1
            """,
            (str(issue["run_id"]), record_type, record_id),
        ).fetchone()
        if row is None:
            raise LookupError("No archived source record is available for owner resolution")
        source = _parse_json_object(row["payload_json"])
        source_id = source.get(f"{record_type}_id")
        if source_id != record_id:
            raise ValueError("Archived source record does not match the migration issue")
        return source

    @staticmethod
    def _legacy_attempt_status(value: object) -> str:
        raw = value if isinstance(value, str) else "completed"
        return {
            "pending": "queued",
            "active": "running",
            "cancelled": "cancelled",
            "canceled": "cancelled",
            "stopped": "stopped",
        }.get(raw, raw)

    @staticmethod
    def _json_text(value: object) -> str | None:
        if value is None:
            return None
        if isinstance(value, str):
            return value
        return _canonical_json(value)

    @staticmethod
    def _record_issue(
        conn: sqlite3.Connection,
        run_id: str,
        *,
        category: str,
        record_type: str,
        record_id: str,
        detail: str,
    ) -> None:
        existing = conn.execute(
            """
            SELECT 1 FROM domain_migration_issues
            WHERE run_id = ? AND category = ? AND record_type = ? AND record_id = ?
            """,
            (run_id, category, record_type, record_id),
        ).fetchone()
        if existing is not None:
            return
        conn.execute(
            """
            INSERT INTO domain_migration_issues (
                issue_id, run_id, category, record_type, record_id, severity, detail, created_at
            ) VALUES (?, ?, ?, ?, ?, 'blocking', ?, ?)
            """,
            (uuid4().hex, run_id, category, record_type, record_id, detail, _now()),
        )

    @staticmethod
    def _ensure_legacy_project_context(
        conn: sqlite3.Connection, project_id: str, owner_user_id: str, now: str
    ) -> str:
        version_id = f"legacy-empty-{project_id}"
        conn.execute(
            """
            INSERT OR IGNORE INTO project_context_drafts
                (project_id, content, updated_by_user_id, updated_at)
            VALUES (?, '', ?, ?)
            """,
            (project_id, owner_user_id, now),
        )
        conn.execute(
            """
            INSERT OR IGNORE INTO project_context_versions
                (context_version_id, project_id, content, fingerprint, fragment_manifest_json,
                 is_active, created_by_user_id, created_at)
            VALUES (?, ?, '', ?, ?, 1, ?, ?)
            """,
            (
                version_id,
                project_id,
                context_version_fingerprint(""),
                empty_fragment_manifest_json(),
                owner_user_id,
                now,
            ),
        )
        provenance_row = conn.execute(
            """
            SELECT 1 FROM project_context_version_provenance
            WHERE context_version_id = ?
            """,
            (version_id,),
        ).fetchone()
        if provenance_row is None:
            record_context_version_fragment_provenance_in_transaction(
                conn,
                context_version_id=version_id,
                status="attention_needed",
                evidence_json=unresolved_legacy_fragment_provenance_evidence(
                    source="domain_reconciliation.synthetic_legacy_context"
                ),
                recorded_at=now,
            )
        return version_id

    @staticmethod
    def _assign_workspace_environment(
        conn: sqlite3.Connection, issue: sqlite3.Row, payload: dict[str, object]
    ) -> None:
        environment_id = payload.get("environment_id", payload.get("replacement_environment_id"))
        if not isinstance(environment_id, str) or not environment_id:
            raise ValueError("assign_workspace_environment requires environment_id")
        environment = conn.execute(
            "SELECT status FROM environments WHERE environment_id = ?", (environment_id,)
        ).fetchone()
        if environment is None or str(environment["status"]) != "active":
            raise ValueError("Workspace resolution requires an active Environment")
        category = str(issue["category"])
        if category == "legacy_environment_placeholder":
            source_environment_id = payload.get("source_environment_id", issue["record_id"])
            if not isinstance(source_environment_id, str) or not source_environment_id:
                raise ValueError("legacy Environment resolution requires source_environment_id")
            now = _now()
            conn.execute(
                """
                UPDATE workspaces SET environment_id = ?, updated_at = ?
                WHERE environment_id = ?
                """,
                (environment_id, now, source_environment_id),
            )
            conn.execute(
                "UPDATE tasks SET environment_id = ?, updated_at = ? WHERE environment_id = ?",
                (environment_id, now, source_environment_id),
            )
            return
        if category == "task_domain_mapping_invalid":
            task_id = str(issue["record_id"])
            workspace_id = payload.get("workspace_id")
            if not isinstance(workspace_id, str) or not workspace_id:
                raise ValueError("Task Environment resolution requires workspace_id")
            workspace = conn.execute(
                """
                SELECT environment_id FROM workspaces
                WHERE workspace_id = ? AND status = 'active'
                """,
                (workspace_id,),
            ).fetchone()
            if workspace is None or str(workspace["environment_id"]) != environment_id:
                raise ValueError("Task resolution Workspace must derive the selected Environment")
            task = conn.execute(
                "SELECT project_id FROM tasks WHERE task_id = ?", (task_id,)
            ).fetchone()
            if task is None:
                raise LookupError(f"Unknown Task for Environment assignment: {task_id}")
            project_id = payload.get("project_id", task["project_id"])
            if not isinstance(project_id, str) or not project_id:
                raise ValueError("Task resolution requires a Project")
            project = conn.execute(
                "SELECT 1 FROM projects WHERE project_id = ?", (project_id,)
            ).fetchone()
            if project is None:
                raise LookupError(f"Unknown Project for Task Environment assignment: {project_id}")
            conn.execute(
                """
                UPDATE tasks
                SET project_id = ?, workspace_id = ?, environment_id = ?, updated_at = ?
                WHERE task_id = ?
                """,
                (project_id, workspace_id, environment_id, _now(), task_id),
            )
            return
        workspace_id = payload.get("workspace_id", issue["record_id"])
        if not isinstance(workspace_id, str) or not workspace_id:
            raise ValueError("assign_workspace_environment requires a workspace_id")
        updated = conn.execute(
            "UPDATE workspaces SET environment_id = ?, updated_at = ? WHERE workspace_id = ?",
            (environment_id, _now(), workspace_id),
        )
        if updated.rowcount != 1:
            raise LookupError(f"Unknown Workspace for environment assignment: {workspace_id}")

    @staticmethod
    def _set_primary_workspace(
        conn: sqlite3.Connection, issue: sqlite3.Row, payload: dict[str, object]
    ) -> None:
        workspace_id = payload.get("workspace_id", issue["record_id"])
        if not isinstance(workspace_id, str) or not workspace_id:
            raise ValueError("set_primary_workspace requires workspace_id")
        default_project_id = issue["record_id"] if str(issue["record_type"]) == "project" else None
        project_id = payload.get("project_id", default_project_id)
        if not isinstance(project_id, str) or not project_id:
            raise ValueError("set_primary_workspace requires project_id")
        project = conn.execute(
            "SELECT owner_user_id FROM projects WHERE project_id = ? AND status = 'active'",
            (project_id,),
        ).fetchone()
        if project is None:
            raise LookupError(f"Unknown active Project for Primary Workspace: {project_id}")
        workspace = conn.execute(
            "SELECT 1 FROM workspaces WHERE workspace_id = ? AND status = 'active'", (workspace_id,)
        ).fetchone()
        if workspace is None:
            raise LookupError(f"Unknown active Workspace for Primary assignment: {workspace_id}")
        link = conn.execute(
            """
            SELECT 1 FROM project_workspace_links
            WHERE project_id = ? AND workspace_id = ? AND status = 'active'
            """,
            (project_id, workspace_id),
        ).fetchone()
        if link is None:
            conn.execute(
                """
                INSERT INTO project_workspace_links (
                    project_id, workspace_id, status, is_primary, actor_id, created_at, updated_at
                ) VALUES (?, ?, 'active', 0, ?, ?, ?)
                ON CONFLICT(project_id, workspace_id) DO UPDATE SET
                    status = 'active', actor_id = excluded.actor_id, updated_at = excluded.updated_at
                """,
                (project_id, workspace_id, str(project["owner_user_id"]), _now(), _now()),
            )
        conn.execute(
            """
            UPDATE project_workspace_links SET is_primary = 0, updated_at = ?
            WHERE project_id = ? AND status = 'active'
            """,
            (_now(), project_id),
        )
        conn.execute(
            """
            UPDATE project_workspace_links SET is_primary = 1, updated_at = ?
            WHERE project_id = ? AND workspace_id = ? AND status = 'active'
            """,
            (_now(), project_id, workspace_id),
        )

    @staticmethod
    def _map_runtime_session(
        conn: sqlite3.Connection, issue: sqlite3.Row, payload: dict[str, object]
    ) -> None:
        attempt_id = payload.get("attempt_id")
        if not isinstance(attempt_id, str) or not attempt_id:
            raise ValueError("map_runtime_session requires attempt_id")
        attempt = conn.execute(
            "SELECT status FROM agent_task_attempts WHERE attempt_id = ?", (attempt_id,)
        ).fetchone()
        if attempt is None:
            raise LookupError(f"Unknown Attempt for runtime session mapping: {attempt_id}")
        runtime_session_id = payload.get("runtime_session_id")
        if not isinstance(runtime_session_id, str) or not runtime_session_id:
            runtime_session_id = f"resolved-runtime-{issue['issue_id']}"
        existing = conn.execute(
            "SELECT attempt_id FROM agent_runtime_sessions WHERE runtime_session_id = ?",
            (runtime_session_id,),
        ).fetchone()
        if existing is not None and str(existing["attempt_id"]) != attempt_id:
            raise ValueError("Runtime Session ID is already mapped to another Attempt")
        if existing is None:
            now = _now()
            conn.execute(
                """
                INSERT INTO agent_runtime_sessions (
                    runtime_session_id, attempt_id, launch_key, status, engine_name,
                    runtime_metadata_json, created_at, finished_at, adopted_at
                ) VALUES (?, ?, ?, 'finished', 'legacy-resolution', ?, ?, ?, ?)
                """,
                (
                    runtime_session_id,
                    attempt_id,
                    f"resolution:{issue['issue_id']}",
                    _canonical_json({"issue_id": str(issue["issue_id"])}),
                    now,
                    now,
                    now,
                ),
            )

    def _resolved_invariant_blockers(self, conn: sqlite3.Connection, run_id: str) -> set[str]:
        """Return categories whose persisted resolution no longer matches state.

        The append-only resolution record proves that an operator made a
        decision.  It does not by itself prove a later direct SQL change,
        failed manual follow-up, or a reverted Environment mapping did not
        invalidate that decision.  Reconciliation therefore re-checks the
        narrow invariant associated with every resolution type.
        """

        rows = conn.execute(
            """
            SELECT issue.issue_id, issue.category, issue.record_type, issue.record_id,
                   issue.resolution_type, resolution.payload_json, resolution.applied_at
            FROM domain_migration_issues AS issue
            LEFT JOIN domain_migration_resolutions AS resolution
              ON resolution.run_id = issue.run_id
             AND resolution.issue_id = issue.issue_id
             AND resolution.resolution_type = issue.resolution_type
             AND resolution.applied_at IS NOT NULL
            WHERE issue.run_id = ? AND issue.resolution_status = 'resolved'
            """,
            (run_id,),
        ).fetchall()
        blockers: set[str] = set()
        for row in rows:
            if row["applied_at"] is None:
                blockers.add(str(row["category"]))
                continue
            payload = _parse_json_object(row["payload_json"])
            resolution_type = str(row["resolution_type"] or "")
            if resolution_type == "owner_mapping":
                valid = self._owner_resolution_holds(conn, row, payload)
            elif resolution_type == "environment_mapping":
                valid = self._environment_resolution_holds(conn, row, payload)
            elif resolution_type == "primary_workspace":
                valid = self._primary_resolution_holds(conn, row, payload)
            elif resolution_type == "session_mapping":
                valid = self._session_resolution_holds(conn, row, payload)
            else:
                valid = False
            if not valid:
                blockers.add(str(row["category"]))
        return blockers

    def _owner_resolution_holds(
        self, conn: sqlite3.Connection, issue: sqlite3.Row, payload: dict[str, object]
    ) -> bool:
        owner_user_id = payload.get("owner_user_id")
        if not isinstance(owner_user_id, str) or not owner_user_id:
            return False
        try:
            self._auth_username(owner_user_id)
        except (LookupError, ValueError):
            return False
        record_type = str(issue["record_type"])
        record_id = str(issue["record_id"])
        if record_type == "project":
            project_id = payload.get("project_id", record_id)
            if not isinstance(project_id, str) or project_id != record_id:
                return False
            return (
                conn.execute(
                    "SELECT 1 FROM projects WHERE project_id = ? AND owner_user_id = ?",
                    (project_id, owner_user_id),
                ).fetchone()
                is not None
            )
        if record_type == "workspace":
            return (
                conn.execute(
                    "SELECT 1 FROM workspaces WHERE workspace_id = ? AND owner_user_id = ?",
                    (record_id, owner_user_id),
                ).fetchone()
                is not None
            )
        if record_type == "task":
            return (
                conn.execute(
                    "SELECT 1 FROM tasks WHERE task_id = ? AND owner_user_id = ?",
                    (record_id, owner_user_id),
                ).fetchone()
                is not None
            )
        return False

    @staticmethod
    def _environment_resolution_holds(
        conn: sqlite3.Connection, issue: sqlite3.Row, payload: dict[str, object]
    ) -> bool:
        environment_id = payload.get("environment_id", payload.get("replacement_environment_id"))
        if not isinstance(environment_id, str) or not environment_id:
            return False
        active_environment = conn.execute(
            "SELECT 1 FROM environments WHERE environment_id = ? AND status = 'active'",
            (environment_id,),
        ).fetchone()
        if active_environment is None:
            return False
        category = str(issue["category"])
        if category == "legacy_environment_placeholder":
            source_environment_id = payload.get("source_environment_id", issue["record_id"])
            if not isinstance(source_environment_id, str) or not source_environment_id:
                return False
            if source_environment_id == environment_id:
                return True
            workspace_reference = conn.execute(
                "SELECT 1 FROM workspaces WHERE environment_id = ?", (source_environment_id,)
            ).fetchone()
            task_reference = conn.execute(
                "SELECT 1 FROM tasks WHERE environment_id = ?", (source_environment_id,)
            ).fetchone()
            return workspace_reference is None and task_reference is None
        if category == "task_domain_mapping_invalid":
            task_id = str(issue["record_id"])
            workspace_id = payload.get("workspace_id")
            if not isinstance(workspace_id, str) or not workspace_id:
                return False
            row = conn.execute(
                """
                SELECT 1 FROM tasks AS task
                JOIN projects AS project ON project.project_id = task.project_id
                JOIN workspaces AS workspace ON workspace.workspace_id = task.workspace_id
                WHERE task.task_id = ?
                  AND task.workspace_id = ?
                  AND task.environment_id = ?
                  AND workspace.environment_id = ?
                  AND workspace.status = 'active'
                """,
                (task_id, workspace_id, environment_id, environment_id),
            ).fetchone()
            return row is not None
        workspace_id = payload.get("workspace_id", issue["record_id"])
        if not isinstance(workspace_id, str) or not workspace_id:
            return False
        return (
            conn.execute(
                """
                SELECT 1 FROM workspaces
                WHERE workspace_id = ? AND environment_id = ?
                """,
                (workspace_id, environment_id),
            ).fetchone()
            is not None
        )

    @staticmethod
    def _primary_resolution_holds(
        conn: sqlite3.Connection, issue: sqlite3.Row, payload: dict[str, object]
    ) -> bool:
        workspace_id = payload.get("workspace_id", issue["record_id"])
        default_project_id = issue["record_id"] if str(issue["record_type"]) == "project" else None
        project_id = payload.get("project_id", default_project_id)
        if not isinstance(project_id, str) or not isinstance(workspace_id, str):
            return False
        return (
            conn.execute(
                """
                SELECT 1 FROM project_workspace_links
                WHERE project_id = ? AND workspace_id = ?
                  AND status = 'active' AND is_primary = 1
                """,
                (project_id, workspace_id),
            ).fetchone()
            is not None
        )

    @staticmethod
    def _session_resolution_holds(
        conn: sqlite3.Connection, issue: sqlite3.Row, payload: dict[str, object]
    ) -> bool:
        attempt_id = payload.get("attempt_id")
        if not isinstance(attempt_id, str) or not attempt_id:
            return False
        runtime_session_id = payload.get("runtime_session_id")
        if not isinstance(runtime_session_id, str) or not runtime_session_id:
            runtime_session_id = f"resolved-runtime-{issue['issue_id']}"
        return (
            conn.execute(
                """
                SELECT 1 FROM agent_runtime_sessions
                WHERE runtime_session_id = ? AND attempt_id = ?
                """,
                (runtime_session_id, attempt_id),
            ).fetchone()
            is not None
        )

    def _auth_username(self, user_id: str) -> str:
        """Require a durable auth identity without making a cross-DB write."""

        auth_path = self._state_root / "runtime" / "auth.sqlite3"
        if not auth_path.is_file():
            raise LookupError("No auth database exists for Project owner resolution")
        auth_uri = f"{auth_path.resolve().as_uri()}?mode=ro"
        with closing(sqlite3.connect(auth_uri, uri=True)) as auth_conn:
            row = auth_conn.execute(
                "SELECT username FROM users WHERE id = ?", (user_id,)
            ).fetchone()
        if row is None:
            raise LookupError(f"Unknown auth user for Project owner resolution: {user_id}")
        username = row[0]
        if not isinstance(username, str) or not username:
            raise ValueError("Project owner auth identity has no valid username")
        return username

    @staticmethod
    def _validate_restore_evidence(value: object) -> dict[str, object]:
        if not isinstance(value, dict):
            raise ValueError("restore_evidence must be an object")
        evidence = {str(key): item for key, item in value.items()}
        manifest_sha256 = evidence.get("manifest_sha256")
        validated_at = evidence.get("validated_at")
        if evidence.get("status") != "valid":
            raise ValueError("restore_evidence must have status='valid'")
        if not isinstance(manifest_sha256, str) or not DomainReconciliationService._is_sha256(
            manifest_sha256
        ):
            raise ValueError("restore_evidence requires a manifest_sha256 digest")
        if not isinstance(validated_at, str) or not validated_at:
            raise ValueError("restore_evidence requires validated_at")
        return evidence

    @staticmethod
    def _is_sha256(value: str) -> bool:
        return len(value) == 64 and all(
            character in "0123456789abcdef" for character in value.lower()
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
    def _issue_from_row(row: sqlite3.Row) -> MigrationIssue:
        return MigrationIssue(
            issue_id=str(row["issue_id"]),
            run_id=str(row["run_id"]),
            category=str(row["category"]),
            record_type=str(row["record_type"]),
            record_id=str(row["record_id"]),
            severity=str(row["severity"]),
            detail=str(row["detail"]),
            resolution_status=str(row["resolution_status"]),
            resolution_type=(
                str(row["resolution_type"]) if row["resolution_type"] is not None else None
            ),
            resolution=_parse_json_object(row["resolution_json"]),
            resolved_by_user_id=(
                str(row["resolved_by_user_id"]) if row["resolved_by_user_id"] is not None else None
            ),
            resolved_at=str(row["resolved_at"]) if row["resolved_at"] is not None else None,
        )
